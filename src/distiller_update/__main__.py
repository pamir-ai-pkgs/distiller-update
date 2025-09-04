"""CLI interface for Distiller Update Notifier"""

import argparse
import json
import logging
import sys

from . import __version__
from .checker import UpdateChecker
from .config import Config
from .daemon import UpdateDaemon
from .notifiers import StatusNotifier

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def cmd_check(args: argparse.Namespace) -> int:
    """Run update check once"""
    daemon = UpdateDaemon(args.config)
    daemon.run_once()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List available updates"""
    config = Config(args.config)
    checker = UpdateChecker(config)

    updates = checker.check_updates()

    if not updates:
        print("No updates available")
        return 0

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    updates.sort(key=lambda p: priority_order.get(p.priority, 99))

    print(f"\n{'Package':<30} {'Installed':<15} {'Available':<15} {'Priority':<10}")
    print("-" * 70)

    # Print updates
    for pkg in updates:
        print(
            f"{pkg.name:<30} {pkg.installed_version:<15} "
            f"{pkg.available_version:<15} {pkg.priority:<10}"
        )

    # Print summary
    print(f"\nTotal: {len(updates)} update{'s' if len(updates) != 1 else ''} available")

    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show current status"""
    config = Config(args.config)
    status_notifier = StatusNotifier(config)

    # Read status file
    status = status_notifier.read_status()

    if not status:
        print("No status available. Run 'distiller-update check' first.")
        return 1

    if args.json:
        # Output as JSON
        print(json.dumps(status, indent=2, default=str))
    else:
        # Human-readable output
        print("\n=== Distiller Update Status ===")
        print(f"Last check: {status.get('last_check', 'Never')}")
        print(f"Next check: {status.get('next_check', 'Unknown')}")
        print(f"Updates available: {'Yes' if status.get('update_available') else 'No'}")

        if status.get("update_available"):
            print(f"Total updates: {status.get('total_updates', 0)}")

            # Show priority breakdown
            if "summary" in status and "by_priority" in status["summary"]:
                priorities = status["summary"]["by_priority"]
                priority_str = []
                for level, count in priorities.items():
                    if count > 0:
                        priority_str.append(f"{count} {level}")
                if priority_str:
                    print(f"By priority: {', '.join(priority_str)}")

            # Show important packages
            if "updates" in status:
                important = [
                    u for u in status["updates"] if u.get("priority") in ["critical", "high"]
                ]
                if important:
                    print("\nImportant updates:")
                    for pkg in important[:5]:
                        print(
                            f"  - {pkg['name']}: {pkg['installed_version']} -> {pkg['available_version']}"
                        )
                    if len(important) > 5:
                        print(f"  ... and {len(important) - 5} more")

        # Show system info if available
        if "system_info" in status:
            info = status["system_info"]
            if info:
                print(f"\nSystem: {info.get('os', 'Unknown')}")
                print(f"Architecture: {info.get('architecture', 'Unknown')}")
                print(f"Hostname: {info.get('hostname', 'Unknown')}")

    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show configuration"""
    config = Config(args.config)

    print("\n=== Distiller Update Configuration ===")
    print("\nRepository:")
    print(f"  URL: {config.repository.url}")
    print(f"  Distributions: {', '.join(config.repository.distributions)}")

    print("\nChecking:")
    print(f"  Interval: {config.checking.interval_seconds} seconds")
    print(f"  On startup: {config.checking.on_startup}")
    print(f"  Cache file: {config.checking.cache_file}")

    print("\nNotifications:")
    print(f"  MOTD: {'Enabled' if config.notifications.motd.enabled else 'Disabled'}")
    print(f"  Journal: {'Enabled' if config.notifications.journal.enabled else 'Disabled'}")
    print(f"  Status file: {'Enabled' if config.notifications.status_file.enabled else 'Disabled'}")
    print(f"  Log file: {'Enabled' if config.notifications.log_file.enabled else 'Disabled'}")

    print("\nFilters:")
    if config.filters.include_packages:
        print(f"  Include: {', '.join(config.filters.include_packages)}")
    if config.filters.exclude_packages:
        print(f"  Exclude: {', '.join(config.filters.exclude_packages)}")
    print(f"  Check architecture: {config.filters.check_architecture}")
    print(f"  Priority levels: {', '.join(config.filters.priority_levels)}")

    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    """Run as daemon"""
    daemon = UpdateDaemon(args.config)

    try:
        daemon.run()
        return 0
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
        return 0
    except Exception as e:
        logger.error(f"Daemon failed: {e}")
        return 1


def main() -> int:
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        prog="distiller-update",
        description="Distiller Update Notifier - Lightweight update notifications for headless systems",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--config",
        "-c",
        help="Configuration file path",
        default=None,
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output",
    )

    # Subcommands
    subparsers = parser.add_subparsers(
        dest="command",
        help="Available commands",
        required=True,
    )

    # Check command
    check_parser = subparsers.add_parser(
        "check",
        help="Check for updates once",
    )
    check_parser.set_defaults(func=cmd_check)

    # List command
    list_parser = subparsers.add_parser(
        "list",
        help="List available updates",
    )
    list_parser.set_defaults(func=cmd_list)

    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show current status",
    )
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    status_parser.set_defaults(func=cmd_status)

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Show configuration",
    )
    config_parser.set_defaults(func=cmd_config)

    # Daemon command
    daemon_parser = subparsers.add_parser(
        "daemon",
        help="Run as daemon (for systemd)",
    )
    daemon_parser.set_defaults(func=cmd_daemon)

    # Parse arguments
    args = parser.parse_args()

    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Execute command
    try:
        return args.func(args)
    except Exception as e:
        logger.error(f"Command failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
