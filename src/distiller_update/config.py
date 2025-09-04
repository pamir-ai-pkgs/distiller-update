"""Configuration management for Distiller Update Notifier"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import yaml

logger = logging.getLogger(__name__)


@dataclass
class RepositoryConfig:
    """Repository configuration"""

    url: str = "http://apt.pamir.ai"
    distributions: list[str] = field(default_factory=lambda: ["stable", "testing", "unstable"])


@dataclass
class CheckingConfig:
    """Update checking configuration"""

    interval_seconds: int = 3600
    on_startup: bool = True
    cache_file: str = "/var/cache/distiller-update/last_check.json"


@dataclass
class MOTDConfig:
    """MOTD notification configuration"""

    enabled: bool = True
    file: str = "/etc/update-motd.d/99-distiller-updates"
    show_count: bool = True
    show_packages: bool = True
    color: bool = True


@dataclass
class JournalConfig:
    """Systemd journal configuration"""

    enabled: bool = True
    identifier: str = "distiller-update"
    priority: str = "info"


@dataclass
class StatusFileConfig:
    """Status file configuration"""

    enabled: bool = True
    path: str = "/var/lib/distiller-update/status.json"
    pretty_print: bool = True


@dataclass
class LogFileConfig:
    """Log file configuration"""

    enabled: bool = True
    path: str = "/var/log/distiller-update.log"
    max_size_mb: int = 10
    backup_count: int = 3
    format: str = "%(asctime)s - %(levelname)s - %(message)s"


@dataclass
class NotificationsConfig:
    """Notifications configuration"""

    motd: MOTDConfig = field(default_factory=MOTDConfig)
    journal: JournalConfig = field(default_factory=JournalConfig)
    status_file: StatusFileConfig = field(default_factory=StatusFileConfig)
    log_file: LogFileConfig = field(default_factory=LogFileConfig)


@dataclass
class FiltersConfig:
    """Package filtering configuration"""

    include_packages: list[str] = field(default_factory=list)
    exclude_packages: list[str] = field(default_factory=list)
    check_architecture: bool = True
    priority_levels: list[str] = field(
        default_factory=lambda: ["critical", "high", "medium", "low"]
    )


class Config:
    """Main configuration class"""

    DEFAULT_CONFIG_PATHS: ClassVar[list[Path | str]] = [
        "/etc/distiller-update/config.yaml",
        Path.home() / ".config/distiller-update/config.yaml",
        Path(__file__).parent.parent.parent / "config/config.yaml",
    ]

    def __init__(self, config_path: str | None = None) -> None:
        """Initialize configuration"""
        self.repository = RepositoryConfig()
        self.checking = CheckingConfig()
        self.notifications = NotificationsConfig()
        self.filters = FiltersConfig()

        # Load configuration
        self._load_config(config_path)

    def _load_config(self, config_path: str | None = None) -> None:
        """Load configuration from file"""
        # Find config file
        if config_path:
            paths = [Path(config_path)]
        else:
            paths = self.DEFAULT_CONFIG_PATHS

        config_data = {}
        for path in paths:
            path = Path(path)
            if path.exists():
                logger.info(f"Loading configuration from {path}")
                try:
                    with open(path) as f:
                        config_data = yaml.safe_load(f) or {}
                    break
                except Exception as e:
                    logger.error(f"Failed to load config from {path}: {e}")

        # Apply configuration
        if config_data:
            self._apply_config(config_data)

    def _apply_config(self, data: dict[str, Any]) -> None:
        """Apply configuration data to dataclasses"""
        # Repository configuration
        if "repository" in data:
            repo = data["repository"]
            self.repository.url = repo.get("url", self.repository.url)
            self.repository.distributions = repo.get("distributions", self.repository.distributions)

        # Checking configuration
        if "checking" in data:
            check = data["checking"]
            self.checking.interval_seconds = check.get(
                "interval_seconds", self.checking.interval_seconds
            )
            self.checking.on_startup = check.get("on_startup", self.checking.on_startup)
            self.checking.cache_file = check.get("cache_file", self.checking.cache_file)

        # Notifications configuration
        if "notifications" in data:
            notif = data["notifications"]

            # MOTD
            if "motd" in notif:
                motd = notif["motd"]
                self.notifications.motd.enabled = motd.get(
                    "enabled", self.notifications.motd.enabled
                )
                self.notifications.motd.file = motd.get("file", self.notifications.motd.file)
                self.notifications.motd.show_count = motd.get(
                    "show_count", self.notifications.motd.show_count
                )
                self.notifications.motd.show_packages = motd.get(
                    "show_packages", self.notifications.motd.show_packages
                )
                self.notifications.motd.color = motd.get("color", self.notifications.motd.color)

            # Journal
            if "journal" in notif:
                journal = notif["journal"]
                self.notifications.journal.enabled = journal.get(
                    "enabled", self.notifications.journal.enabled
                )
                self.notifications.journal.identifier = journal.get(
                    "identifier", self.notifications.journal.identifier
                )
                self.notifications.journal.priority = journal.get(
                    "priority", self.notifications.journal.priority
                )

            # Status file
            if "status_file" in notif:
                status = notif["status_file"]
                self.notifications.status_file.enabled = status.get(
                    "enabled", self.notifications.status_file.enabled
                )
                self.notifications.status_file.path = status.get(
                    "path", self.notifications.status_file.path
                )
                self.notifications.status_file.pretty_print = status.get(
                    "pretty_print", self.notifications.status_file.pretty_print
                )

            # Log file
            if "log_file" in notif:
                log = notif["log_file"]
                self.notifications.log_file.enabled = log.get(
                    "enabled", self.notifications.log_file.enabled
                )
                self.notifications.log_file.path = log.get("path", self.notifications.log_file.path)
                self.notifications.log_file.max_size_mb = log.get(
                    "max_size_mb", self.notifications.log_file.max_size_mb
                )
                self.notifications.log_file.backup_count = log.get(
                    "backup_count", self.notifications.log_file.backup_count
                )
                self.notifications.log_file.format = log.get(
                    "format", self.notifications.log_file.format
                )

        # Filters configuration
        if "filters" in data:
            filt = data["filters"]
            self.filters.include_packages = filt.get(
                "include_packages", self.filters.include_packages
            )
            self.filters.exclude_packages = filt.get(
                "exclude_packages", self.filters.exclude_packages
            )
            self.filters.check_architecture = filt.get(
                "check_architecture", self.filters.check_architecture
            )
            self.filters.priority_levels = filt.get("priority_levels", self.filters.priority_levels)

    def save_cache(self, data: dict[str, Any]) -> None:
        """Save data to cache file"""
        cache_path = Path(self.checking.cache_file)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(cache_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save cache: {e}")

    def load_cache(self) -> dict[str, Any] | None:
        """Load data from cache file"""
        cache_path = Path(self.checking.cache_file)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load cache: {e}")
            return None
