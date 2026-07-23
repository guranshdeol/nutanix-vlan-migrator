"""Configuration loading for the VLAN migration tool."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class PrismCentralConfig:
    host: str
    port: int = 9440
    username: str = "admin"
    password: Optional[str] = None
    verify_ssl: bool = False
    ca_bundle: Optional[str] = None
    timeout_secs: int = 60


@dataclass
class MigrationConfig:
    task_poll_interval_secs: int = 5
    task_timeout_secs: int = 1800
    max_retries: int = 1
    rolling: bool = True


@dataclass
class PortPollingConfig:
    enabled: bool = True
    port: int = 2121
    interval_secs: int = 5
    targets: List[str] = field(default_factory=list)


@dataclass
class ReachabilityConfig:
    enabled: bool = False
    ping_count: int = 2
    ping_timeout_secs: int = 2


@dataclass
class AppConfig:
    prism_central: PrismCentralConfig
    migration: MigrationConfig = field(default_factory=MigrationConfig)
    port_polling: PortPollingConfig = field(default_factory=PortPollingConfig)
    reachability: ReachabilityConfig = field(default_factory=ReachabilityConfig)

    @classmethod
    def load(cls, path: str) -> "AppConfig":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        pc_raw = raw.get("prism_central") or {}
        if not pc_raw.get("host"):
            raise ValueError("config: prism_central.host is required")

        pc = PrismCentralConfig(**pc_raw)
        # Environment variable overrides secrets in the file.
        pc.password = os.environ.get("PC_PASSWORD", pc.password)
        if not pc.password:
            raise ValueError(
                "PC password not set. Provide prism_central.password or PC_PASSWORD env var."
            )

        return cls(
            prism_central=pc,
            migration=MigrationConfig(**(raw.get("migration") or {})),
            port_polling=PortPollingConfig(**(raw.get("port_polling") or {})),
            reachability=ReachabilityConfig(**(raw.get("reachability") or {})),
        )
