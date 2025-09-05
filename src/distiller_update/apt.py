"""Async APT interface for efficient update checking."""

import asyncio
import gzip
import hashlib
import re
from urllib.parse import urljoin

import aiohttp
import structlog

from .models import Config, Package

logger = structlog.get_logger()


class AptInterface:
    """Efficient async interface to APT."""

    def __init__(self, config: Config) -> None:
        """Initialize APT interface."""
        self.config = config
        self.repo_pattern = re.compile(
            rf"{re.escape(config.repository_url)}.*{re.escape(config.distribution)}"
        )

    async def run_command(self, cmd: list[str]) -> tuple[str, str, int]:
        """Run command asynchronously and return output."""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"DEBIAN_FRONTEND": "noninteractive", "PATH": "/usr/bin:/bin"},
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)
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
        """Update APT package cache for Pamir repository only."""
        logger.debug("Updating APT cache")

        # Update only the Pamir repository to save time
        stdout, stderr, code = await self.run_command(
            [
                "apt-get",
                "update",
                "-o",
                "Dir::Etc::sourcelist=/dev/null",
                "-o",
                'Dir::Etc::sourceparts="/dev/null"',
                "-o",
                'APT::Get::List-Cleanup="0"',
                "-o",
                'Acquire::http::Dl-Limit="0"',
                "-o",
                'APT::Sources::Use-Etag="false"',
                "--no-list-cleanup",
                f"-o=APT::Sources::List={self.config.repository_url} {self.config.distribution} main",
            ]
        )

        if code != 0:
            logger.warning("Failed to update cache", stderr=stderr)
            # Try full update as fallback
            stdout, stderr, code = await self.run_command(["apt-get", "update", "-qq"])

        return code == 0

    async def get_upgradable_packages(self) -> list[Package]:
        """Get list of upgradable packages from Pamir repository."""
        # Run apt list --upgradable to get all upgradable packages
        stdout, stderr, code = await self.run_command(["apt", "list", "--upgradable"])

        if code != 0:
            logger.error("Failed to list upgradable packages", stderr=stderr)
            return []

        packages: list[Package] = []
        seen_packages: set[str] = set()

        for line in stdout.splitlines():
            # Skip header and empty lines
            if not line or line.startswith("Listing") or "/" not in line:
                continue

            try:
                # Parse line format: package-name/distribution version arch [upgradable from: old-version]
                if "[upgradable from:" not in line:
                    continue

                # Extract package info
                pkg_part, rest = line.split("[upgradable from:", 1)
                old_version = rest.rstrip("]").strip()

                # Parse package part
                parts = pkg_part.split()
                if len(parts) < 2:
                    continue

                name_dist = parts[0]
                new_version = parts[1]

                # Extract package name and distribution
                if "/" in name_dist:
                    name, dist = name_dist.split("/", 1)
                else:
                    name = name_dist
                    dist = ""

                # Skip if not from Pamir repository (check distribution)
                if dist and self.config.distribution not in dist:
                    continue

                # Skip duplicates
                if name in seen_packages:
                    continue
                seen_packages.add(name)

                # Get package size (optional, for better UX)
                size = await self._get_package_size(name, new_version)

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

        # If no packages found via apt list, try apt-get -s upgrade as fallback
        if not packages:
            packages = await self._get_packages_via_simulate()

        logger.info(f"Found {len(packages)} upgradable packages from Pamir repository")
        return packages

    async def _get_package_size(self, name: str, version: str) -> int:
        """Get download size for a package (best effort)."""
        try:
            stdout, _, code = await self.run_command(["apt-cache", "show", f"{name}={version}"])
            if code == 0:
                for line in stdout.splitlines():
                    if line.startswith("Size:"):
                        return int(line.split(":", 1)[1].strip())
        except Exception:
            # Size not available
            pass
        return 0

    async def _get_packages_via_simulate(self) -> list[Package]:
        """Fallback method using apt-get -s upgrade."""
        stdout, stderr, code = await self.run_command(["apt-get", "-s", "upgrade", "--assume-yes"])

        if code != 0:
            return []

        packages: list[Package] = []
        in_upgrade_list = False

        for line in stdout.splitlines():
            if "The following packages will be upgraded:" in line:
                in_upgrade_list = True
                continue

            if in_upgrade_list:
                if line.strip() and not line.startswith(" "):
                    # End of upgrade list
                    break

                # Parse package names from the list
                for pkg_name in line.split():
                    pkg_name = pkg_name.strip()
                    if pkg_name:
                        # Get version info
                        info = await self._get_package_info(pkg_name)
                        if info and self._is_from_pamir(info):
                            packages.append(info)

        return packages

    async def _get_package_info(self, name: str) -> Package | None:
        """Get detailed package information."""
        try:
            # Get current version
            stdout, _, code = await self.run_command(["dpkg-query", "-W", "-f=${Version}", name])
            if code != 0:
                return None
            current_version = stdout.strip()

            # Get candidate version
            stdout, _, code = await self.run_command(["apt-cache", "policy", name])
            if code != 0:
                return None

            candidate_version = ""
            for line in stdout.splitlines():
                if "Candidate:" in line:
                    candidate_version = line.split(":", 1)[1].strip()
                    break

            if current_version and candidate_version and current_version != candidate_version:
                size = await self._get_package_size(name, candidate_version)
                return Package(
                    name=name,
                    current_version=current_version,
                    new_version=candidate_version,
                    size=size,
                )
        except Exception as e:
            logger.debug(f"Failed to get package info for {name}: {e}")

        return None

    def _is_from_pamir(self, package: Package) -> bool:
        """Check if package is from Pamir repository."""
        # For now, include all packages since we're checking after apt update
        # In production, you might want to check apt-cache policy output
        return True

    async def get_installed_checksum(self, package_name: str) -> str | None:
        """Get MD5 checksum of installed package file."""
        try:
            # Get the installed package file path
            stdout, _, code = await self.run_command(["dpkg-query", "-L", package_name])
            if code != 0:
                return None

            # Find the .deb file in dpkg cache
            stdout, _, code = await self.run_command(
                ["find", "/var/cache/apt/archives", "-name", f"{package_name}_*.deb", "-type", "f"]
            )

            if code == 0 and stdout.strip():
                deb_files = stdout.strip().split("\n")
                if deb_files:
                    # Calculate SHA256 of the most recent .deb file
                    newest_deb = deb_files[-1]
                    try:
                        with open(newest_deb, "rb") as f:
                            sha256_hash = hashlib.sha256()
                            for chunk in iter(lambda: f.read(4096), b""):
                                sha256_hash.update(chunk)
                            return sha256_hash.hexdigest()
                    except Exception:
                        pass

            # Fallback: Use dpkg database checksum
            stdout, _, code = await self.run_command(
                ["dpkg-query", "-W", "-f=${MD5sum}", package_name]
            )
            if code == 0 and stdout.strip():
                return stdout.strip()

        except Exception as e:
            logger.debug(f"Failed to get installed checksum for {package_name}: {e}")

        return None

    async def fetch_repository_checksums(self) -> dict[str, dict[str, str]]:
        """Fetch package checksums from repository Packages file."""
        checksums = {}

        try:
            # Construct Packages.gz URL
            packages_url = urljoin(
                self.config.repository_url.rstrip("/") + "/",
                f"dists/{self.config.distribution}/main/binary-arm64/Packages.gz",
            )

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    packages_url, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        logger.warning(f"Failed to fetch Packages.gz: HTTP {response.status}")
                        return checksums

                    # Download and decompress
                    content = await response.read()
                    decompressed = gzip.decompress(content).decode("utf-8")

                    # Parse Packages file
                    current_package = None
                    current_version = None
                    current_md5 = None

                    for line in decompressed.split("\n"):
                        line = line.strip()

                        if line.startswith("Package: "):
                            current_package = line.split(": ", 1)[1]
                        elif line.startswith("Version: "):
                            current_version = line.split(": ", 1)[1]
                        elif line.startswith("MD5sum: "):
                            current_md5 = line.split(": ", 1)[1]
                        elif line == "" and current_package:
                            # End of package stanza
                            if current_package and current_version and current_md5:
                                if current_package not in checksums:
                                    checksums[current_package] = {}
                                checksums[current_package][current_version] = current_md5
                            current_package = None
                            current_version = None
                            current_md5 = None

                    # Handle last package if file doesn't end with blank line
                    if current_package and current_version and current_md5:
                        if current_package not in checksums:
                            checksums[current_package] = {}
                        checksums[current_package][current_version] = current_md5

        except Exception as e:
            logger.error(f"Failed to fetch repository checksums: {e}")

        return checksums

    async def check_updates(self) -> list[Package]:
        """Main method to check for updates with checksum support."""
        # Update cache and get packages
        update_success = await self.update_cache()
        if not update_success:
            logger.warning("Cache update failed, checking with existing cache")

        # Get standard upgradable packages
        packages = await self.get_upgradable_packages()

        # Fetch repository checksums for rebuild detection
        repo_checksums = await self.fetch_repository_checksums()

        # Check for rebuilds (same version, different checksum)
        all_installed_packages = await self._get_all_installed_pamir_packages()

        for installed_pkg in all_installed_packages:
            # Skip if already in upgrade list
            if any(p.name == installed_pkg["name"] for p in packages):
                continue

            # Check if repository has same version but different checksum
            if installed_pkg["name"] in repo_checksums:
                repo_versions = repo_checksums[installed_pkg["name"]]
                installed_version = installed_pkg["version"]

                if installed_version in repo_versions:
                    repo_md5 = repo_versions[installed_version]
                    installed_md5 = await self.get_installed_checksum(installed_pkg["name"])

                    if installed_md5 and repo_md5 and installed_md5 != repo_md5:
                        # Found a rebuild - same version, different checksum
                        logger.info(
                            f"Found rebuild for {installed_pkg['name']}: "
                            f"version {installed_version}, "
                            f"checksum {installed_md5[:8]}... → {repo_md5[:8]}..."
                        )

                        size = await self._get_package_size(
                            installed_pkg["name"], installed_version
                        )
                        packages.append(
                            Package(
                                name=installed_pkg["name"],
                                current_version=installed_version,
                                new_version=installed_version,  # Same version
                                size=size,
                                installed_checksum=installed_md5,
                                repository_checksum=repo_md5,
                                update_type="rebuild",
                            )
                        )

        # Add checksums to regular updates
        for pkg in packages:
            if pkg.update_type == "version" and pkg.name in repo_checksums:
                if pkg.new_version in repo_checksums[pkg.name]:
                    pkg.repository_checksum = repo_checksums[pkg.name][pkg.new_version]
                    pkg.installed_checksum = await self.get_installed_checksum(pkg.name)

        return sorted(packages, key=lambda p: p.name)

    async def _get_all_installed_pamir_packages(self) -> list[dict[str, str]]:
        """Get all installed packages that might be from Pamir repository."""
        packages = []

        try:
            # Get list of installed packages with pamir/distiller in name
            stdout, _, code = await self.run_command(
                ["dpkg-query", "-W", "-f=${Package}\\t${Version}\\n"]
            )

            if code == 0:
                for line in stdout.strip().split("\n"):
                    if line and ("\t" in line):
                        name, version = line.split("\t", 1)
                        # Filter for likely Pamir packages
                        if any(x in name.lower() for x in ["distiller", "pamir", "vibe"]):
                            packages.append({"name": name, "version": version})

        except Exception as e:
            logger.debug(f"Failed to get installed packages: {e}")

        return packages
