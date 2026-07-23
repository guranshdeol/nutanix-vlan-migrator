"""Pre-migration validations from description.md, section 1.

Each check returns Finding objects. Findings with level=ERROR block migration of
the affected subnet; level=WARNING are surfaced for visibility but do not block
(matching the "raise warning" wording in the spec), except trunked vNICs which
cause the subnet to be SKIPPED.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from .inventory import Inventory, Subnet


class Level(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass
class Finding:
    level: Level
    code: str
    message: str
    subnet_ext_id: Optional[str] = None


@dataclass
class SubnetValidation:
    subnet: Subnet
    findings: List[Finding] = field(default_factory=list)

    @property
    def has_error(self) -> bool:
        return any(f.level == Level.ERROR for f in self.findings)

    @property
    def skip(self) -> bool:
        # Trunked vNICs are unsupported -> skip (spec section 1: Trunked vNIC).
        return any(f.code == "TRUNKED_VNIC" for f in self.findings)

    @property
    def can_migrate(self) -> bool:
        return not self.has_error and not self.skip


class Validator:
    def __init__(self, inventory: Inventory):
        self.inv = inventory

    # ---- global checks -------------------------------------------------
    def duplicate_macs_global(self) -> List[Finding]:
        """Detect duplicate MAC addresses across all VMs (spec 1: MAC + dup MAC)."""
        mac_to_owners: Dict[str, list] = defaultdict(list)
        for vm in self.inv.vms():
            for nic in vm.nics:
                if nic.mac_address:
                    mac_to_owners[nic.mac_address].append((vm, nic))

        findings: List[Finding] = []
        for mac, owners in mac_to_owners.items():
            distinct_vms = {vm.ext_id for vm, _ in owners}
            if len(owners) > 1:
                if len(distinct_vms) > 1:
                    findings.append(
                        Finding(
                            Level.ERROR,
                            "DUPLICATE_MAC_MULTI_VM",
                            f"MAC {mac} shared across {len(distinct_vms)} VMs: "
                            f"{sorted(distinct_vms)}. "
                            "Multiple VMs detected with identical MAC addresses. "
                            "Please raise a Support ticket.",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            Level.ERROR,
                            "DUPLICATE_MAC",
                            f"Duplicate MAC {mac} detected on {len(owners)} NICs. "
                            "Please raise a Support ticket.",
                        )
                    )
        return findings

    # ---- per-subnet checks --------------------------------------------
    def validate_subnet(self, subnet: Subnet) -> SubnetValidation:
        result = SubnetValidation(subnet=subnet)

        if not subnet.is_basic_vlan:
            result.findings.append(
                Finding(
                    Level.ERROR,
                    "NOT_BASIC",
                    f"Subnet '{subnet.name}' is not a Basic VLAN subnet "
                    f"(type={subnet.subnet_type}, advanced={subnet.is_advanced}); "
                    "nothing to migrate.",
                    subnet.ext_id,
                )
            )
            return result

        pairs = self.inv.nics_on_subnet(subnet.ext_id)

        # Trunked vNIC detection (unsupported -> warn + skip).
        trunked = [(vm, nic) for vm, nic in pairs if nic.is_trunked]
        if trunked:
            vms = sorted({vm.name or vm.ext_id for vm, _ in trunked})
            result.findings.append(
                Finding(
                    Level.WARNING,
                    "TRUNKED_VNIC",
                    "Trunked vNICs are not supported for automated migration. "
                    f"Skipping subnet '{subnet.name}'. Affected VMs: {vms}. "
                    "Mark for support escalation.",
                    subnet.ext_id,
                )
            )

        # Multiple VLANs attached to a single VM (warning for visibility).
        for vm, _nic in pairs:
            distinct_subnets = set(vm.subnet_ext_ids())
            if len(distinct_subnets) > 1:
                result.findings.append(
                    Finding(
                        Level.WARNING,
                        "MULTI_VLAN_VM",
                        f"VM '{vm.name or vm.ext_id}' is attached to "
                        f"{len(distinct_subnets)} subnets. If migration fails: "
                        "Migration failed due to multiple VLANs attached to the VM. "
                        "Please raise a Support ticket.",
                        subnet.ext_id,
                    )
                )

        # Service compatibility (best-effort; deep checks are enforced by the
        # migration task itself and are only partially observable via the API).
        result.findings.extend(self._service_compat(subnet))

        return result

    def _service_compat(self, subnet: Subnet) -> List[Finding]:
        """Best-effort service-compatibility signal.

        The authoritative incompatibility gate (old Nutanix Files, SyncRep on
        unsupported AOS, etc.) is enforced inside the migrate-subnets task. We
        surface an INFO so operators know it is checked server-side, and leave a
        hook for environment-specific pre-checks.
        """
        return [
            Finding(
                Level.INFO,
                "SERVICE_COMPAT",
                "Service-compatibility (older Nutanix Files, SyncRep on "
                "unsupported AOS, etc.) is enforced server-side by the migration "
                "task. If incompatible, the task fails with: Incompatible service "
                "dependency detected. Please raise a Support ticket.",
                subnet.ext_id,
            )
        ]

    # ---- orchestration -------------------------------------------------
    def validate_all(self, subnets: List[Subnet]) -> tuple:
        """Return (global_findings, [SubnetValidation])."""
        global_findings = self.duplicate_macs_global()
        per_subnet = [self.validate_subnet(s) for s in subnets]
        # A global duplicate-MAC error blocks everything (spec: migration fails
        # immediately). Attach it to each subnet as a blocking error.
        if any(f.level == Level.ERROR for f in global_findings):
            for sv in per_subnet:
                sv.findings.extend(global_findings)
        return global_findings, per_subnet
