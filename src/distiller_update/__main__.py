"""CLI interface for distiller-update using Typer."""

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
from .models import Config

app = typer.Typer(
    name="distiller-update",
    help="Simple APT update checker for Pamir AI Distiller devices",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)

logger = structlog.get_logger()


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file or defaults."""
    if config_path and config_path.exists():
        try:
            import tomllib

            with open(config_path, "rb") as f:
                data = tomllib.load(f)
                cfg = Config(**data)
                logger.info(f"Loaded config from {config_path}")
                return cfg
        except ValueError as e:
            # Pydantic validation error
            logger.error(f"Config validation failed for {config_path}: {e}")
            typer.echo(
                typer.style(
                    f"Config validation error in {config_path}:\n  {e}",
                    fg=typer.colors.RED,
                ),
                err=True,
            )
            raise typer.Exit(1) from None
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")

    # Try default locations
    for path in [
        Path("/etc/distiller-update/config.toml"),
        Path.home() / ".config/distiller-update/config.toml",
    ]:
        if path.exists():
            try:
                import tomllib

                with open(path, "rb") as f:
                    data = tomllib.load(f)
                    cfg = Config(**data)
                    logger.info(f"Loaded config from {path}")
                    return cfg
            except ValueError as e:
                # Pydantic validation error - report it clearly
                logger.error(f"Config validation failed for {path}: {e}")
                typer.echo(
                    typer.style(
                        f"Config validation error in {path}:\n  {e}",
                        fg=typer.colors.RED,
                    ),
                    err=True,
                )
                # Don't try next location on validation errors - fail fast
                raise typer.Exit(1) from None
            except Exception as e:
                # Other errors (TOML syntax, etc.) - log and try next
                logger.debug(f"Failed to load config from {path}: {e}")
                continue

    # Use defaults
    logger.info("Using default configuration")
    return Config()


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
    """Check for updates once and exit."""

    # Check if running as root
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
            # Get and display results
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
    """Run as a daemon, checking periodically for updates."""

    # Check if running as root
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
    """List currently available updates."""

    async def run() -> None:
        cfg = load_config(config)
        checker = UpdateChecker(cfg)

        # Check if we have cached results
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

                # Display packages in a table format
                typer.echo(f"{'Package':<30} {'Current':<15} {'Available':<15} {'Type':<10}")
                typer.echo("-" * 70)

                for pkg in result.packages:
                    update_type = "Rebuild" if pkg.update_type == "rebuild" else "Version"
                    typer.echo(
                        f"{pkg.name:<30} {pkg.current_version:<15} {pkg.new_version:<15} {update_type:<10}"
                    )

                if result.total_size > 0:
                    typer.echo(f"\nTotal download size: {result.packages[0].display_size}")

                # Show rebuild notice if any rebuilds are present
                rebuilds = [p for p in result.packages if p.update_type == "rebuild"]
                if rebuilds:
                    typer.echo("\nRebuilds detected: Same version with updated content")
            else:
                typer.echo("System is up to date")
                typer.echo(f"Last checked: {result.checked_at.strftime('%Y-%m-%d %H:%M:%S')}")

    asyncio.run(run())


@app.command()
def version() -> None:
    """Show version information."""
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
    """Reinstall packages with checksum mismatches (dirty rebuilds)."""

    # Check if running as root
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

        # Get current status
        result = await checker.get_status()

        if not result:
            typer.echo("No cached update information. Run 'distiller-update check' first.")
            raise typer.Exit(1)

        # Filter for rebuilds only
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

        # Confirm before proceeding
        if not typer.confirm("\nReinstall these packages?"):
            typer.echo("Cancelled")
            return

        # Reinstall each package
        for pkg in rebuilds:
            typer.echo(f"\nReinstalling {pkg.name}...")
            try:
                # Use apt-get install --reinstall
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
    """Show current configuration."""
    import json

    cfg = load_config(config)
    typer.echo(json.dumps(cfg.model_dump(mode="json"), indent=2, default=str))


def main() -> None:
    """Main entry point."""
    # Setup logging
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    app()


if __name__ == "__main__":
    main()
