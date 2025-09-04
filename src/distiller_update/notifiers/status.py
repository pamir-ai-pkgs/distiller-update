"""Status file notifier for machine-readable update information"""

import json
import logging
from datetime import datetime
from pathlib import Path

from ..checker import Package
from ..config import Config

logger = logging.getLogger(__name__)


class StatusNotifier:
    """Write update status to JSON file"""

    def __init__(self, config: Config) -> None:
        """Initialize status notifier"""
        self.config = config.notifications.status_file
        self.status_file = Path(self.config.path)

    def notify(self, updates: list[Package], summary: dict[str, any]) -> None:
        """Write update status to file"""
        if not self.config.enabled:
            return

        try:
            # Enhance summary with additional metadata
            status_data = self._create_status_data(updates, summary)

            # Write to file
            self._write_status_file(status_data)

            logger.info(f"Updated status file: {self.status_file}")
        except Exception as e:
            logger.error(f"Failed to write status file: {e}")

    def _create_status_data(self, updates: list[Package], summary: dict[str, any]) -> dict:
        """Create complete status data structure"""
        status = {
            "last_check": datetime.now().isoformat(),
            "next_check": self._calculate_next_check(),
            "update_available": len(updates) > 0,
            "total_updates": len(updates),
            "summary": summary,
            "system_info": self._get_system_info(),
        }

        # Add detailed package list if updates exist
        if updates:
            status["updates"] = [
                {
                    "name": pkg.name,
                    "installed_version": pkg.installed_version,
                    "available_version": pkg.available_version,
                    "architecture": pkg.architecture,
                    "distribution": pkg.distribution,
                    "priority": pkg.priority,
                }
                for pkg in updates
            ]
        else:
            status["updates"] = []

        return status

    def _calculate_next_check(self) -> str:
        """Calculate when the next check will occur"""
        from datetime import timedelta

        from ..config import Config

        # Get interval from config (this is a bit hacky but works)
        config = Config()
        interval = config.checking.interval_seconds
        next_time = datetime.now() + timedelta(seconds=interval)
        return next_time.isoformat()

    def _get_system_info(self) -> dict[str, str]:
        """Get basic system information"""
        info = {}

        try:
            # Get distro info
            if Path("/etc/os-release").exists():
                with open("/etc/os-release") as f:
                    for line in f:
                        if line.startswith("PRETTY_NAME="):
                            info["os"] = line.split("=", 1)[1].strip().strip('"')
                            break

            # Get architecture
            import platform

            info["architecture"] = platform.machine()
            info["hostname"] = platform.node()

        except Exception as e:
            logger.debug(f"Could not get system info: {e}")

        return info

    def _write_status_file(self, data: dict) -> None:
        """Write status data to file"""
        # Create directory if it doesn't exist
        self.status_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Write with pretty print if configured
            with open(self.status_file, "w") as f:
                if self.config.pretty_print:
                    json.dump(data, f, indent=2, sort_keys=True, default=str)
                else:
                    json.dump(data, f, default=str)

            # Set reasonable permissions (readable by all, writable by owner)
            self.status_file.chmod(0o644)

        except Exception as e:
            logger.error(f"Failed to write status file: {e}")
            raise

    def read_status(self) -> dict | None:
        """Read current status from file"""
        if not self.status_file.exists():
            return None

        try:
            with open(self.status_file) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read status file: {e}")
            return None

    def clear(self) -> None:
        """Clear status file (write empty status)"""
        empty_status = {
            "last_check": datetime.now().isoformat(),
            "update_available": False,
            "total_updates": 0,
            "updates": [],
            "summary": {
                "total_updates": 0,
                "by_priority": {
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                },
                "by_distribution": {},
                "packages": [],
            },
        }

        try:
            self._write_status_file(empty_status)
            logger.info("Cleared status file")
        except Exception as e:
            logger.error(f"Failed to clear status file: {e}")
