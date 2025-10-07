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

app = typer.Typer(name="distiller-update", no_args_is_help=True)


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
        cfg = get_config(config)
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
    refresh: Annotated[bool, typer.Option("--refresh")] = False,
) -> None:
    """List available updates."""

    cfg = get_config(config)
    checker = UpdateChecker(cfg)

    if refresh:
        with get_spinner("Refreshing package information..."):
            packages = checker.check_updates(refresh=True)
            result = UpdateResult(
                packages=packages,
                checked_at=datetime.now(),
                distribution=cfg.distribution,
            )
        show_step("Package information refreshed", success=True)
    else:
        cached_result = checker.get_status()
        if not cached_result:
            console.print("[red]No cached update information.[/red]")
            console.print("Run 'distiller-update check' first.")
            raise typer.Exit(1)
        result = cached_result

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


@app.command()
def apply(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
    refresh: Annotated[bool, typer.Option("--refresh")] = False,
) -> None:
    """Apply updates."""
    ensure_root()

    cfg = get_config(config)
    checker = UpdateChecker(cfg)

    if not json_output:
        with get_spinner("Checking for available updates..."):
            actions = checker.check_updates(refresh=refresh)
    else:
        actions = checker.check_updates(refresh=refresh)

    if not actions:
        if json_output:
            typer.echo(json.dumps({"ok": True, "message": "Nothing to do"}, indent=2))
        else:
            show_step("No updates to install", success=True)
        return

    if not json_output:
        console.print(
            f"\n[bold cyan]Installing {len(actions)} package{'s' if len(actions) != 1 else ''}...[/bold cyan]"
        )
        for pkg in actions:
            console.print(f"  → {pkg.name}: {pkg.current_version or '(new)'} → {pkg.new_version}")
        console.print()

        # Show progress during installation
        with get_spinner("Installing packages (this may take a while)..."):
            result = checker.apply(actions)
    else:
        result = checker.apply(actions)

    if json_output:
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
    setup_logging()
    app()


if __name__ == "__main__":
    main()
