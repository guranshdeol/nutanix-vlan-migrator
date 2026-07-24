"""Interactive terminal launcher for the VLAN migration tool.

Provides a colored, menu-driven session (arrow-key selection, checkboxes,
confirmations, live progress) on top of the same core used by the classic
subcommands. Uses `rich` + `questionary`; both are declared dependencies.
"""
from __future__ import annotations

import getpass
import logging
import os
import sys
from typing import List, Optional

import questionary
import yaml
from questionary import Choice
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from .client import ApiError, PrismCentralClient
from .config import AppConfig, PrismCentralConfig
from .inventory import Inventory, Subnet
from .migrator import Migrator, Outcome
from .validators import Level, SubnetValidation, Validator

console = Console()

BANNER = r"""
 __     ___    _    _   _   __  __ _                 _
 \ \   / / |  / \  | \ | | |  \/  (_) __ _ _ __ __ _| |_ ___  _ __
  \ \ / /| | / _ \ |  \| | | |\/| | |/ _` | '__/ _` | __/ _ \| '__|
   \ V / | |/ ___ \| |\  | | |  | | | (_| | | | (_| | || (_) | |
    \_/  |_/_/   \_\_| \_| |_|  |_|_|\__, |_|  \__,_|\__\___/|_|
                                     |___/  Basic -> Advanced (v4)
"""

_STYLE = questionary.Style(
    [
        ("qmark", "fg:#00afff bold"),
        ("question", "bold"),
        ("pointer", "fg:#00afff bold"),
        ("highlighted", "fg:#00afff bold"),
        ("selected", "fg:#5fd700"),
    ]
)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, show_path=False, rich_tracebacks=True)],
    )


# --------------------------------------------------------------------------
# Connection / config setup
# --------------------------------------------------------------------------
def _load_or_prompt_config(config_path: str) -> Optional[AppConfig]:
    if os.path.exists(config_path):
        try:
            cfg = AppConfig.load(config_path)
            console.print(f"[green]Loaded config[/] from [bold]{config_path}[/]")
            return cfg
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]Config at {config_path} unusable:[/] {exc}")
            if not questionary.confirm(
                "Enter connection details interactively instead?", default=True, style=_STYLE
            ).ask():
                return None
    else:
        console.print(f"[yellow]No config file at {config_path}.[/] Let's set one up.")

    host = questionary.text("Prism Central host / VIP:", style=_STYLE).ask()
    if not host:
        return None
    port = questionary.text("Port:", default="9440", style=_STYLE).ask()
    username = questionary.text("Username:", default="admin", style=_STYLE).ask()
    password = getpass.getpass("Password (input hidden): ")
    verify_ssl = questionary.confirm("Verify TLS certificate?", default=False, style=_STYLE).ask()

    pc = PrismCentralConfig(
        host=host,
        port=int(port or 9440),
        username=username or "admin",
        password=password,
        verify_ssl=bool(verify_ssl),
    )
    cfg = AppConfig(prism_central=pc)

    if questionary.confirm(
        f"Save these settings to {config_path}? (password NOT saved)",
        default=True,
        style=_STYLE,
    ).ask():
        _save_config(config_path, cfg)
        console.print(
            f"[green]Saved.[/] Set [bold]PC_PASSWORD[/] env var to avoid re-entering "
            "the password next time."
        )
    return cfg


def _save_config(path: str, cfg: AppConfig) -> None:
    pc = cfg.prism_central
    data = {
        "prism_central": {
            "host": pc.host,
            "port": pc.port,
            "username": pc.username,
            "password": None,  # never persist the secret
            "verify_ssl": pc.verify_ssl,
            "ca_bundle": pc.ca_bundle,
            "timeout_secs": pc.timeout_secs,
        },
        "migration": vars(cfg.migration),
        "port_polling": vars(cfg.port_polling),
        "reachability": vars(cfg.reachability),
    }
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False)


def _test_connection(client: PrismCentralClient) -> bool:
    with console.status("[cyan]Testing connection to Prism Central..."):
        try:
            client.get("/networking/v4.3/config/subnets", params={"$page": 0, "$limit": 1})
            return True
        except ApiError as exc:
            console.print(f"[red]Connection/auth failed:[/] {exc}")
            return False
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Could not reach Prism Central:[/] {exc}")
            return False


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------
def _subnet_table(inv: Inventory, subnets: List[Subnet]) -> Table:
    table = Table(title="Basic VLAN Subnets", header_style="bold cyan")
    table.add_column("Name")
    table.add_column("VLAN", justify="right")
    table.add_column("VMs", justify="right")
    table.add_column("Cluster")
    table.add_column("extId", style="dim")
    for s in subnets:
        vms = len(inv.vms_on_subnet(s.ext_id))
        table.add_row(s.name, str(s.vlan_id), str(vms), inv.cluster_name(s.cluster_ref), s.ext_id)
    return table


def _decision(sv: SubnetValidation):
    """Return (label, color, plain-English meaning)."""
    if sv.can_migrate:
        return ("READY", "green", "Passed all checks - safe to migrate")
    if sv.skip:
        return ("SKIP", "yellow", "Trunked vNICs found (not supported) - will be skipped")
    return ("BLOCKED", "red", "Blocking issues found - fix these before migrating")


def _render_validation(inv: Inventory, svs: List[SubnetValidation]) -> None:
    """Print a clear validation report: a table of decisions + real issues,
    a legend explaining each decision, and a single note about server-side checks."""
    table = Table(title="Validation Results", header_style="bold cyan", show_lines=True)
    table.add_column("Subnet")
    table.add_column("VLAN", justify="right")
    table.add_column("VMs", justify="right")
    table.add_column("Cluster")
    table.add_column("Decision")
    table.add_column("Issues to review")

    had_service_note = False
    for sv in svs:
        label, color, _meaning = _decision(sv)
        issues = []
        for f in sv.findings:
            if f.level == Level.INFO:
                if f.code == "SERVICE_COMPAT":
                    had_service_note = True
                continue  # INFO notes are summarized below, not per-row
            tag = "red" if f.level == Level.ERROR else "yellow"
            issues.append(f"[{tag}]•[/] {f.message}")
        vms = len(inv.vms_on_subnet(sv.subnet.ext_id))
        table.add_row(
            sv.subnet.name,
            str(sv.subnet.vlan_id),
            str(vms),
            inv.cluster_name(sv.subnet.cluster_ref),
            f"[{color}]{label}[/]",
            "\n".join(issues) if issues else "[green]None - all checks passed[/]",
        )
    console.print(table)

    # Legend + counts so the decision column is self-explanatory.
    ready = sum(1 for sv in svs if sv.can_migrate)
    skip = sum(1 for sv in svs if sv.skip)
    blocked = sum(1 for sv in svs if not sv.can_migrate and not sv.skip)
    console.print(
        f"\n[bold]Summary:[/] [green]{ready} READY[/] · "
        f"[yellow]{skip} SKIP[/] · [red]{blocked} BLOCKED[/]"
    )
    console.print(
        "[dim]READY = passed all checks, safe to migrate.  "
        "SKIP = has trunked vNICs (unsupported).  "
        "BLOCKED = has errors (e.g. duplicate MACs) that must be fixed first.[/]"
    )
    if had_service_note:
        console.print(
            "[dim]Note: deeper service-compatibility checks (older Nutanix Files, "
            "SyncRep on unsupported AOS, etc.) are run automatically by Prism Central "
            "during the migration itself.[/]"
        )


def _pick_subnets(inv: Inventory, basics: List[Subnet]) -> List[Subnet]:
    choices = []
    for s in basics:
        vms = len(inv.vms_on_subnet(s.ext_id))
        choices.append(
            Choice(title=f"{s.name}  (vlan {s.vlan_id}, {vms} VMs)", value=s.ext_id)
        )
    picked = questionary.checkbox(
        "Select subnets (space to toggle, enter to confirm):",
        choices=choices,
        style=_STYLE,
    ).ask()
    if not picked:
        return []
    return [s for s in basics if s.ext_id in set(picked)]


# --------------------------------------------------------------------------
# Actions
# --------------------------------------------------------------------------
def _action_list(inv: Inventory) -> None:
    basics = inv.basic_vlan_subnets()
    if not basics:
        console.print("[green]No Basic VLAN subnets found - nothing to migrate.[/]")
        return
    console.print(_subnet_table(inv, basics))


def _action_validate(inv: Inventory) -> None:
    basics = inv.basic_vlan_subnets()
    if not basics:
        console.print("[green]No Basic VLAN subnets found.[/]")
        return
    targets = _pick_subnets(inv, basics)
    if not targets:
        console.print("[yellow]No subnets selected.[/]")
        return
    with console.status("[cyan]Validating..."):
        _global, svs = Validator(inv).validate_all(targets)
    _render_validation(inv, svs)


def _action_migrate(inv: Inventory, client: PrismCentralClient, cfg: AppConfig) -> None:
    basics = inv.basic_vlan_subnets()
    if not basics:
        console.print("[green]No Basic VLAN subnets found.[/]")
        return
    targets = _pick_subnets(inv, basics)
    if not targets:
        console.print("[yellow]No subnets selected.[/]")
        return

    with console.status("[cyan]Running pre-migration validation..."):
        _global, svs = Validator(inv).validate_all(targets)
    _render_validation(inv, svs)

    eligible = [sv.subnet for sv in svs if sv.can_migrate]
    if not eligible:
        console.print("[red]Nothing eligible to migrate after validation.[/]")
        return

    console.print(
        Panel.fit(
            "\n".join(f"  • {s.name} (vlan {s.vlan_id})" for s in eligible),
            title=f"[bold]Will migrate {len(eligible)} subnet(s)[/]",
            border_style="cyan",
        )
    )
    if not questionary.confirm(
        f"Proceed with rolling migration of {len(eligible)} subnet(s)?",
        default=False,
        style=_STYLE,
    ).ask():
        console.print("[yellow]Cancelled.[/]")
        return

    migrator = Migrator(client, inv, cfg)
    results = migrator.migrate_many(eligible)

    summary = Table(title="Migration Summary", header_style="bold cyan")
    summary.add_column("Subnet")
    summary.add_column("Outcome")
    summary.add_column("Attempts", justify="right")
    summary.add_column("Detail / post-checks")
    ocolor = {Outcome.MIGRATED: "green", Outcome.SKIPPED: "yellow", Outcome.FAILED: "red"}
    for r in results:
        detail = r.detail + ("\n" + "\n".join(r.post_checks) if r.post_checks else "")
        summary.add_row(
            r.subnet.name,
            f"[{ocolor[r.outcome]}]{r.outcome.value}[/]",
            str(r.attempts),
            detail,
        )
    console.print(summary)


# --------------------------------------------------------------------------
# Main loop
# --------------------------------------------------------------------------
def run_interactive(config_path: str, verbose: bool = False) -> int:
    _setup_logging(verbose)
    console.print(f"[bold cyan]{BANNER}[/]")

    # The interactive UI needs a real terminal for menus/keyboard input.
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        console.print(
            "[yellow]No interactive terminal detected.[/]\n"
            "Run [bold]vlan-migrator[/] directly in your terminal for the menu UI, "
            "or use the non-interactive subcommands, e.g.:\n"
            "  [bold]vlan-migrator list-basic[/]\n"
            "  [bold]vlan-migrator validate --all[/]\n"
            "  [bold]vlan-migrator migrate --subnet <name|extId> --dry-run[/]"
        )
        return 2

    cfg = _load_or_prompt_config(config_path)
    if cfg is None:
        console.print("[red]No configuration - exiting.[/]")
        return 2

    client = PrismCentralClient(cfg.prism_central)
    if not _test_connection(client):
        return 1
    console.print(
        f"[green]Connected[/] to [bold]{cfg.prism_central.host}[/] "
        f"as [bold]{cfg.prism_central.username}[/]\n"
    )

    inv = Inventory(client)

    while True:
        action = questionary.select(
            "What would you like to do?",
            choices=[
                Choice("List Basic VLAN subnets", "list"),
                Choice("Validate subnets (dry, no changes)", "validate"),
                Choice("Migrate subnets (Basic -> Advanced)", "migrate"),
                Choice("Reload inventory from Prism Central", "reload"),
                Choice("Quit", "quit"),
            ],
            style=_STYLE,
        ).ask()

        if action in (None, "quit"):
            console.print("[cyan]Bye.[/]")
            return 0
        try:
            if action == "list":
                _action_list(inv)
            elif action == "validate":
                _action_validate(inv)
            elif action == "migrate":
                _action_migrate(inv, client, cfg)
                inv.invalidate()
            elif action == "reload":
                inv.invalidate()
                with console.status("[cyan]Refreshing inventory..."):
                    inv.subnets(refresh=True)
                    inv.vms(refresh=True)
                console.print("[green]Inventory refreshed.[/]")
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted - returning to menu.[/]")
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]Error:[/] {exc}")
        console.print()
