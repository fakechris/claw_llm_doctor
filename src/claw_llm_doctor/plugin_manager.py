"""Plugin manager -- enable/disable the OpenClaw Gateway plugin."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path


OPENCLAW_DIR = Path.home() / ".openclaw"
EXTENSIONS_DIR = OPENCLAW_DIR / "extensions"
PLUGIN_ID = "claw-llm-doctor"
PLUGIN_DEST = EXTENSIONS_DIR / PLUGIN_ID
CONFIG_FILE = OPENCLAW_DIR / "openclaw.json"


def _get_bundled_plugin_dir() -> Path:
    """Return the path to the bundled plugin files inside the package."""
    ref = resources.files("claw_llm_doctor") / "_plugin"
    # resources.files returns a Traversable; for file-backed packages it
    # resolves to the actual filesystem path.
    return Path(str(ref))


def _read_config() -> dict:
    """Read the OpenClaw config, returning an empty dict if missing."""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(cfg: dict) -> None:
    """Write config back, creating parent dirs if needed."""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def enable_plugin(*, verbose: bool = True) -> bool:
    """Install the bundled plugin into OpenClaw extensions and enable it.

    Steps:
    1. Copy plugin files to ~/.openclaw/extensions/claw-llm-doctor/
    2. Run `npm install` in that directory
    3. Update openclaw.json config to enable the plugin
    4. Restart the OpenClaw daemon (if available)

    Returns True on success.
    """
    from rich.console import Console
    console = Console()

    # 1. Copy plugin files
    src = _get_bundled_plugin_dir()
    if not src.exists():
        console.print(f"[red]Error:[/red] bundled plugin files not found at {src}")
        return False

    EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)

    if PLUGIN_DEST.exists():
        # Preserve node_modules if it exists
        node_modules = PLUGIN_DEST / "node_modules"
        had_nm = node_modules.exists()
        nm_backup = PLUGIN_DEST.parent / f".{PLUGIN_ID}-node_modules-bak"
        if had_nm:
            if nm_backup.exists():
                shutil.rmtree(nm_backup)
            node_modules.rename(nm_backup)

        # Remove old files (except node_modules which was moved)
        shutil.rmtree(PLUGIN_DEST)
        PLUGIN_DEST.mkdir(parents=True)

        # Copy new files
        _copy_plugin(src, PLUGIN_DEST)

        # Restore node_modules
        if had_nm and nm_backup.exists():
            nm_backup.rename(PLUGIN_DEST / "node_modules")
    else:
        PLUGIN_DEST.mkdir(parents=True)
        _copy_plugin(src, PLUGIN_DEST)

    if verbose:
        console.print(f"  Copied plugin to [cyan]{PLUGIN_DEST}[/cyan]")

    # 2. npm install
    if verbose:
        console.print("  Running [cyan]npm install[/cyan]...")
    try:
        result = subprocess.run(
            ["npm", "install", "--no-fund", "--no-audit"],
            cwd=str(PLUGIN_DEST),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            console.print(f"[yellow]Warning:[/yellow] npm install exited with code {result.returncode}")
            if result.stderr:
                console.print(f"  [dim]{result.stderr.strip()[:500]}[/dim]")
    except FileNotFoundError:
        console.print("[yellow]Warning:[/yellow] npm not found. Please run 'npm install' manually in:")
        console.print(f"  [cyan]{PLUGIN_DEST}[/cyan]")
    except subprocess.TimeoutExpired:
        console.print("[yellow]Warning:[/yellow] npm install timed out")

    # 3. Update config
    cfg = _read_config()
    plugins = cfg.setdefault("plugins", {})
    allow = plugins.setdefault("allow", [])
    if PLUGIN_ID not in allow:
        allow.append(PLUGIN_ID)
    entries = plugins.setdefault("entries", {})
    entries[PLUGIN_ID] = entries.get(PLUGIN_ID, {})
    entries[PLUGIN_ID]["enabled"] = True
    _write_config(cfg)

    if verbose:
        console.print(f"  Updated [cyan]{CONFIG_FILE}[/cyan]")

    # 4. Restart daemon
    _restart_daemon(console, verbose)

    if verbose:
        console.print("\n[green]Plugin enabled successfully.[/green]")
        console.print(f"  Logs will be written to: [cyan]~/.openclaw/logs/llm-doctor/[/cyan]")
        console.print(f"  Verify with: [cyan]openclaw plugins list[/cyan]")

    return True


def disable_plugin(*, verbose: bool = True, remove_files: bool = False) -> bool:
    """Disable the plugin in OpenClaw config and optionally remove files.

    Returns True on success.
    """
    from rich.console import Console
    console = Console()

    # 1. Update config
    cfg = _read_config()
    plugins = cfg.get("plugins", {})
    entries = plugins.get("entries", {})
    if PLUGIN_ID in entries:
        entries[PLUGIN_ID]["enabled"] = False
        _write_config(cfg)
        if verbose:
            console.print(f"  Disabled plugin in [cyan]{CONFIG_FILE}[/cyan]")
    else:
        if verbose:
            console.print("  Plugin was not configured.")

    # 2. Optionally remove files
    if remove_files and PLUGIN_DEST.exists():
        shutil.rmtree(PLUGIN_DEST)
        if verbose:
            console.print(f"  Removed [cyan]{PLUGIN_DEST}[/cyan]")

    # 3. Restart daemon
    _restart_daemon(console, verbose)

    if verbose:
        console.print("\n[green]Plugin disabled.[/green]")

    return True


def plugin_status() -> dict:
    """Check the current plugin installation status."""
    installed = PLUGIN_DEST.exists()
    has_node_modules = (PLUGIN_DEST / "node_modules").exists() if installed else False

    cfg = _read_config()
    plugins = cfg.get("plugins", {})
    entries = plugins.get("entries", {})
    plugin_cfg = entries.get(PLUGIN_ID, {})
    enabled = plugin_cfg.get("enabled", False)
    in_allow = PLUGIN_ID in plugins.get("allow", [])

    return {
        "installed": installed,
        "has_node_modules": has_node_modules,
        "path": str(PLUGIN_DEST) if installed else None,
        "enabled": enabled,
        "in_allow_list": in_allow,
        "config_file": str(CONFIG_FILE),
    }


def _copy_plugin(src: Path, dest: Path) -> None:
    """Copy plugin files from src to dest, skipping __pycache__ and node_modules."""
    for item in src.iterdir():
        if item.name in ("node_modules", "__pycache__", ".DS_Store"):
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _restart_daemon(console, verbose: bool) -> None:
    """Try to restart the OpenClaw daemon."""
    try:
        result = subprocess.run(
            ["openclaw", "daemon", "restart"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if verbose:
            if result.returncode == 0:
                console.print("  Restarted OpenClaw daemon")
            else:
                console.print("[yellow]Warning:[/yellow] failed to restart daemon")
                if result.stderr:
                    console.print(f"  [dim]{result.stderr.strip()[:200]}[/dim]")
    except FileNotFoundError:
        if verbose:
            console.print("  [dim]openclaw not found -- skip daemon restart[/dim]")
    except subprocess.TimeoutExpired:
        if verbose:
            console.print("[yellow]Warning:[/yellow] daemon restart timed out")
