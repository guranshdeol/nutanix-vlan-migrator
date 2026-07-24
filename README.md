# Nutanix VLAN Migrator

Interactive, safety-first CLI to perform **rolling migration of Nutanix VLAN subnets from Basic to Advanced (network-controller managed)** mode — with pre-migration validation, automatic retry, background connectivity polling, and post-migration verification.

Built entirely on the **Nutanix v4 API namespaces** (`networking` v4.3, `vmm` v4.0, `prism` v4.3, `clustermgmt` v4.0). Runs isolated inside its own virtualenv — nothing touches your system Python or PATH.

---

## Quick start (one line)

**macOS / Linux**
```bash
curl -fsSL https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.sh | bash
```

**Windows (PowerShell)**
```powershell
irm https://raw.githubusercontent.com/guranshdeol/nutanix-vlan-migrator/main/install.ps1 | iex
```

The installer finds Python 3.8+, installs the tool into an isolated virtualenv (`~/.nutanix-vlan-migrator/venv`), adds a global **`vlan-migrator`** command to your PATH, and launches the interactive UI immediately. After that, just type `vlan-migrator` from any directory.

> If `vlan-migrator` isn't found right after install, open a new terminal (or run `export PATH="$HOME/.local/bin:$PATH"`) so the updated PATH takes effect.

---

## What it does

The tool implements a three-phase workflow:

### 1. Pre-migration validation (read-only)
- **Duplicate MAC detection** across all VMs (and the same MAC shared across multiple VMs) — blocks migration.
- **Trunked vNIC detection** — trunked vNICs are unsupported, so affected subnets are skipped and flagged for escalation.
- **Multiple VLANs per VM** — surfaced as a warning for visibility.
- **Service-compatibility signal** — the authoritative gate (older Nutanix Files, SyncRep on unsupported AOS, etc.) is enforced server-side by the migration task; the tool surfaces this and any failures.

### 2. Migration execution
- Invokes the public **`migrate-subnets`** action (`POST /networking/v4.3/config/$actions/migrate-subnets`) — the supported equivalent of the internal `kVlanSubnetMigration` RPC.
- **Background port-2121 polling** from PC to CVM/host targets for connectivity observability during migration.
- **Automatic single retry** on the first failure; a second failure stops and reports for support.
- Migrates **one subnet at a time** (rolling) for safety.

### 3. Post-migration verification
- Confirms the subnet is now Advanced (network-controller managed).
- Confirms logical ports / NICs remain connected.
- Tracks the underlying task to `SUCCEEDED` via the `prism` Tasks API.

> Internal mechanics — the migration lock (`kMigrationInProgress`), legacy Basic-VLAN cleanup in Zeus/IDF, and unlock — are handled server-side by the migration task. The tool drives and verifies the outcome rather than reaching into those internals.

---

## Requirements

- **Python 3.8+**
- **git** — auto-installed by the installer if missing (Homebrew/apt/dnf/yum/pacman/zypper/apk on macOS/Linux; winget/choco on Windows)
- Network access to a **Prism Central** with:
  - PC 7.3+ / AOS 7.3+ (v4 `networking` GA)
  - **Network Controller enabled** (required for Advanced subnets)
- A PC user with permission to read subnets/VMs and run subnet migration.

---

## Usage

### Interactive (default)
```bash
vlan-migrator
```
You get an arrow-key menu: **List Basic VLANs · Validate · Migrate · Reload · Quit**, with colored tables, checkbox subnet selection, confirmation prompts, and a live migration summary.

### Non-interactive (automation / CI)
```bash
vlan-migrator list-basic                              # list Basic VLAN subnets
vlan-migrator validate --all                          # validate every Basic VLAN
vlan-migrator validate --subnet vlan100               # validate specific subnet(s)
vlan-migrator migrate --subnet vlan100 --dry-run      # show plan, no changes
vlan-migrator migrate --all                           # rolling migrate all eligible
```
Exit codes: `0` success, `1` findings/failures, `2` usage/config error.

---

## Configuration

On first interactive run the tool prompts for connection details and offers to save a `config.yaml` (the password is **never** written to disk). You can also copy the template:

```bash
cp config.example.yaml config.yaml
export PC_PASSWORD='your-pc-password'   # preferred over storing in the file
```

```yaml
prism_central:
  host: 10.0.0.10
  port: 9440
  username: admin
  verify_ssl: false        # set true + ca_bundle in production
migration:
  max_retries: 1           # first failure -> one automatic retry
  task_timeout_secs: 1800
  rolling: true            # one subnet at a time
port_polling:
  enabled: true
  port: 2121
  targets: []              # auto-discovered from clustermgmt if empty
```

`config.yaml` is git-ignored so environment-specific hosts/secrets never get committed.

---

## Manual install (without the one-liner)

```bash
git clone https://github.com/guranshdeol/nutanix-vlan-migrator.git
cd nutanix-vlan-migrator
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/vlan-migrator
```

---

## Uninstall

Everything lives in one isolated directory plus two PATH symlinks:
```bash
rm -rf ~/.nutanix-vlan-migrator
rm -f  ~/.local/bin/vlan-migrator ~/.local/bin/vlanmig
```
On Windows: delete `%USERPROFILE%\.nutanix-vlan-migrator` and the `vlan-migrator.cmd` launcher in `%USERPROFILE%\.local\bin`.

---

## Safety notes

- Always run `validate` (or `migrate --dry-run`) first and review findings.
- Migrations are rolling and gated by server-side validation; blocked subnets are never forced.
- The tool makes **no** direct changes to Zeus/IDF or migration locks — those are handled by Nutanix.

---

## License

Provided as-is for operational automation. Review and test in a non-production environment first.
