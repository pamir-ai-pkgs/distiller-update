"""File-based log notifier"""

import logging
import logging.handlers
from pathlib import Path

from ..checker import Package
from ..config import Config

logger = logging.getLogger(__name__)


class LogNotifier:
    """Write notifications to log file with rotation"""

    def __init__(self, config: Config) -> None:
        """Initialize log notifier"""
        self.config = config.notifications.log_file
        self.log_file = Path(self.config.path)
        self.logger = None

        if self.config.enabled:
            self._setup_logger()

    def _setup_logger(self) -> None:
        """Setup dedicated logger for update notifications"""
        # Create directory if it doesn't exist
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        # Create dedicated logger
        self.logger = logging.getLogger("distiller-update-notifier")
        self.logger.setLevel(logging.INFO)

        # Remove existing handlers
        self.logger.handlers.clear()

        # Create rotating file handler
        max_bytes = self.config.max_size_mb * 1024 * 1024
        handler = logging.handlers.RotatingFileHandler(
            self.log_file,
            maxBytes=max_bytes,
            backupCount=self.config.backup_count,
        )

        # Set formatter
        formatter = logging.Formatter(self.config.format)
        handler.setFormatter(formatter)

        # Add handler
        self.logger.addHandler(handler)

    def notify(self, updates: list[Package], summary: dict[str, any]) -> None:
        """Log update notification"""
        if not self.config.enabled or not self.logger:
            return

        try:
            if not updates:
                self.logger.info("No updates available")
                return

            # Log summary
            total = summary["total_updates"]
            self.logger.info(f"Found {total} available update{'s' if total != 1 else ''}")

            # Log priority breakdown
            priority_info = []
            for level in ["critical", "high", "medium", "low"]:
                count = summary["by_priority"].get(level, 0)
                if count > 0:
                    priority_info.append(f"{count} {level}")

            if priority_info:
                self.logger.info(f"Priority breakdown: {', '.join(priority_info)}")

            # Log distribution breakdown
            if summary.get("by_distribution"):
                dist_info = []
                for dist, count in summary["by_distribution"].items():
                    dist_info.append(f"{dist}={count}")
                self.logger.info(f"By distribution: {', '.join(dist_info)}")

            # Log critical and high priority packages
            critical_high = [p for p in updates if p.priority in ["critical", "high"]]
            if critical_high:
                self.logger.warning(
                    f"Important updates: {', '.join([p.name for p in critical_high])}"
                )

            # Log all package details at debug level
            for pkg in updates:
                self.logger.debug(
                    f"Update available: {pkg.name} "
                    f"{pkg.installed_version} -> {pkg.available_version} "
                    f"[{pkg.distribution}] [{pkg.priority}]"
                )

        except Exception as e:
            logger.error(f"Failed to write to log file: {e}")

    def log_check_start(self) -> None:
        """Log that update check is starting"""
        if self.config.enabled and self.logger:
            self.logger.info("Starting update check")

    def log_check_complete(self, duration: float = 0) -> None:
        """Log that update check completed"""
        if self.config.enabled and self.logger:
            if duration > 0:
                self.logger.info(f"Update check completed in {duration:.2f} seconds")
            else:
                self.logger.info("Update check completed")

    def log_error(self, error: str) -> None:
        """Log an error"""
        if self.config.enabled and self.logger:
            self.logger.error(error)
