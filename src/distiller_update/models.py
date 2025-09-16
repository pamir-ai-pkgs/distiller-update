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
    installed_checksum: str | None = None
    repository_checksum: str | None = None
    update_type: Literal["version", "rebuild"] = "version"

    @property
    def display_size(self) -> str:
        return format_size(self.size)

    @property
    def needs_update(self) -> bool:
        if self.current_version is None or self.current_version != self.new_version:
            return True
        if self.installed_checksum and self.repository_checksum:
            return self.installed_checksum != self.repository_checksum
        return False

    @property
    def update_reason(self) -> str:
        if self.current_version is None:
            return f"New package: {self.new_version}"
        elif self.update_type == "rebuild":
            return "Rebuild available (checksum changed)"
        else:
            return f"Version update: {self.current_version} → {self.new_version}"


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


class Config(BaseModel):
    check_interval: int = Field(default=14400, ge=1)
    repository_url: str = Field(default="http://apt.pamir.ai")
    distribution: Literal["stable", "testing", "unstable"] = "stable"
    notify_motd: bool = Field(default=True)
    notify_dbus: bool = Field(default=True)
    motd_file: Path = Field(default=Path("/etc/update-motd.d/99-distiller-updates"))
    cache_dir: Path = Field(default=Path("/var/cache/distiller-update"))
    log_level: Literal["debug", "info", "warning", "error"] = "info"
    policy_restrict_prefixes: list[str] = Field(default_factory=lambda: ["pamir-ai-", "distiller-", "claude-code-"])
    policy_allow_new_packages: bool = Field(default=True)
    bundle_default: list[str] = Field(default_factory=list)

    def ensure_directories(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.notify_motd:
            self.motd_file.parent.mkdir(parents=True, exist_ok=True)
