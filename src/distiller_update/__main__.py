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
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Run apt-get update before listing"),
    ] = False,
) -> None:
    async def run() -> None:
        cfg = load_config(config)
        checker = UpdateChecker(cfg)

        if refresh:
            packages = await checker.apt.check_updates(refresh=True)
            from datetime import datetime

            from .models import UpdateResult
            result = UpdateResult(
                packages=packages,
                checked_at=datetime.now(),
                distribution=cfg.distribution,
            )
        else:
            cached_result = await checker.get_status()
            if cached_result is None:
                typer.echo("No cached update information. Run 'distiller-update check' first.")
                raise typer.Exit(1)
            result = cached_result

        if result is None:
            typer.echo("No cached update information. Run 'distiller-update check' first.")
            raise typer.Exit(1)

        if json_output:
            import json

            typer.echo(json.dumps({
                "has_updates": result.has_updates,
                "packages": [p.model_dump() for p in result.packages],
                "summary": result.summary,
                "checked_at": result.checked_at.isoformat() + "Z",
            }, indent=2, default=str))
        else:
            if result.has_updates:
                typer.echo(f"\n{result.summary}")
                typer.echo(f"Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}\n")

                typer.echo(f"{'Package':<30} {'Current':<15} {'Available':<15} {'Type':<10}")
                typer.echo("-" * 70)

                for pkg in result.packages:
                    action = "install" if pkg.current_version is None else "upgrade"
                    current = pkg.current_version or "(new)"
                    typer.echo(
                        f"{pkg.name:<30} {current:<15} {pkg.new_version:<15} {action:<10}"
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
                proc_result = subprocess.run(
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

                if proc_result.returncode == 0:
                    typer.echo(f"  [OK] Successfully reinstalled {pkg.name}")
                else:
                    typer.echo(f"  [FAIL] Failed to reinstall {pkg.name}")
                    typer.echo(f"    Error: {proc_result.stderr}")
            except subprocess.TimeoutExpired:
                typer.echo(f"  [TIMEOUT] Timeout while reinstalling {pkg.name}")
            except Exception as e:
                typer.echo(f"  [ERROR] Error reinstalling {pkg.name}: {e}")

        typer.echo("\nReinstallation complete. Run 'distiller-update check' to verify.")

    asyncio.run(run())


@app.command()
def apply(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Configuration file path"),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output as JSON"),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Run apt-get update before applying"),
    ] = False,
) -> None:
    if os.geteuid() != 0:
        typer.echo(
            typer.style(
                "Warning: This command requires root privileges for package installation.",
                fg=typer.colors.YELLOW,
            ),
            err=True,
        )
        typer.echo(
            typer.style(
                "Please run with sudo: sudo distiller-update apply", fg=typer.colors.YELLOW
            ),
            err=True,
        )
        raise typer.Exit(1)

    async def run() -> None:
        cfg = load_config(config)
        from .apt import AptInterface
        apt_interface = AptInterface(cfg)

        # Build the same plan as list
        actions = await apt_interface.check_updates(refresh=refresh)
        if not actions:
            if json_output:
                import json
                typer.echo(json.dumps({"ok": True, "message": "Nothing to do"}, indent=2))
            else:
                typer.echo("Nothing to do.")
            return

        result = await apt_interface.apply(actions)

        if json_output:
            import json
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
