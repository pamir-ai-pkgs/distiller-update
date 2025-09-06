import asyncio

import structlog

from .models import Config, Package

logger = structlog.get_logger()


class AptInterface:
    def __init__(self, config: Config) -> None:
        self.config = config

    async def run_command(self, cmd: list[str], timeout: float = 30.0) -> tuple[str, str, int]:
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
        stdout, stderr, code = await self.run_command(["apt-get", "update", "-qq"])

        if code != 0:
            logger.warning("Failed to update cache", stderr=stderr)
            return False

        return True

    async def check_updates(self) -> list[Package]:
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

        logger.info(f"Found {len(packages)} upgradable packages")
        return sorted(packages, key=lambda p: p.name)

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
