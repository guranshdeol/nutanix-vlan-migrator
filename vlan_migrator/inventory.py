"""Fetch and model subnets, VMs, and NICs from Prism Central v4 APIs."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .client import PrismCentralClient

SUBNETS_PATH = "/networking/v4.3/config/subnets"
VMS_PATH = "/vmm/v4.0/ahv/config/vms"


@dataclass
class Subnet:
    ext_id: str
    name: str
    subnet_type: str          # VLAN | OVERLAY
    vlan_id: Optional[int]    # networkId
    is_advanced: bool         # isAdvancedNetworking
    cluster_ref: Optional[str]
    bridge_name: Optional[str]
    migration_state: Optional[str]
    raw: dict = field(default_factory=dict)

    @property
    def is_basic_vlan(self) -> bool:
        """Basic == a VLAN subnet not yet managed by the network controller."""
        return self.subnet_type == "VLAN" and not self.is_advanced

    @classmethod
    def from_api(cls, d: dict) -> "Subnet":
        return cls(
            ext_id=d.get("extId"),
            name=d.get("name", ""),
            subnet_type=d.get("subnetType", ""),
            vlan_id=d.get("networkId"),
            is_advanced=bool(d.get("isAdvancedNetworking", False)),
            cluster_ref=d.get("clusterReference"),
            bridge_name=d.get("bridgeName"),
            migration_state=d.get("migrationState"),
            raw=d,
        )


@dataclass
class Nic:
    ext_id: Optional[str]
    mac_address: Optional[str]
    is_connected: bool
    subnet_ext_id: Optional[str]
    vlan_mode: Optional[str]        # ACCESS | TRUNK
    trunked_vlans: List[int] = field(default_factory=list)
    learned_ips: List[str] = field(default_factory=list)

    @property
    def is_trunked(self) -> bool:
        return (self.vlan_mode or "").upper() == "TRUNK" or bool(self.trunked_vlans)

    @classmethod
    def from_api(cls, d: dict) -> "Nic":
        backing = d.get("backingInfo") or {}
        net = d.get("networkInfo") or {}
        subnet = net.get("subnet") or {}
        ipv4_info = net.get("ipv4Info") or {}
        learned = [
            ip.get("value")
            for ip in (ipv4_info.get("learnedIpAddresses") or [])
            if isinstance(ip, dict) and ip.get("value")
        ]
        return cls(
            ext_id=d.get("extId"),
            mac_address=(backing.get("macAddress") or "").lower() or None,
            is_connected=bool(backing.get("isConnected", False)),
            subnet_ext_id=subnet.get("extId"),
            vlan_mode=net.get("vlanMode"),
            trunked_vlans=list(net.get("trunkedVlans") or []),
            learned_ips=learned,
        )


@dataclass
class Vm:
    ext_id: str
    name: str
    nics: List[Nic] = field(default_factory=list)

    @classmethod
    def from_api(cls, d: dict) -> "Vm":
        return cls(
            ext_id=d.get("extId"),
            name=d.get("name", ""),
            nics=[Nic.from_api(n) for n in (d.get("nics") or [])],
        )

    def subnet_ext_ids(self) -> List[str]:
        return [n.subnet_ext_id for n in self.nics if n.subnet_ext_id]


class Inventory:
    """Loads and caches PC inventory needed for validation and migration."""

    def __init__(self, client: PrismCentralClient):
        self._client = client
        self._subnets: Optional[List[Subnet]] = None
        self._vms: Optional[List[Vm]] = None

    # ---- subnets -------------------------------------------------------
    def subnets(self, refresh: bool = False) -> List[Subnet]:
        if self._subnets is None or refresh:
            rows = self._client.get_all(SUBNETS_PATH)
            self._subnets = [Subnet.from_api(r) for r in rows]
        return self._subnets

    def basic_vlan_subnets(self) -> List[Subnet]:
        return [s for s in self.subnets() if s.is_basic_vlan]

    def get_subnet(self, ext_id: str, refresh: bool = False) -> Optional[Subnet]:
        for s in self.subnets(refresh=refresh):
            if s.ext_id == ext_id:
                return s
        return None

    # ---- vms / nics ----------------------------------------------------
    def vms(self, refresh: bool = False) -> List[Vm]:
        if self._vms is None or refresh:
            rows = self._client.get_all(VMS_PATH)
            self._vms = [Vm.from_api(r) for r in rows]
        return self._vms

    def vms_on_subnet(self, subnet_ext_id: str) -> List[Vm]:
        return [v for v in self.vms() if subnet_ext_id in v.subnet_ext_ids()]

    def nics_on_subnet(self, subnet_ext_id: str) -> List[tuple]:
        """Return (vm, nic) pairs attached to the given subnet."""
        out = []
        for vm in self.vms():
            for nic in vm.nics:
                if nic.subnet_ext_id == subnet_ext_id:
                    out.append((vm, nic))
        return out

    def invalidate(self) -> None:
        self._subnets = None
        self._vms = None
