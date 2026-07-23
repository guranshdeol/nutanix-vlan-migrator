"""Migration orchestrator (description.md sections 2 & 3).

Per subnet: run the migrate-subnets action, hold via the server-side migration
lock (handled by the task), poll the task with one automatic retry on failure,
then run post-migration verification.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .client import PrismCentralClient, TaskFailed, extract_task_ext_id
from .config import AppConfig
from .inventory import Inventory, Subnet
from .portpoll import PortPoller

log = logging.getLogger("vlan_migrator.migrator")

MIGRATE_SUBNETS_PATH = "/networking/v4.3/config/$actions/migrate-subnets"
CLUSTERS_PATH = "/clustermgmt/v4.0/config/clusters"


class Outcome(str, Enum):
    MIGRATED = "MIGRATED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


@dataclass
class MigrationResult:
    subnet: Subnet
    outcome: Outcome
    task_ext_id: Optional[str] = None
    attempts: int = 0
    detail: str = ""
    post_checks: List[str] = field(default_factory=list)


class Migrator:
    def __init__(self, client: PrismCentralClient, inventory: Inventory, cfg: AppConfig):
        self.client = client
        self.inv = inventory
        self.cfg = cfg

    # ---- CVM/host target discovery for port polling --------------------
    def discover_poll_targets(self) -> List[str]:
        if self.cfg.port_polling.targets:
            return self.cfg.port_polling.targets
        targets: List[str] = []
        try:
            clusters = self.client.get_all(CLUSTERS_PATH)
        except Exception as exc:  # noqa: BLE001 - discovery is best-effort
            log.warning("could not auto-discover CVM targets: %s", exc)
            return targets
        for c in clusters:
            network = c.get("network") or {}
            # External/data-services IP shapes vary slightly by version; grab
            # the common ones so we have something to probe port 2121 against.
            for key in ("externalAddress", "externalDataServicesIp"):
                node = network.get(key) or {}
                v4 = (node.get("ipv4") or {}).get("value")
                if v4:
                    targets.append(v4)
        return targets

    # ---- core migration of a single subnet -----------------------------
    def migrate_subnet(self, subnet: Subnet, poller: Optional[PortPoller] = None) -> MigrationResult:
        result = MigrationResult(subnet=subnet, outcome=Outcome.FAILED)
        max_attempts = self.cfg.migration.max_retries + 1  # first try + retries

        for attempt in range(1, max_attempts + 1):
            result.attempts = attempt
            try:
                log.info(
                    "migrating subnet '%s' (%s) attempt %d/%d",
                    subnet.name, subnet.ext_id, attempt, max_attempts,
                )
                task_id = self._invoke_migration(subnet)
                result.task_ext_id = task_id
                self.client.wait_for_task(
                    task_id,
                    poll_interval=self.cfg.migration.task_poll_interval_secs,
                    timeout=self.cfg.migration.task_timeout_secs,
                    on_progress=lambda s, p: log.info(
                        "  task %s: %s %d%%", task_id, s, p
                    ),
                )
                result.outcome = Outcome.MIGRATED
                result.detail = "migration task succeeded"
                break
            except TaskFailed as exc:
                log.error("subnet '%s' attempt %d failed: %s", subnet.name, attempt, exc)
                result.detail = str(exc)
                if attempt >= max_attempts:
                    result.detail = (
                        "Migration failed after retry. Please raise a Support ticket."
                    )
                    return result
            except Exception as exc:  # noqa: BLE001
                log.error("subnet '%s' attempt %d error: %s", subnet.name, attempt, exc)
                result.detail = str(exc)
                if attempt >= max_attempts:
                    return result

        # ---- post-migration verification (section 3) ----
        result.post_checks = self._post_verify(subnet)
        return result

    def _invoke_migration(self, subnet: Subnet) -> str:
        body = {"subnets": [{"subnetUuid": subnet.ext_id}]}
        resp = self.client.post(MIGRATE_SUBNETS_PATH, json=body)
        task_id = extract_task_ext_id(resp)
        if not task_id:
            raise RuntimeError(
                f"migrate-subnets did not return a task reference: {resp}"
            )
        return task_id

    def _post_verify(self, subnet: Subnet) -> List[str]:
        checks: List[str] = []
        fresh = self.inv.get_subnet(subnet.ext_id, refresh=True)
        if fresh is None:
            checks.append("WARN: subnet no longer listed after migration")
            return checks
        if fresh.is_advanced:
            checks.append("OK: subnet now Advanced (network-controller managed)")
        else:
            checks.append(
                f"WARN: subnet still not advanced (state={fresh.migration_state})"
            )
        # Logical ports / NIC connectivity intact.
        pairs = self.inv.nics_on_subnet(subnet.ext_id)
        disconnected = [
            f"{vm.name}:{nic.mac_address}" for vm, nic in pairs if not nic.is_connected
        ]
        if disconnected:
            checks.append(f"WARN: disconnected NICs after migration: {disconnected}")
        else:
            checks.append(f"OK: all {len(pairs)} NIC(s) report connected")
        return checks

    # ---- rolling driver ------------------------------------------------
    def migrate_many(self, subnets: List[Subnet]) -> List[MigrationResult]:
        results: List[MigrationResult] = []
        targets = self.discover_poll_targets() if self.cfg.port_polling.enabled else []
        poller = (
            PortPoller(targets, self.cfg.port_polling.port, self.cfg.port_polling.interval_secs)
            if self.cfg.port_polling.enabled
            else None
        )
        if poller:
            poller.start()
        try:
            for subnet in subnets:
                results.append(self.migrate_subnet(subnet, poller))
                self.inv.invalidate()
        finally:
            if poller:
                poller.stop()
        return results
