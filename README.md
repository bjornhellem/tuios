# TuiOS

TuiOS is a matrix-themed terminal launcher for local TUI (text user interface) utilities.

## What it does

- Shows a desktop-style TUI shell (`tuios_tui.py`).
- Auto-discovers local apps with `tui` in the filename.
- Lets you launch tools from one menu.
- Provides quick system info (time, host, user, Python version, disk, uptime).

## Included apps and functions

- `tuios_tui.py`  
  Main launcher for all TUI apps in this folder.

- `nmap_tui.py`  
  Interactive network scanning UI built on `nmap`.
  - Run predefined/custom scans
  - View parsed hosts/ports
  - Save results to JSON/CSV
  - Jump to SSH for discovered hosts

- `ssh_tui.py`  
  SSH connection manager.
  - Manage saved hosts
  - Launch SSH sessions
  - Uses `ssh_hosts.txt` for host definitions

- `system_info_tui.py`  
  Local system information dashboard in TUI form.

- `calendar_tui.py`  
  Matrix-themed calendar with week/month/year views, date jumping, and JSON events storage.

- `file_manager_tui.py`  
  Terminal file manager with matrix-style UI for browsing and inspecting files.

- `snake_tui.py`  
  Classic Snake game with difficulty levels and persistent scoreboard.

- `python_editor_tui.py`  
  Matrix-themed Python code editor with syntax highlighting, cleanup, and run support.
  Features: multi-file tabs, search/replace, go-to line, and line selection with copy/cut/delete.

## Supporting files

- `ssh_hosts.txt`  
  Tab-separated host definitions used by `ssh_tui.py`.

- `nmap_scan_*.csv`  
  Previously saved scan exports from `nmap_tui.py`.

## Run

From `LocalStuff`:

```bash
python3 tuios/tuios_tui.py
```

Or run any tool directly from this folder:

```bash
python3 tuios/nmap_tui.py
python3 tuios/ssh_tui.py
python3 tuios/system_info_tui.py
python3 tuios/file_manager_tui.py
python3 tuios/calendar_tui.py
```

## Dependencies

### Core (all TuiOS apps)

- Python 3.10+ (uses only Python standard library modules)
- A terminal that supports `curses` (macOS/Linux terminal)

### External CLI tools by app

- `tuios_tui.py`
  - `uptime`

- `nmap_tui.py`
  - `nmap` (required)
  - `ssh` (optional, for "SSH to host" action from scan results)

- `ssh_tui.py`
  - `ssh` (OpenSSH client, required)

- `system_info_tui.py`
  - Cross-platform/common: `df`, `ps`, `uptime`
  - macOS: `top`, `sysctl`, `vm_stat`, `system_profiler`, `diskutil`, `ifconfig`, `netstat`, `pmset`
  - Linux: `ip` (`iproute2`), `lspci` (`pciutils`, optional for GPU details)

- `file_manager_tui.py`
  - `sudo` (optional, only when elevated copy/move/chmod is needed)
  - `cp`, `mv`, `chmod` (used during sudo fallback flow)

### Quick install examples

- macOS (Homebrew): `brew install nmap`
- Debian/Ubuntu: `sudo apt install nmap openssh-client iproute2 pciutils`
- Fedora/RHEL: `sudo dnf install nmap openssh-clients iproute pciutils`

## Notes

- `nmap_tui.py` requires `nmap` installed and available in `PATH`.
- `ssh_tui.py` requires `ssh` available in `PATH`.
