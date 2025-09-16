import asyncio
import fcntl
import os
from datetime import datetime
from typing import Any

import structlog

from .models import Config, Package

logger = structlog.get_logger()


class AptInterface:
    def __init__(self, config: Config) -> None:
        self.config = config

    async def run_command(self, cmd: list[str], timeout: float = 30.0) -> tuple[str, str, int]:
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"DEBIAN_FRONTEND": "noninteractive", "PATH": "/usr/bin:/bin"},
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
                process.returncode or 0,
            )
        except TimeoutError:
            logger.warning("Command timed out", cmd=cmd)
            if process:
                process.kill()
                await process.wait()
            return "", "Command timed out", 1
        except Exception as e:
            logger.error("Command failed", cmd=cmd, error=str(e))
            return "", str(e), 1

    async def update_cache(self) -> bool:
        _stdout, stderr, code = await self.run_command(["apt-get", "update", "-qq"])

        if code != 0:
            logger.warning("Failed to update cache", stderr=stderr)
            return False

        return True

    async def check_updates(self, refresh: bool = True) -> list[Package]:
        if refresh:
            update_success = await self.update_cache()
            if not update_success:
                logger.warning("Cache update failed, checking with existing cache")

        stdout, stderr, code = await self.run_command(["apt", "list", "--upgradable"])

        if code != 0:
            logger.error("Failed to list upgradable packages", stderr=stderr)
            return []

        packages: list[Package] = []
        seen_packages: set[str] = set()

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

                if self.config.distribution not in dist.lower():
                    continue

                if name in seen_packages:
                    continue
                seen_packages.add(name)

                size = await self._get_package_size(name)

                packages.append(
                    Package(
                        name=name,
                        current_version=old_version,
                        new_version=new_version,
                        size=size,
                    )
                )

            except Exception as e:
                logger.debug("Failed to parse apt line", line=line, error=str(e))
                continue

        # Add curated installs (only if allowed)
        if self.config.policy_allow_new_packages:
            for name in self.config.bundle_default:
                cur = await self.installed_version(name)
                if cur is None:
                    cand = await self.candidate_version(name)
                    if cand:
                        size = await self._get_package_size(name)
                        packages.append(Package(
                            name=name,
                            current_version=None,
                            new_version=cand,
                            size=size,
                        ))

        # De-duplicate and sort
        dedup: dict[str, Package] = {}
        for p in packages:
            dedup[p.name] = p
        packages = sorted(dedup.values(), key=lambda p: (p.current_version is None, p.name))

        logger.info(f"Found {len(packages)} actions")
        return packages

    async def _get_package_size(self, name: str) -> int:
        try:
            stdout, _, code = await self.run_command(["apt-cache", "show", name], timeout=5.0)
            if code == 0:
                for line in stdout.splitlines():
                    if line.startswith("Size:"):
                        return int(line.split(":", 1)[1].strip())
        except Exception:
            pass
        return 0

    async def installed_version(self, name: str) -> str | None:
        stdout, _, code = await self.run_command(["dpkg-query", "-W", "-f=${Version}", name], timeout=5.0)
        if code == 0 and stdout.strip():
            return stdout.strip()
        return None

    async def candidate_version(self, name: str) -> str | None:
        stdout, _, code = await self.run_command(["apt-cache", "policy", name], timeout=5.0)
        if code != 0:
            return None
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("Candidate:"):
                cand = line.split(":", 1)[1].strip()
                return None if cand in ("(none)", "none") else cand
        return None

    async def apply(self, actions: list[Package], install_timeout: float = 1800.0) -> dict[str, Any]:
        lock_path = "/run/distiller-update.lock"
        os.makedirs("/run", exist_ok=True)

        try:
            with open(lock_path, "w") as lockf:
                try:
                    fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return {"ok": False, "rc": 1, "error": "Another update is running"}

                started_at = datetime.now()

                # Refresh cache before apply
                await self.update_cache()

                to_upgrade = [a for a in actions if a.current_version]
                to_install = [a for a in actions if a.current_version is None]

                up_args = [f"{p.name}={p.new_version}" for p in to_upgrade]
                in_args = [f"{p.name}={p.new_version}" for p in to_install]

                rc = 0
                if up_args:
                    _, _, code = await self.run_command(
                        ["apt-get", "install", "-y", "--only-upgrade", *up_args],
                        timeout=install_timeout,
                    )
                    rc = max(rc, code)

                if in_args:
                    _, _, code = await self.run_command(
                        ["apt-get", "install", "-y", *in_args],
                        timeout=install_timeout,
                    )
                    rc = max(rc, code)

                # Verify installations
                ok = True
                results = []
                for p in actions:
                    cur = await self.installed_version(p.name)
                    results.append({"name": p.name, "installed": cur, "expected": p.new_version})
                    if cur != p.new_version:
                        ok = False
                        rc = rc or 2

                finished_at = datetime.now()
                return {
                    "ok": ok,
                    "rc": rc,
                    "started_at": started_at.isoformat() + "Z",
                    "finished_at": finished_at.isoformat() + "Z",
                    "results": results
                }
        except Exception as e:
            logger.error("Apply failed", error=str(e))
            return {"ok": False, "rc": 3, "error": str(e)}
