import asyncio
import os
import sys
from pathlib import Path
from typing import Annotated

import structlog
import typer

from . import __version__
from .core import UpdateChecker
from .daemon import UpdateDaemon
from .utils.config import load_config
from .utils.logging import setup_logging

app = typer.Typer(
    name="distiller-update",
    help="Simple APT update checker for Pamir AI Distiller devices",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

logger = structlog.get_logger()


@app.command()
def check(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Configuration file path"),
    ] = None,
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Suppress output"),
    ] = False,
) -> None:
    if os.geteuid() != 0:
        typer.echo(
            typer.style(
                "Warning: This command requires root privileges for APT operations.",
                fg=typer.colors.YELLOW,
            ),
            err=True,
        )
        typer.echo(
            typer.style(
                "Please run with sudo: sudo distiller-update check", fg=typer.colors.YELLOW
            ),
            err=True,
        )
        raise typer.Exit(1)

    async def run() -> None:
        cfg = load_config(config)
        daemon = UpdateDaemon(cfg)
        await daemon.run_once()

        if not quiet:
            result = await daemon.checker.get_status()
            if result and result.has_updates:
                typer.echo(f"\n{result.summary}")
                if len(result.packages) <= 20:
                    typer.echo("\nPackages with updates:")
                    for pkg in result.packages:
                        typer.echo(f"  • {pkg.name}: {pkg.current_version} → {pkg.new_version}")
                typer.echo("\nRun 'sudo apt upgrade' to install updates")
            else:
                typer.echo("System is up to date")

    asyncio.run(run())


@app.command()
def daemon(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Configuration file path"),
    ] = None,
) -> None:
    if os.geteuid() != 0:
        typer.echo(
            typer.style(
                "Warning: This command requires root privileges for APT operations.",
                fg=typer.colors.YELLOW,
            ),
            err=True,
        )
        typer.echo(
            typer.style(
                "Please run with sudo: sudo distiller-update daemon", fg=typer.colors.YELLOW
            ),
            err=True,
        )
        raise typer.Exit(1)

    async def run() -> None:
        cfg = load_config(config)
        daemon = UpdateDaemon(cfg)
        await daemon.start()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        typer.echo("\nDaemon stopped")
        sys.exit(0)


@app.command()
def list(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Configuration file path"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
) -> None:
    async def run() -> None:
        cfg = load_config(config)
        checker = UpdateChecker(cfg)

        result = await checker.get_status()

        if not result:
            typer.echo("No cached update information. Run 'distiller-update check' first.")
            raise typer.Exit(1)

        if json_output:
            import json

            typer.echo(json.dumps(result.model_dump(mode="json"), indent=2, default=str))
        else:
            if result.has_updates:
                typer.echo(f"\n{result.summary}")
                typer.echo(f"Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

                typer.echo(f"{'Package':<30} {'Current':<15} {'Available':<15} {'Type':<10}")
                typer.echo("-" * 70)

                for pkg in result.packages:
                    update_type = "Rebuild" if pkg.update_type == "rebuild" else "Version"
                    typer.echo(
                        f"{pkg.name:<30} {pkg.current_version:<15} {pkg.new_version:<15} {update_type:<10}"
                    )

                if result.total_size > 0:
                    typer.echo(f"\nTotal download size: {result.packages[0].display_size}")

                rebuilds = [p for p in result.packages if p.update_type == "rebuild"]
                if rebuilds:
                    typer.echo("\nRebuilds detected: Same version with updated content")
            else:
                typer.echo("System is up to date")
                typer.echo(f"Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}")

    asyncio.run(run())


@app.command()
def version() -> None:
    typer.echo(f"distiller-update version {__version__}")


@app.command()
def reinstall_dirty(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Configuration file path"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", "-n", help="Show what would be reinstalled without doing it"),
    ] = False,
) -> None:
    if not dry_run and os.geteuid() != 0:
        typer.echo(
            typer.style(
                "Warning: This command requires root privileges for package installation.",
                fg=typer.colors.YELLOW,
            ),
            err=True,
        )
        typer.echo(
            typer.style(
                "Please run with sudo: sudo distiller-update reinstall-dirty",
                fg=typer.colors.YELLOW,
            ),
            err=True,
        )
        raise typer.Exit(1)

    async def run() -> None:
        import subprocess

        cfg = load_config(config)
        checker = UpdateChecker(cfg)

        result = await checker.get_status()

        if not result:
            typer.echo("No cached update information. Run 'distiller-update check' first.")
            raise typer.Exit(1)

        rebuilds = [p for p in result.packages if p.update_type == "rebuild"]

        if not rebuilds:
            typer.echo("No rebuild packages found. System packages are in sync.")
            return

        typer.echo(f"\nFound {len(rebuilds)} package(s) with checksum mismatches:")
        for pkg in rebuilds:
            typer.echo(f"  • {pkg.name} ({pkg.current_version})")
            if pkg.installed_checksum and pkg.repository_checksum:
                typer.echo(f"    Current: {pkg.installed_checksum[:16]}...")
                typer.echo(f"    Repository: {pkg.repository_checksum[:16]}...")

        if dry_run:
            typer.echo("\n[DRY RUN] Would reinstall the above packages")
            typer.echo("Run without --dry-run to actually reinstall")
            return

        if not typer.confirm("\nReinstall these packages?"):
            typer.echo("Cancelled")
            return

        for pkg in rebuilds:
            typer.echo(f"\nReinstalling {pkg.name}...")
            try:
                result = subprocess.run(
                    [
                        "/usr/bin/apt-get",
                        "install",
                        "--reinstall",
                        "-y",
                        f"{pkg.name}={pkg.current_version}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

                if result.returncode == 0:
                    typer.echo(f"  [OK] Successfully reinstalled {pkg.name}")
                else:
                    typer.echo(f"  [FAIL] Failed to reinstall {pkg.name}")
                    typer.echo(f"    Error: {result.stderr}")
            except subprocess.TimeoutExpired:
                typer.echo(f"  [TIMEOUT] Timeout while reinstalling {pkg.name}")
            except Exception as e:
                typer.echo(f"  [ERROR] Error reinstalling {pkg.name}: {e}")

        typer.echo("\nReinstallation complete. Run 'distiller-update check' to verify.")

    asyncio.run(run())


@app.command()
def config_show(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Configuration file path"),
    ] = None,
) -> None:
    import json

    cfg = load_config(config)
    typer.echo(json.dumps(cfg.model_dump(mode="json"), indent=2, default=str))


def main() -> None:
    setup_logging()
    app()


if __name__ == "__main__":
    main()
