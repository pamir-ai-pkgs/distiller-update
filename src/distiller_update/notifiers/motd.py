"""MOTD (Message of the Day) notifier for SSH login notifications"""

import logging
import os
from pathlib import Path

from ..checker import Package
from ..config import Config

logger = logging.getLogger(__name__)


class MOTDNotifier:
    """Updates /etc/update-motd.d/ with available updates"""

    def __init__(self, config: Config) -> None:
        """Initialize MOTD notifier"""
        self.config = config.notifications.motd
        self.motd_file = Path(self.config.file)

    def notify(self, updates: list[Package], summary: dict[str, any]) -> None:
        """Write update notification to MOTD"""
        if not self.config.enabled:
            return

        try:
            content = self._generate_motd_content(updates, summary)
            self._write_motd_file(content)
        except Exception as e:
            logger.error(f"Failed to update MOTD: {e}")

    def _generate_motd_content(self, updates: list[Package], summary: dict[str, any]) -> str:
        """Generate MOTD content"""
        lines = ["#!/bin/sh", ""]

        if not updates:
            # No updates available - remove the file
            return ""

        # Color codes if enabled
        if self.config.color:
            red = "\\033[0;31m"
            yellow = "\\033[1;33m"
            green = "\\033[0;32m"
            blue = "\\033[0;34m"
            reset = "\\033[0m"
        else:
            red = yellow = green = blue = reset = ""

        # Header
        lines.append(f'echo "{yellow}===================================={reset}"')

        # Determine color based on priority
        has_critical = summary["by_priority"].get("critical", 0) > 0
        has_high = summary["by_priority"].get("high", 0) > 0

        if has_critical:
            color = red
            prefix = "*** CRITICAL UPDATES AVAILABLE ***"
        elif has_high:
            color = yellow
            prefix = "*** Updates Available ***"
        else:
            color = green
            prefix = "Updates Available"

        lines.append(f'echo "{color}{prefix}{reset}"')
        lines.append(f'echo "{yellow}===================================={reset}"')
        lines.append('echo ""')

        # Update count
        if self.config.show_count:
            total = summary["total_updates"]
            lines.append(f'echo "{blue}Total updates: {total}{reset}"')

            # Show by priority if we have critical/high
            if has_critical or has_high:
                priority_str = []
                for level in ["critical", "high", "medium", "low"]:
                    count = summary["by_priority"].get(level, 0)
                    if count > 0:
                        if level == "critical":
                            priority_str.append(f"{red}{count} critical{reset}")
                        elif level == "high":
                            priority_str.append(f"{yellow}{count} high{reset}")
                        else:
                            priority_str.append(f"{count} {level}")

                if priority_str:
                    lines.append(f'echo "Priority: {", ".join(priority_str)}"')

            lines.append('echo ""')

        # Package list
        if self.config.show_packages:
            priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_updates = sorted(updates, key=lambda p: priority_order.get(p.priority, 99))

            # Show first 10 packages
            shown = 0
            for pkg in sorted_updates[:10]:
                if pkg.priority == "critical":
                    pkg_color = red
                elif pkg.priority == "high":
                    pkg_color = yellow
                else:
                    pkg_color = ""

                lines.append(
                    f'echo "  {pkg_color}{pkg.name:<30} '
                    f'{pkg.installed_version} -> {pkg.available_version}{reset}"'
                )
                shown += 1

            if len(updates) > shown:
                remaining = len(updates) - shown
                lines.append(f'echo "  ... and {remaining} more"')

            lines.append('echo ""')

        # Instructions
        lines.append(
            f'echo "{green}Run \\"sudo apt update && sudo apt upgrade\\" to install{reset}"'
        )
        lines.append(f'echo "{yellow}===================================={reset}"')
        lines.append('echo ""')

        return "\n".join(lines)

    def _write_motd_file(self, content: str) -> None:
        """Write content to MOTD file"""
        if not content:
            # Remove file if no updates
            if self.motd_file.exists():
                try:
                    os.remove(self.motd_file)
                    logger.info(f"Removed MOTD file (no updates): {self.motd_file}")
                except Exception as e:
                    logger.error(f"Failed to remove MOTD file: {e}")
            else:
                logger.debug("No MOTD file to remove (no updates available)")
            return

        # Create directory if it doesn't exist
        self.motd_file.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        try:
            with open(self.motd_file, "w") as f:
                f.write(content)

            # Make executable (required for MOTD scripts)
            os.chmod(self.motd_file, 0o755)  # noqa: S103
            logger.info(f"Updated MOTD file: {self.motd_file}")
        except Exception as e:
            logger.error(f"Failed to write MOTD file: {e}")
            raise

    def clear(self) -> None:
        """Clear MOTD notification"""
        if self.motd_file.exists():
            try:
                os.remove(self.motd_file)
                logger.info("Cleared MOTD notification")
            except Exception as e:
                logger.error(f"Failed to clear MOTD: {e}")
