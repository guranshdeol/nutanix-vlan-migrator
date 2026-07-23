"""Command-line interface for the rolling VLAN Basic->Advanced migration tool.

Subcommands:
  list-basic   List Basic VLAN subnets eligible for migration.
  validate     Run pre-migration validations only (no changes).
  migrate      Validate, then migrate (rolling, with retry + post-verify).
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from .client import PrismCentralClient
from .config import AppConfig
from .inventory import Inventory, Subnet
from .migrator import Migrator, Outcome
from .validators import Level, SubnetValidation, Validator


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _select_subnets(inv: Inventory, args) -> List[Subnet]:
    basic = inv.basic_vlan_subnets()
    if getattr(args, "all", False):
        return basic
    wanted = set(getattr(args, "subnet", []) or [])
    if not wanted:
        return []
    selected = [s for s in basic if s.ext_id in wanted or s.name in wanted]
    missing = wanted - {s.ext_id for s in selected} - {s.name for s in selected}
    if missing:
        print(f"WARNING: not found among Basic VLAN subnets: {sorted(missing)}",
              file=sys.stderr)
    return selected


def _print_validation(svs: List[SubnetValidation]) -> None:
    for sv in svs:
        status = "MIGRATE" if sv.can_migrate else ("SKIP" if sv.skip else "BLOCKED")
        print(f"\n[{status}] {sv.subnet.name} (vlan={sv.subnet.vlan_id}, {sv.subnet.ext_id})")
        if not sv.findings:
            print("    - no findings")
        for f in sv.findings:
            print(f"    - {f.level.value}: [{f.code}] {f.message}")


def cmd_interactive(args, cfg: AppConfig) -> int:
    # cfg is loaded lazily inside the interactive flow, so ignore the preloaded one.
    from .interactive import run_interactive

    return run_interactive(args.config, verbose=args.verbose)


def cmd_list_basic(args, cfg: AppConfig) -> int:
    client = PrismCentralClient(cfg.prism_central)
    inv = Inventory(client)
    basic = inv.basic_vlan_subnets()
    if not basic:
        print("No Basic VLAN subnets found.")
        return 0
    print(f"Basic VLAN subnets ({len(basic)}):")
    for s in basic:
        vms = len(inv.vms_on_subnet(s.ext_id))
        print(f"  - {s.name:30} vlan={s.vlan_id}  vms={vms}  extId={s.ext_id}")
    return 0


def cmd_validate(args, cfg: AppConfig) -> int:
    client = PrismCentralClient(cfg.prism_central)
    inv = Inventory(client)
    subnets = _select_subnets(inv, args)
    if not subnets:
        print("No subnets selected. Use --all or --subnet <extId|name>.", file=sys.stderr)
        return 2
    validator = Validator(inv)
    global_findings, svs = validator.validate_all(subnets)
    if global_findings:
        print("Global findings:")
        for f in global_findings:
            print(f"    - {f.level.value}: [{f.code}] {f.message}")
    _print_validation(svs)
    blocked = [sv for sv in svs if not sv.can_migrate and not sv.skip]
    return 1 if blocked else 0


def cmd_migrate(args, cfg: AppConfig) -> int:
    client = PrismCentralClient(cfg.prism_central)
    inv = Inventory(client)
    subnets = _select_subnets(inv, args)
    if not subnets:
        print("No subnets selected. Use --all or --subnet <extId|name>.", file=sys.stderr)
        return 2

    validator = Validator(inv)
    _global, svs = validator.validate_all(subnets)
    _print_validation(svs)

    to_migrate = [sv.subnet for sv in svs if sv.can_migrate]
    skipped = [sv for sv in svs if not sv.can_migrate]
    if skipped:
        print(f"\nSkipping/blocking {len(skipped)} subnet(s) due to findings above.")
    if not to_migrate:
        print("Nothing eligible to migrate.")
        return 1
    if args.dry_run:
        print(f"\n[dry-run] Would migrate {len(to_migrate)} subnet(s): "
              f"{[s.name for s in to_migrate]}")
        return 0

    print(f"\nMigrating {len(to_migrate)} subnet(s) (rolling)...")
    migrator = Migrator(client, inv, cfg)
    results = migrator.migrate_many(to_migrate)

    print("\n==== Migration summary ====")
    exit_code = 0
    for r in results:
        print(f"  {r.outcome.value:9} {r.subnet.name} "
              f"(attempts={r.attempts}) - {r.detail}")
        for c in r.post_checks:
            print(f"        {c}")
        if r.outcome == Outcome.FAILED:
            exit_code = 1
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vlan-migrator",
        description="Rolling Nutanix VLAN Basic->Advanced migration (v4 APIs).",
    )
    p.add_argument("-c", "--config", default="config.yaml", help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    # No subcommand -> interactive launcher.
    sub = p.add_subparsers(dest="command", required=False)

    ip = sub.add_parser("interactive", help="launch the interactive TUI (default)")
    ip.set_defaults(func=cmd_interactive)

    lp = sub.add_parser("list-basic", help="list Basic VLAN subnets")
    lp.set_defaults(func=cmd_list_basic)

    def add_selectors(sp):
        sp.add_argument("--subnet", action="append", metavar="EXTID|NAME",
                        help="subnet to target (repeatable)")
        sp.add_argument("--all", action="store_true", help="target all Basic VLANs")

    vp = sub.add_parser("validate", help="run pre-migration validations only")
    add_selectors(vp)
    vp.set_defaults(func=cmd_validate)

    mp = sub.add_parser("migrate", help="validate then migrate (rolling)")
    add_selectors(mp)
    mp.add_argument("--dry-run", action="store_true",
                    help="validate and show plan without migrating")
    mp.set_defaults(func=cmd_migrate)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # No subcommand (or explicit `interactive`) -> launch the TUI, which loads
    # or interactively creates the config itself.
    if args.command in (None, "interactive"):
        from .interactive import run_interactive

        return run_interactive(args.config, verbose=args.verbose)

    _setup_logging(args.verbose)
    try:
        cfg = AppConfig.load(args.config)
    except Exception as exc:  # noqa: BLE001
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
