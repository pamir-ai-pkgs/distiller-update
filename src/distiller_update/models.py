"""Data models for distiller-update using Pydantic."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Package(BaseModel):
    """Represents an upgradable package."""

    name: str
    current_version: str
    new_version: str
    size: int = 0  # Download size in bytes
    installed_checksum: str | None = None  # MD5 checksum of installed package
    repository_checksum: str | None = None  # MD5 checksum from repository
    update_type: Literal["version", "rebuild"] = "version"  # Type of update available

    @property
    def display_size(self) -> str:
        """Human-readable download size."""
        if self.size < 1024:
            return f"{self.size}B"
        elif self.size < 1024 * 1024:
            return f"{self.size / 1024:.1f}KB"
        elif self.size < 1024 * 1024 * 1024:
            return f"{self.size / (1024 * 1024):.1f}MB"
        else:
            return f"{self.size / (1024 * 1024 * 1024):.1f}GB"

    @property
    def needs_update(self) -> bool:
        """Check if package needs update (version or checksum mismatch)."""
        if self.current_version != self.new_version:
            return True
        # Check for rebuild (same version, different checksum)
        if self.installed_checksum and self.repository_checksum:
            return self.installed_checksum != self.repository_checksum
        return False

    @property
    def update_reason(self) -> str:
        """Human-readable reason for update."""
        if self.update_type == "rebuild":
            return "Rebuild available (checksum changed)"
        else:
            return f"Version update: {self.current_version} → {self.new_version}"


class UpdateResult(BaseModel):
    """Result of an update check."""

    packages: list[Package] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)
    distribution: str = "stable"

    @property
    def has_updates(self) -> bool:
        """Check if any updates are available."""
        return len(self.packages) > 0

    @property
    def total_size(self) -> int:
        """Total download size for all packages."""
        return sum(pkg.size for pkg in self.packages)

    @property
    def summary(self) -> str:
        """Human-readable summary."""
        if not self.has_updates:
            return "System is up to date"
        count = len(self.packages)
        return f"{count} package{'s' if count != 1 else ''} can be upgraded"


class Config(BaseModel):
    """Configuration for distiller-update."""

    # Check interval in seconds
    check_interval: int = Field(default=14400, ge=1)  # 4 hours default

    # APT repository settings
    repository_url: str = Field(default="http://apt.pamir.ai")
    distribution: Literal["stable", "testing", "unstable"] = "stable"

    # Notification settings
    notify_motd: bool = Field(default=True)
    notify_dbus: bool = Field(default=True)

    # File paths
    motd_file: Path = Field(default=Path("/etc/update-motd.d/99-distiller-updates"))
    cache_dir: Path = Field(default=Path("/var/cache/distiller-update"))

    # Logging
    log_level: Literal["debug", "info", "warning", "error"] = "info"

    class Config:
        """Pydantic config."""

        env_prefix = "DISTILLER_"
        env_file = ".env"
        env_file_encoding = "utf-8"
        use_enum_values = True

    def ensure_directories(self) -> None:
        """Ensure required directories exist."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.notify_motd:
            self.motd_file.parent.mkdir(parents=True, exist_ok=True)
