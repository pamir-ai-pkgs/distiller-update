import asyncio
import json
import os
import sys
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
) -> None:
    """Check for updates."""
    ensure_root()

    cfg = get_config(config)
    daemon = UpdateDaemon(cfg)
    daemon.run_once()

    if not quiet:
        result = daemon.checker.get_status()
        if result and result.has_updates:
            typer.echo(f"\n{result.summary}")
            if len(result.packages) <= 20:
                typer.echo("\nPackages with updates:")
                for pkg in result.packages:
                    typer.echo(f"  • {pkg.name}: {pkg.current_version} → {pkg.new_version}")
            typer.echo("\nRun 'sudo apt upgrade' to install updates")
        else:
            typer.echo("System is up to date")


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
        packages = checker.check_updates(refresh=True)
        result = UpdateResult(
            packages=packages,
            checked_at=datetime.now(),
            distribution=cfg.distribution,
        )
    else:
        cached_result = checker.get_status()
        if not cached_result:
            typer.echo("No cached update information. Run 'distiller-update check' first.")
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
            typer.echo(f"\n{result.summary}")
            typer.echo(f"Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

            typer.echo(f"{'Package':<30} {'Current':<15} {'Available':<15} {'Type':<10}")
            typer.echo("-" * 70)

            for pkg in result.packages:
                action = "install" if pkg.current_version is None else "upgrade"
                current = pkg.current_version or "(new)"
                typer.echo(f"{pkg.name:<30} {current:<15} {pkg.new_version:<15} {action:<10}")

            if result.total_size > 0:
                typer.echo(f"\nTotal download size: {result.packages[0].display_size}")
        else:
            typer.echo("System is up to date")
            typer.echo(f"Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}")


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

    actions = checker.check_updates(refresh=refresh)
    if not actions:
        if json_output:
            typer.echo(json.dumps({"ok": True, "message": "Nothing to do"}, indent=2))
        else:
            typer.echo("Nothing to do.")
        return

    result = checker.apply(actions)

    if json_output:
        typer.echo(json.dumps(result, indent=2, default=str))
    else:
        if result.get("ok"):
            typer.echo("Installation completed successfully")
            for item in result.get("results", []):
                if isinstance(item, dict) and "name" in item:
                    typer.echo(f"  {item['name']}: {item.get('installed', 'unknown')}")
        else:
            typer.echo(f"Installation failed: {result.get('error', 'Unknown error')}")

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
