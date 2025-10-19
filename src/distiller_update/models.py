from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .utils.formatting import format_size


class Package(BaseModel):
    name: str
    current_version: str | None
    new_version: str
    size: int = 0

    @property
    def display_size(self) -> str:
        return format_size(self.size)

    @property
    def is_reinstall(self) -> bool:
        """Check if this is a reinstall (same version in repo as installed)."""
        return self.current_version is not None and self.current_version == self.new_version

    @property
    def action_type(self) -> str:
        """Get the action type: Install, Upgrade, or Reinstall."""
        if self.current_version is None:
            return "Install"
        elif self.is_reinstall:
            return "Reinstall"
        else:
            return "Upgrade"


class UpdateResult(BaseModel):
    packages: list[Package] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.now)
    distribution: str = "stable"

    @property
    def has_updates(self) -> bool:
        return len(self.packages) > 0

    @property
    def total_size(self) -> int:
        return sum(pkg.size for pkg in self.packages)

    @property
    def summary(self) -> str:
        if not self.has_updates:
            return "System is up to date"
        count = len(self.packages)
        return f"{count} package{'s' if count != 1 else ''} can be upgraded"


class NewsResult(BaseModel):
    content: str
    fetched_at: datetime = Field(default_factory=datetime.now)
    cache_ttl: int = Field(default=86400)

    @property
    def is_expired(self) -> bool:
        """Check if news cache has expired based on TTL."""
        age = (datetime.now() - self.fetched_at).total_seconds()
        return age > self.cache_ttl

    @property
    def has_content(self) -> bool:
        """Check if news has non-empty content."""
        return bool(self.content.strip())


class Config(BaseModel):
    check_interval: int = Field(default=14400, ge=1)
    repository_url: str = Field(default="http://apt.pamir.ai")
    distribution: Literal["stable", "testing", "unstable"] = "stable"
    notify_motd: bool = Field(default=True)
    notify_dbus: bool = Field(default=True)
    motd_file: Path = Field(default=Path("/etc/update-motd.d/99-distiller-updates"))
    cache_dir: Path = Field(default=Path("/var/cache/distiller-update"))
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    policy_restrict_prefixes: list[str] = Field(
        default_factory=lambda: ["pamir-ai-", "distiller-", "claude-code-"]
    )
    policy_allow_new_packages: bool = Field(default=True)
    bundle_default: list[str] = Field(default_factory=list)
    apt_lists_path: Path = Field(default=Path("/var/lib/apt/lists"))
    apt_source_file: str | None = Field(
        default=None,
        description="Optional: APT source file to update (e.g., 'sources.list.d/pamir-ai.list'). "
        "If set, only this source will be updated for faster checks. If None, all sources are updated.",
    )

    # News fetching configuration
    news_enabled: bool = Field(default=True, description="Enable news fetching and display")
    news_url: str = Field(default="https://apt.pamir.ai/NEWS", description="URL to fetch news from")
    news_fetch_timeout: int = Field(
        default=5, ge=1, le=30, description="Timeout for news HTTP requests"
    )
    news_cache_ttl: int = Field(
        default=86400, ge=3600, description="News cache TTL in seconds (default: 24h)"
    )

    # APT command timeout settings (in seconds)
    apt_update_timeout: int = Field(default=120, ge=30, description="Timeout for apt-get update")
    apt_list_timeout: int = Field(
        default=60, ge=10, description="Timeout for apt list --upgradable"
    )
    apt_query_timeout: int = Field(default=10, ge=5, description="Timeout for quick apt queries")
    apt_install_timeout: int = Field(
        default=1800, ge=300, description="Timeout for package installation"
    )

    def ensure_directories(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.notify_motd:
            self.motd_file.parent.mkdir(parents=True, exist_ok=True)
