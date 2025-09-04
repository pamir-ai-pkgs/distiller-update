"""Systemd journal notifier"""

import logging
import subprocess
from typing import ClassVar

from ..checker import Package
from ..config import Config

logger = logging.getLogger(__name__)


class JournalNotifier:
    """Send notifications to systemd journal"""

    # Map our priority levels to systemd priorities
    PRIORITY_MAP: ClassVar[dict[str, str]] = {
        "debug": "7",
        "info": "6",
        "notice": "5",
        "warning": "4",
        "err": "3",
        "crit": "2",
        "alert": "1",
        "emerg": "0",
    }

    def __init__(self, config: Config) -> None:
        """Initialize journal notifier"""
        self.config = config.notifications.journal
        self.identifier = self.config.identifier

    def notify(self, updates: list[Package], summary: dict[str, any]) -> None:
        """Send notification to systemd journal"""
        if not self.config.enabled:
            return

        try:
            # Determine priority based on updates
            priority = self._determine_priority(summary)

            # Create message
            message = self._create_message(updates, summary)

            # Send to journal
            self._send_to_journal(message, priority)

            logger.info("Sent notification to systemd journal")
        except Exception as e:
            logger.error(f"Failed to send to journal: {e}")

    def _determine_priority(self, summary: dict[str, any]) -> str:
        """Determine journal priority based on update summary"""
        if summary["by_priority"].get("critical", 0) > 0:
            return "err"  # Critical updates = error priority
        elif summary["by_priority"].get("high", 0) > 0:
            return "warning"  # High priority updates = warning
        elif summary["total_updates"] > 0:
            return "notice"  # Regular updates = notice
        else:
            return "info"  # No updates = info

    def _create_message(self, updates: list[Package], summary: dict[str, any]) -> str:
        """Create journal message"""
        if not updates:
            return "No updates available"

        parts = []

        # Summary
        total = summary["total_updates"]
        parts.append(f"{total} package update{'s' if total != 1 else ''} available")

        # Priority breakdown
        priority_counts = []
        for level in ["critical", "high", "medium", "low"]:
            count = summary["by_priority"].get(level, 0)
            if count > 0:
                priority_counts.append(f"{count} {level}")

        if priority_counts:
            parts.append(f"Priority: {', '.join(priority_counts)}")

        # Critical/High priority packages
        critical_high = [p for p in updates if p.priority in ["critical", "high"]]
        if critical_high:
            pkg_list = ", ".join([p.name for p in critical_high[:5]])
            if len(critical_high) > 5:
                pkg_list += f" (+{len(critical_high) - 5} more)"
            parts.append(f"Important: {pkg_list}")

        return " | ".join(parts)

    def _send_to_journal(self, message: str, priority: str) -> None:
        """Send message to systemd journal"""
        try:
            # Get systemd priority number
            self.PRIORITY_MAP.get(priority, "6")

            # Construct systemd-cat command
            cmd = [
                "systemd-cat",
                "-t",
                self.identifier,
                "-p",
                priority,
            ]

            # Send message
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, text=True)
            process.communicate(input=message)

            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, cmd)

        except FileNotFoundError:
            # systemd-cat not available, try logger
            self._fallback_to_logger(message, priority)
        except Exception as e:
            logger.error(f"Failed to write to journal: {e}")
            raise

    def _fallback_to_logger(self, message: str, priority: str) -> None:
        """Fallback to logger command if systemd-cat not available"""
        try:
            cmd = ["logger", "-t", self.identifier, "-p", f"user.{priority}", message]
            subprocess.run(cmd, check=True)
        except Exception as e:
            logger.error(f"Fallback to logger also failed: {e}")
            raise

    def log_check(self, checking: bool = True) -> None:
        """Log that we're checking for updates"""
        if not self.config.enabled:
            return

        message = "Checking for updates..." if checking else "Update check complete"
        try:
            self._send_to_journal(message, "info")
        except Exception as e:
            logger.debug(f"Failed to send journal log: {e}")
