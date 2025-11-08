import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .checker import UpdateChecker
from .daemon import UpdateDaemon
from .models import Config, UpdateResult
from .utils.config import load_config
from .utils.logging import setup_logging
from .utils.ui import (
    console,
    format_package_table,
    format_time,
    get_spinner,
    print_summary,
    show_step,
)

app = typer.Typer(
    name="distiller-update",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode=None if os.getenv("TERM") == "dumb" else "rich",
)


def ensure_root() -> None:
    """Check if running as root, exit if not."""
    if os.geteuid() != 0:
        typer.echo("Error: This command requires root privileges.", err=True)
        raise typer.Exit(1)


def get_config(config_path: Path | None) -> Config:
    """Load configuration from file or defaults."""
    return load_config(config_path)


@app.command()
def check(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Check for updates."""
    ensure_root()

    if quiet:
        setup_logging("error")
    elif verbose:
        setup_logging("debug")
    else:
        setup_logging("warning")

    cfg = get_config(config)
    daemon = UpdateDaemon(cfg)

    if not quiet:
        start_time = time.time()
        with get_spinner("Checking for updates..."):
            daemon.run_once()
        elapsed = time.time() - start_time
        show_step(f"Update check completed ({format_time(elapsed)})", success=True)
    else:
        daemon.run_once()

    if not quiet:
        result = daemon.checker.get_status()
        if result and result.has_updates:
            print_summary(result.summary)

            if len(result.packages) <= 20:
                # Show table for reasonable number of packages
                table = format_package_table(result.packages)
                console.print(table)
            else:
                # For many packages, show count only
                console.print(
                    f"[yellow]Found {len(result.packages)} packages with updates[/yellow]"
                )
                console.print("Run 'distiller-update list' to see all packages")

            console.print(
                "\n[bold cyan]Run 'sudo distiller-update apply' to install updates[/bold cyan]"
            )
        else:
            show_step("System is up to date", success=True)
            if result:
                console.print(
                    f"[dim]Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
                )


@app.command()
def daemon(config: Annotated[Path | None, typer.Option("--config", "-c")] = None) -> None:
    """Run as daemon."""
    ensure_root()

    async def run() -> None:
        setup_logging("warning")
        cfg = get_config(config)

        # Reconfigure with config file's log level
        setup_logging(cfg.log_level)
        daemon = UpdateDaemon(cfg)
        await daemon.start()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        typer.echo("\nDaemon stopped")
        sys.exit(0)


@app.command()
def list(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List available updates."""
    setup_logging("warning")

    cfg = get_config(config)
    checker = UpdateChecker(cfg)

    with get_spinner("Refreshing package information..."):
        packages = checker.check_updates(refresh=True)
        result = UpdateResult(
            packages=packages,
            checked_at=datetime.now(),
            distribution=cfg.distribution,
        )
    show_step("Package information refreshed", success=True)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "has_updates": result.has_updates,
                    "packages": [p.model_dump() for p in result.packages],
                    "summary": result.summary,
                    "checked_at": result.checked_at.isoformat() + "Z",
                },
                indent=2,
                default=str,
            )
        )
    else:
        if result.has_updates:
            print_summary(result.summary)
            console.print(
                f"[dim]Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]\n"
            )

            # Use rich table for better formatting
            table = format_package_table(result.packages, show_size=True)
            console.print(table)

            if result.total_size > 0:
                console.print(
                    f"\n[cyan]Total download size: {result.packages[0].display_size}[/cyan]"
                )
        else:
            show_step("System is up to date", success=True)
            console.print(
                f"[dim]Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}[/dim]"
            )


def _validate_filter_flags(
    all_packages: bool, upgrade_only: bool, reinstall_only: bool
) -> None:
    """Validate that only one filter flag is specified."""
    flags_set = sum([all_packages, upgrade_only, reinstall_only])
    if flags_set > 1:
        typer.echo(
            "Error: --all, --upgrade, and --reinstall are mutually exclusive. "
            "Use only one filter flag at a time.",
            err=True,
        )
        raise typer.Exit(1)


@app.command()
def apply(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    refresh: Annotated[bool, typer.Option("--refresh")] = False,
    all_packages: Annotated[
        bool, typer.Option("--all", "-a", help="Apply all packages (default)")
    ] = False,
    upgrade_only: Annotated[
        bool, typer.Option("--upgrade", "-u", help="Only apply upgrades")
    ] = False,
    reinstall_only: Annotated[
        bool, typer.Option("--reinstall", "-r", help="Only apply reinstalls")
    ] = False,
) -> None:
    """Apply updates."""
    ensure_root()
    setup_logging("warning")

    # Validate mutual exclusivity of filter flags
    _validate_filter_flags(all_packages, upgrade_only, reinstall_only)

    cfg = get_config(config)
    checker = UpdateChecker(cfg)

    if not json_output:
        with get_spinner("Checking for available updates..."):
            actions = checker.check_updates(refresh=refresh)
    else:
        actions = checker.check_updates(refresh=refresh)

    # Apply filtering based on action type
    original_count = len(actions)
    if upgrade_only:
        actions = [pkg for pkg in actions if pkg.action_type == "Upgrade"]
        filter_name = "upgrades"
    elif reinstall_only:
        actions = [pkg for pkg in actions if pkg.action_type == "Reinstall"]
        filter_name = "reinstalls"
    else:
        # Default: apply all packages (no filter)
        filter_name = None

    # Check if filtering resulted in empty list
    if not actions and original_count > 0 and filter_name:
        if json_output:
            typer.echo(
                json.dumps(
                    {
                        "ok": True,
                        "message": f"No {filter_name} available (found {original_count} other packages)",
                    },
                    indent=2,
                )
            )
        else:
            show_step(f"No {filter_name} to apply", success=True)
            console.print(
                f"[yellow]({original_count} other package{'s' if original_count != 1 else ''} "
                f"available with different filters)[/yellow]"
            )
        return

    if not actions:
        if json_output:
            typer.echo(json.dumps({"ok": True, "message": "Nothing to do"}, indent=2))
        else:
            show_step("No updates to install", success=True)
        return

    if not json_output:
        # Show which filter is active in the preview
        if filter_name:
            item_type = filter_name
        else:
            item_type = f"package{'s' if len(actions) != 1 else ''}"

        console.print(f"\n[bold cyan]Installing {len(actions)} {item_type}...[/bold cyan]")
        for pkg in actions:
            console.print(f"  → {pkg.name}: {pkg.current_version or '(new)'} → {pkg.new_version}")
        console.print()

    # Run installation with native APT output
    result = checker.apply(actions)

    if json_output:
        # Emit result as JSON
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            show_step("Installation completed successfully", success=True)
            for item in result.get("results", []):
                if isinstance(item, dict) and "name" in item:
                    console.print(
                        f"  [green]✓[/green] {item['name']}: {item.get('installed', 'unknown')}"
                    )
        else:
            show_step(f"Installation failed: {result.get('error', 'Unknown error')}", error=True)

    raise typer.Exit(0 if result.get("ok") else result.get("rc", 2))


@app.command()
def version() -> None:
    """Show version."""
    typer.echo(f"distiller-update version {__version__}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
