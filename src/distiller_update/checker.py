import fcntl
import json
import os
import re
import subprocess
from datetime import datetime
from typing import Any, Protocol

import structlog

from .led_controller import LEDController
from .models import Config, Package, UpdateResult
from .utils.logging import setup_logging

logger = structlog.get_logger()

# Pattern for valid Debian package names
VALID_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+\-.]+$")


class Notifier(Protocol):
    """Protocol for notification objects."""

    def notify(self, result: UpdateResult) -> None:
        """Send notification about update result."""
        ...


def _validate_package_name(package_name: str) -> str:
    """Validate package name against Debian naming rules."""
    package_name = package_name.strip()
    if not package_name or len(package_name) > 255 or not VALID_PACKAGE_NAME.match(package_name):
        raise ValueError(f"Invalid package name: {package_name}")
    return package_name


class UpdateChecker:
    """Handles APT operations and update notifications."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.notifiers: list[Notifier] = []
        config.ensure_directories()
        setup_logging(config.log_level)

    def add_notifier(self, notifier: Notifier) -> None:
        """Add a notifier to receive update notifications."""
        self.notifiers.append(notifier)

    def check(self) -> UpdateResult:
        """Check for updates and notify all registered notifiers."""
        try:
            packages = self.check_updates()
            result = UpdateResult(
                packages=packages,
                checked_at=datetime.now(),
                distribution=self.config.distribution,
            )

            self._save_result(result)
            self._notify_all(result)

            return result

        except Exception as e:
            logger.error("Update check failed", error=str(e), exc_info=True)
            raise

    def check_updates(self, refresh: bool = True) -> list[Package]:
        """Check for available updates using APT."""
        if refresh:
            update_success = self._update_cache()
            if not update_success:
                logger.warning("Cache update failed, checking with existing cache")

        stdout, stderr, code = self._run_command(
            ["apt", "list", "--upgradable"], timeout=self.config.apt_list_timeout
        )

        if code != 0:
            logger.error("Failed to list upgradable packages", stderr=stderr)
            return []

        packages_dict: dict[str, Package] = {}

        for line in stdout.splitlines():
            if not line or line.startswith("Listing") or "/" not in line:
                continue

            try:
                if "[upgradable from:" not in line:
                    continue

                pkg_part, rest = line.split("[upgradable from:", 1)
                old_version = rest.rstrip("]").strip()

                parts = pkg_part.split()
                if len(parts) < 2:
                    continue

                name_dist = parts[0]
                new_version = parts[1]

                if "/" in name_dist:
                    name, dist = name_dist.split("/", 1)
                else:
                    name = name_dist
                    dist = ""

                try:
                    name = _validate_package_name(name)
                except Exception as e:
                    logger.warning(f"Invalid package name '{name}': {e}")
                    continue

                if self.config.distribution not in dist.lower():
                    continue

                if name in packages_dict:
                    continue

                packages_dict[name] = Package(
                    name=name,
                    current_version=old_version,
                    new_version=new_version,
                    size=0,
                )

            except Exception as e:
                logger.debug("Failed to parse apt line", line=line, error=str(e))
                continue

        # Add curated installs (only if allowed)
        if self.config.policy_allow_new_packages:
            for name in self.config.bundle_default:
                if name in packages_dict:
                    continue

                cur = self.installed_version(name)
                if cur is None:
                    cand = self.candidate_version(name)
                    if cand:
                        packages_dict[name] = Package(
                            name=name,
                            current_version=None,
                            new_version=cand,
                            size=0,
                        )

        packages = sorted(packages_dict.values(), key=lambda p: (p.current_version is None, p.name))

        # Batch fetch sizes for all packages
        if packages:
            package_sizes = self._get_package_sizes([p.name for p in packages])
            for pkg in packages:
                pkg.size = package_sizes.get(pkg.name, 0)

        logger.info(f"Found {len(packages)} actions")
        return packages

    def apply(self, actions: list[Package]) -> dict[str, Any]:
        """Apply package updates/installations."""
        lock_path = "/run/distiller-update.lock"
        os.makedirs("/run", exist_ok=True)

        led_controller = LEDController()
        led_status = "disabled" if not led_controller.enabled else "idle"

        try:
            with open(lock_path, "w") as lockf:
                try:
                    fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return {
                        "ok": False,
                        "rc": 1,
                        "error": "Another update is running",
                        "led_status": led_status,
                    }

                started_at = datetime.now()

                led_controller.set_updating()
                led_status = "updating"

                self._update_cache()

                to_upgrade = [a for a in actions if a.current_version]
                to_install = [a for a in actions if a.current_version is None]

                up_args = [f"{p.name}={p.new_version}" for p in to_upgrade]
                in_args = [f"{p.name}={p.new_version}" for p in to_install]

                rc = 0
                if up_args:
                    _, _, code = self._run_command(
                        ["apt-get", "install", "-y", "--only-upgrade", *up_args],
                        timeout=self.config.apt_install_timeout,
                    )
                    rc = max(rc, code)

                if in_args:
                    _, _, code = self._run_command(
                        ["apt-get", "install", "-y", *in_args],
                        timeout=self.config.apt_install_timeout,
                    )
                    rc = max(rc, code)

                ok = True
                results = []
                for p in actions:
                    cur = self.installed_version(p.name)
                    results.append({"name": p.name, "installed": cur, "expected": p.new_version})
                    if cur != p.new_version:
                        ok = False
                        rc = rc or 2

                if ok:
                    led_controller.set_success()
                    led_status = "success"
                else:
                    led_controller.turn_off()
                    led_status = "error"

                finished_at = datetime.now()
                return {
                    "ok": ok,
                    "rc": rc,
                    "started_at": started_at.isoformat() + "Z",
                    "finished_at": finished_at.isoformat() + "Z",
                    "results": results,
                    "led_status": led_status,
                }
        except Exception as e:
            logger.error("Apply failed", error=str(e))
            led_controller.turn_off()
            led_status = "error"
            return {"ok": False, "rc": 3, "error": str(e), "led_status": led_status}

    def installed_version(self, name: str) -> str | None:
        """Get the currently installed version of a package."""
        stdout, _, code = self._run_command(
            ["dpkg-query", "-W", "-f=${Version}", name], timeout=self.config.apt_query_timeout
        )
        if code == 0 and stdout.strip():
            return stdout.strip()
        return None

    def candidate_version(self, name: str) -> str | None:
        """Get the candidate version from APT cache."""
        stdout, _, code = self._run_command(
            ["apt-cache", "policy", name], timeout=self.config.apt_query_timeout
        )
        if code != 0:
            return None
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("Candidate:"):
                cand = line.split(":", 1)[1].strip()
                return None if cand in ("(none)", "none") else cand
        return None

    def get_status(self) -> UpdateResult | None:
        """Get the last cached update check result."""
        return self._load_cached_result()

    def _run_command(self, cmd: list[str], timeout: float = 30.0) -> tuple[str, str, int]:
        """Run a system command and return stdout, stderr, and return code."""
        try:
            # Direct command execution without security validation - APT handles security internally
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={"DEBIAN_FRONTEND": "noninteractive", "PATH": "/usr/bin:/bin"},
            )
            return (
                result.stdout,
                result.stderr,
                result.returncode,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Command timed out", cmd=cmd)
            return "", "Command timed out", 1
        except Exception as e:
            logger.error("Command failed", cmd=cmd, error=str(e))
            return "", str(e), 1

    def _update_cache(self) -> bool:
        """Update the APT cache."""
        # Build apt-get update command
        cmd = ["apt-get", "update"]

        # If apt_source_file is configured, only update that specific repository
        if self.config.apt_source_file:
            cmd.extend(
                [
                    "-o",
                    f"Dir::Etc::sourcelist={self.config.apt_source_file}",
                    "-o",
                    "Dir::Etc::sourceparts=-",
                ]
            )
            logger.debug(f"Updating only {self.config.apt_source_file}")
        else:
            logger.debug("Updating all APT sources")

        _stdout, stderr, code = self._run_command(cmd, timeout=self.config.apt_update_timeout)

        if code != 0:
            logger.warning("Failed to update cache", stderr=stderr)
            return False

        return True

    def _get_package_sizes(self, package_names: list[str]) -> dict[str, int]:
        """Get download sizes for multiple packages in a single query."""
        if not package_names:
            return {}

        sizes: dict[str, int] = {}

        try:
            stdout, _, code = self._run_command(
                ["apt-cache", "show", *package_names], timeout=self.config.apt_query_timeout * 2
            )

            if code != 0:
                logger.warning("Batch package size query failed, sizes will be unavailable")
                return dict.fromkeys(package_names, 0)

            current_package = None
            for line in stdout.splitlines():
                line = line.strip()

                if line.startswith("Package:"):
                    current_package = line.split(":", 1)[1].strip()

                elif line.startswith("Size:") and current_package:
                    size_str = line.split(":", 1)[1].strip()
                    try:
                        sizes[current_package] = int(size_str)
                    except (ValueError, TypeError):
                        logger.debug(f"Invalid size value for {current_package}: {size_str}")
                        sizes[current_package] = 0

        except Exception as e:
            logger.warning("Failed to fetch package sizes in batch", error=str(e))
            return dict.fromkeys(package_names, 0)

        # Ensure all packages have a size entry
        for name in package_names:
            if name not in sizes:
                sizes[name] = 0

        return sizes

    def _save_result(self, result: UpdateResult) -> None:
        """Save the check result to cache."""
        cache_file = self.config.cache_dir / "last_check.json"
        try:
            data = result.model_dump(mode="json")
            json_str = json.dumps(data, indent=2, default=str)

            with open(cache_file, "w") as f:
                f.write(json_str)
        except Exception as e:
            logger.error(
                "Failed to save cache - data may be lost", error=str(e), cache_file=str(cache_file)
            )
            # Don't raise here as this is not critical for the check operation

    def _load_cached_result(self) -> UpdateResult | None:
        """Load the last cached check result."""
        cache_file = self.config.cache_dir / "last_check.json"
        if not cache_file.exists():
            return None

        try:
            with open(cache_file) as f:
                content = f.read()
                return UpdateResult.model_validate_json(content)
        except Exception as e:
            logger.debug("Failed to load cache", error=str(e))
            return None

    def _notify_all(self, result: UpdateResult) -> None:
        """Send notifications to all registered notifiers."""
        if not self.notifiers:
            return

        for notifier in self.notifiers:
            self._safe_notify(notifier, result)

    def _safe_notify(self, notifier: Notifier, result: UpdateResult) -> None:
        """Safely call a notifier, catching and logging any exceptions."""
        try:
            notifier.notify(result)
        except Exception as e:
            logger.warning(
                "Notifier failed",
                notifier=notifier.__class__.__name__,
                error=str(e),
            )
