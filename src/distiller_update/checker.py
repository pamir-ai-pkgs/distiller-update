"""Core update checking logic for Distiller Update Notifier"""

import logging
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

from packaging import version

from .config import Config

logger = logging.getLogger(__name__)


@dataclass
class Package:
    """Represents a package with version information"""

    name: str
    installed_version: str | None
    available_version: str | None
    architecture: str
    distribution: str
    priority: str = "medium"
    force_update: bool = False  # Set to True when APT reports an update regardless of version

    @property
    def has_update(self) -> bool:
        """Check if package has an update available"""
        # If APT explicitly marked this as upgradable, trust that
        if self.force_update:
            return True
            
        if not self.installed_version or not self.available_version:
            return False
        try:
            return version.parse(self.available_version) > version.parse(self.installed_version)
        except Exception:
            # Fallback to string comparison if version parsing fails
            return self.available_version != self.installed_version


class UpdateChecker:
    """Main update checking class"""

    def __init__(self, config: Config) -> None:
        """Initialize update checker"""
        self.config = config
        self.installed_packages: dict[str, str] = {}
        self.available_packages: dict[str, dict[str, str]] = {}

    def check_updates(self) -> list[Package]:
        """Check for available updates"""
        logger.info("Starting update check")

        # Get installed packages
        self._get_installed_packages()

        # Get available packages from repository
        self._get_available_packages()
        
        # Get packages that APT considers upgradable
        apt_upgradable = self._get_apt_upgradable()

        # Compare and find updates
        updates = self._compare_versions(apt_upgradable)

        # Apply filters
        updates = self._apply_filters(updates)

        logger.info(f"Found {len(updates)} available updates")
        return updates

    def _get_installed_packages(self) -> None:
        """Get list of installed packages"""
        try:
            cmd = ["dpkg-query", "-W", "-f=${Package}:${Architecture} ${Version}\\n"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            self.installed_packages.clear()
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    pkg_arch = parts[0]
                    version = parts[1]
                    # Extract package name without architecture
                    pkg_name = pkg_arch.split(":")[0]
                    self.installed_packages[pkg_name] = version

            logger.debug(f"Found {len(self.installed_packages)} installed packages")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get installed packages: {e}")
        except Exception as e:
            logger.error(f"Error getting installed packages: {e}")

    def _get_available_packages(self) -> None:
        """Get available packages from repository"""
        self.available_packages.clear()

        # Update package cache first (we're running as root in systemd)
        try:
            logger.debug("Updating package cache")
            subprocess.run(["/usr/bin/apt-get", "update", "-qq"], check=False, timeout=30)
        except Exception as e:
            logger.warning(f"Failed to update package cache: {e}")

        # Get packages from apt.pamir.ai repository only
        pamir_packages = self._get_pamir_packages()
        logger.debug(f"Found {len(pamir_packages)} packages from apt.pamir.ai")

        # Check versions only for Pamir packages
        for pkg_name in pamir_packages:
            self._check_package_version(pkg_name)

    def _get_pamir_packages(self) -> set[str]:
        """Get list of packages available from apt.pamir.ai repository"""
        pamir_packages = set()
        
        try:
            # Method 1: Check installed packages and filter by their source
            # Get all installed packages first
            cmd = ["dpkg-query", "-W", "-f=${Package}\n"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
            
            if result.returncode == 0 and result.stdout:
                installed = result.stdout.strip().split("\n")
                # Check a subset of packages for Pamir origin to avoid checking all
                # Start with known patterns
                patterns = ["distiller", "pamir", "cm5", "claude", "cuda", "jetson"]
                candidates = [pkg for pkg in installed if any(p in pkg.lower() for p in patterns)]
                
                logger.debug(f"Checking {len(candidates)} candidate packages for Pamir origin")
                for pkg in candidates:
                    if pkg and self._is_pamir_package(pkg):
                        pamir_packages.add(pkg)
                        
            # If we found too few packages, try checking apt lists directly
            if len(pamir_packages) < 5:
                # Method 2: Try to find packages from apt lists if they exist
                cmd = ["sh", "-c", "ls /var/lib/apt/lists/*Packages 2>/dev/null | xargs -r grep -l 'apt.pamir.ai' | head -1"]
                result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    # Found a Packages file with apt.pamir.ai
                    packages_file = result.stdout.strip()
                    cmd = ["sh", "-c", f"grep '^Package:' {packages_file} | cut -d' ' -f2"]
                    result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=2)
                    if result.returncode == 0:
                        for pkg in result.stdout.strip().split("\n"):
                            if pkg:
                                pamir_packages.add(pkg)
                
        except subprocess.TimeoutExpired:
            logger.error("Timeout while getting package list")
        except Exception as e:
            logger.error(f"Failed to get Pamir packages: {e}")
        
        return pamir_packages

    def _is_pamir_package(self, package: str) -> bool:
        """Check if a package is from apt.pamir.ai repository"""
        try:
            cmd = ["apt-cache", "policy", package]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=5)
            
            # Check if apt.pamir.ai appears in the policy output
            return "apt.pamir.ai" in result.stdout
            
        except Exception:
            return False

    def _check_package_version(self, package: str) -> None:
        """Check available version for a specific package"""
        try:
            cmd = ["apt-cache", "policy", package]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)

            if result.returncode == 0:
                # Parse the policy output to find version from apt.pamir.ai
                lines = result.stdout.split("\n")
                candidate_version = None
                
                for i, line in enumerate(lines):
                    if line.strip().startswith("Candidate:"):
                        candidate_version = line.split(":", 1)[1].strip()
                    elif "apt.pamir.ai" in line and candidate_version:
                        # This candidate is from our repository
                        if package not in self.available_packages:
                            self.available_packages[package] = {}
                        # Store with a generic dist key for now
                        self.available_packages[package]["pamir"] = candidate_version
                        break

        except Exception as e:
            logger.debug(f"Could not check version for {package}: {e}")
    
    def _get_apt_upgradable(self) -> set[str]:
        """Get list of packages that APT considers upgradable"""
        upgradable = set()
        
        try:
            # Run apt list --upgradable to get the authoritative list
            cmd = ["apt", "list", "--upgradable"]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=10)
            
            if result.returncode == 0 and result.stdout:
                # Parse output - skip the header line
                lines = result.stdout.strip().split("\n")
                for line in lines:
                    if not line or line.startswith("Listing"):
                        continue
                    
                    # Parse package name from lines like:
                    # distiller-update/unstable 0.1.0 all [upgradable from: 0.1.0]
                    if "/" in line:
                        pkg_name = line.split("/")[0]
                        upgradable.add(pkg_name)
                        logger.debug(f"APT reports {pkg_name} as upgradable")
            
            logger.debug(f"Found {len(upgradable)} packages marked as upgradable by APT")
                        
        except subprocess.TimeoutExpired:
            logger.warning("Timeout while checking apt upgradable packages")
        except Exception as e:
            logger.warning(f"Failed to get apt upgradable list: {e}")
        
        return upgradable

    def _compare_versions(self, apt_upgradable: set[str] = None) -> list[Package]:
        """Compare installed vs available versions"""
        updates = []
        apt_upgradable = apt_upgradable or set()

        for pkg_name in self.available_packages:
            if pkg_name in self.installed_packages:
                installed_ver = self.installed_packages[pkg_name]
                for dist, available_ver in self.available_packages[pkg_name].items():
                    # Check if APT considers this package upgradable
                    force_update = pkg_name in apt_upgradable
                    
                    pkg = Package(
                        name=pkg_name,
                        installed_version=installed_ver,
                        available_version=available_ver,
                        architecture=self._get_architecture(pkg_name),
                        distribution=dist,
                        priority=self._determine_priority(pkg_name),
                        force_update=force_update,
                    )

                    if pkg.has_update:
                        updates.append(pkg)
                        if force_update and installed_ver == available_ver:
                            logger.debug(f"Package {pkg_name} has same version {installed_ver} but APT reports as upgradable")

        return updates

    def _apply_filters(self, packages: list[Package]) -> list[Package]:
        """Apply configured filters to package list"""
        filtered = []

        for pkg in packages:
            # Check include filter
            if self.config.filters.include_packages:
                if pkg.name not in self.config.filters.include_packages:
                    continue

            # Check exclude filter
            if pkg.name in self.config.filters.exclude_packages:
                continue

            # Check priority filter
            if pkg.priority not in self.config.filters.priority_levels:
                continue

            filtered.append(pkg)

        return filtered

    def _get_architecture(self, package: str) -> str:
        """Get architecture of a package"""
        try:
            cmd = ["dpkg-query", "-W", "-f=${Architecture}", package]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip() or "all"
        except Exception:
            return "all"

    def _determine_priority(self, package: str) -> str:
        """Determine priority level of a package"""
        # Critical packages
        critical_patterns = [
            r"^linux-",
            r"^systemd",
            r"^openssh-",
            r"^openssl",
            r"^apt",
            r"^dpkg",
        ]

        # High priority packages
        high_patterns = [
            r"^distiller-",
            r"^pamir-",
            r"^python3",
            r"^lib.*security",
            r"^.*-security",
        ]

        # Check patterns
        for pattern in critical_patterns:
            if re.match(pattern, package):
                return "critical"

        for pattern in high_patterns:
            if re.match(pattern, package):
                return "high"

        # Default to medium
        return "medium"

    def get_update_summary(self, updates: list[Package]) -> dict[str, any]:
        """Get a summary of available updates"""
        summary = {
            "timestamp": datetime.now().isoformat(),
            "total_updates": len(updates),
            "by_priority": {
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            },
            "by_distribution": {},
            "packages": [],
        }

        for update in updates:
            # Count by priority
            summary["by_priority"][update.priority] += 1

            # Count by distribution
            if update.distribution not in summary["by_distribution"]:
                summary["by_distribution"][update.distribution] = 0
            summary["by_distribution"][update.distribution] += 1

            # Add package details
            summary["packages"].append(
                {
                    "name": update.name,
                    "installed": update.installed_version,
                    "available": update.available_version,
                    "distribution": update.distribution,
                    "priority": update.priority,
                }
            )

        return summary
