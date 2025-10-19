"""Tests for the UpdateChecker module."""

import subprocess
from unittest.mock import Mock, patch

import pytest

from distiller_update.checker import UpdateChecker, _validate_package_name
from distiller_update.models import Config, Package, UpdateResult


class TestPackageValidation:
    """Test package name validation."""

    def test_valid_package_names(self):
        """Test valid package names."""
        valid_names = [
            "apt",
            "python3",
            "libssl1.1",
            "gcc-9",
            "nodejs",
            "docker.io",
        ]

        for name in valid_names:
            assert _validate_package_name(name) == name

    def test_invalid_package_names(self):
        """Test invalid package names are rejected."""
        invalid_names = [
            "",  # Empty
            "Package",  # Uppercase
            "my package",  # Space
            "my_package",  # Underscore
        ]

        for name in invalid_names:
            with pytest.raises(ValueError):
                _validate_package_name(name)


class TestUpdateChecker:
    """Test the UpdateChecker class."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create a test config."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        motd_file = tmp_path / "motd" / "99-distiller-updates"
        apt_cache_dir = tmp_path / "apt-cache"
        return Config(
            cache_dir=cache_dir,
            motd_file=motd_file,
            apt_cache_dir=apt_cache_dir,
            check_interval=3600,
            distribution="stable",
        )

    @pytest.fixture
    def checker(self, config):
        """Create an UpdateChecker instance."""
        return UpdateChecker(config)

    def test_initialization(self, checker, config):
        """Test checker initialization."""
        assert checker.config == config
        assert checker.notifiers == []
        assert config.cache_dir.exists()

    def test_add_notifier(self, checker):
        """Test adding notifiers."""
        mock_notifier = Mock()
        checker.add_notifier(mock_notifier)
        assert len(checker.notifiers) == 1
        assert checker.notifiers[0] == mock_notifier

    @patch("distiller_update.checker.subprocess.run")
    def test_check_updates_no_updates(self, mock_run, checker):
        """Test check_updates when no updates available."""
        mock_run.return_value = Mock(stdout="Listing...\n", stderr="", returncode=0)

        packages = checker.check_updates()
        assert packages == []

    @patch("distiller_update.checker.subprocess.run")
    def test_check_updates_with_packages(self, mock_run, checker):
        """Test check_updates with available updates."""
        mock_run.side_effect = [
            Mock(stdout="", stderr="", returncode=0),
            Mock(
                stdout="Listing...\n"
                "package1/stable 2.0 amd64 [upgradable from: 1.0]\n"
                "package2/stable 3.0 amd64 [upgradable from: 2.0]\n",
                stderr="",
                returncode=0,
            ),
            Mock(stdout="Size: 1024\n", stderr="", returncode=0),
            Mock(stdout="Size: 2048\n", stderr="", returncode=0),
        ]

        packages = checker.check_updates()
        assert len(packages) == 2
        assert packages[0].name == "package1"
        assert packages[0].current_version == "1.0"
        assert packages[0].new_version == "2.0"
        assert packages[1].name == "package2"

    @patch("distiller_update.checker.subprocess.run")
    def test_run_command_timeout(self, mock_run, checker):
        """Test command timeout handling."""
        mock_run.side_effect = subprocess.TimeoutExpired(["cmd"], 1.0)

        stdout, stderr, code = checker._run_command(["test"], timeout=1.0)
        assert stdout == ""
        assert stderr == "Command timed out"
        assert code == 1

    @patch("distiller_update.checker.subprocess.run")
    def test_run_command_error(self, mock_run, checker):
        """Test command error handling."""
        mock_run.side_effect = Exception("Command failed")

        stdout, stderr, code = checker._run_command(["test"])
        assert stdout == ""
        assert stderr == "Command failed"
        assert code == 1

    def test_save_and_load_result(self, checker, config):
        """Test saving and loading cache results."""
        packages = [
            Package(name="test1", current_version="1.0", new_version="2.0", size=1024),
            Package(name="test2", current_version="2.0", new_version="3.0", size=2048),
        ]
        result = UpdateResult(packages=packages, distribution="stable")

        # Save result
        checker._save_result(result)

        # Check file exists
        cache_file = config.cache_dir / "last_check.json"
        assert cache_file.exists()

        # Load result
        loaded = checker._load_cached_result()
        assert loaded is not None
        assert len(loaded.packages) == 2
        assert loaded.packages[0].name == "test1"
        assert loaded.distribution == "stable"

    def test_load_nonexistent_cache(self, checker):
        """Test loading when cache doesn't exist."""
        result = checker._load_cached_result()
        assert result is None

    def test_notify_all(self, checker):
        """Test notification of all notifiers."""
        mock_notifier1 = Mock()
        mock_notifier2 = Mock()
        checker.add_notifier(mock_notifier1)
        checker.add_notifier(mock_notifier2)

        result = UpdateResult(packages=[], distribution="stable")
        checker._notify_all(result)

        mock_notifier1.notify.assert_called_once_with(result)
        mock_notifier2.notify.assert_called_once_with(result)

    def test_notify_with_exception(self, checker):
        """Test notification continues even if one notifier fails."""
        mock_notifier1 = Mock()
        mock_notifier1.notify.side_effect = Exception("Notification failed")
        mock_notifier2 = Mock()

        checker.add_notifier(mock_notifier1)
        checker.add_notifier(mock_notifier2)

        result = UpdateResult(packages=[], distribution="stable")
        checker._notify_all(result)

        # Both should be called despite first one failing
        mock_notifier1.notify.assert_called_once_with(result)
        mock_notifier2.notify.assert_called_once_with(result)

    @patch("distiller_update.checker.subprocess.run")
    def test_check_full_flow(self, mock_run, checker, config):
        """Test the full check flow."""
        # Setup mocks
        mock_run.side_effect = [
            Mock(stdout="", stderr="", returncode=0),
            Mock(
                stdout="package1/stable 2.0 amd64 [upgradable from: 1.0]\n", stderr="", returncode=0
            ),
            Mock(stdout="Size: 1024\n", stderr="", returncode=0),
        ]

        mock_notifier = Mock()
        checker.add_notifier(mock_notifier)

        # Run check
        result = checker.check()

        # Verify result
        assert result.has_updates
        assert len(result.packages) == 1
        assert result.packages[0].name == "package1"

        # Verify cache was saved
        cache_file = config.cache_dir / "last_check.json"
        assert cache_file.exists()

        # Verify notifier was called
        mock_notifier.notify.assert_called_once()

    @patch("distiller_update.checker.UpdateChecker.check_updates")
    def test_check_with_failure_raises(self, mock_check_updates, checker):
        """Test that check raises exception on failure."""
        mock_check_updates.side_effect = Exception("APT failed")

        with pytest.raises(Exception) as exc_info:
            checker.check()
        assert "APT failed" in str(exc_info.value)

    @patch("distiller_update.checker.subprocess.run")
    def test_check_updates_filters_by_distribution(self, mock_run, checker):
        """Test that distribution filtering is applied when apt_source_file is None."""
        # Checker is configured for 'stable' distribution
        assert checker.config.distribution == "stable"
        assert checker.config.apt_source_file is None

        mock_run.side_effect = [
            Mock(stdout="", stderr="", returncode=0),  # apt-get update
            Mock(
                stdout="Listing...\n"
                "package1/stable 2.0 amd64 [upgradable from: 1.0]\n"
                "package2/testing 3.0 amd64 [upgradable from: 2.0]\n"
                "package3/unstable 4.0 amd64 [upgradable from: 3.0]\n",
                stderr="",
                returncode=0,
            ),  # apt list
            Mock(stdout="Size: 1024\n", stderr="", returncode=0),  # size query
        ]

        packages = checker.check_updates()

        # Only package1 should be included (stable distribution)
        assert len(packages) == 1
        assert packages[0].name == "package1"

    @patch("distiller_update.checker.subprocess.run")
    def test_check_updates_skips_filter_with_apt_source_file(self, mock_run, tmp_path):
        """Test that distribution filtering is skipped when apt_source_file is set."""
        # Create checker with apt_source_file configured
        config = Config(
            cache_dir=tmp_path / "cache",
            motd_file=tmp_path / "motd" / "99-distiller-updates",
            apt_cache_dir=tmp_path / "apt-cache",
            check_interval=3600,
            distribution="stable",
            apt_source_file="sources.list.d/pamir-ai.list",
        )
        checker = UpdateChecker(config)

        mock_run.side_effect = [
            Mock(stdout="", stderr="", returncode=0),  # apt-get update
            Mock(
                stdout="Listing...\n"
                "package1/stable 2.0 amd64 [upgradable from: 1.0]\n"
                "package2/testing 3.0 amd64 [upgradable from: 2.0]\n"
                "package3/unstable 4.0 amd64 [upgradable from: 3.0]\n",
                stderr="",
                returncode=0,
            ),  # apt list
            Mock(
                stdout="Package: package1\nSize: 1024\n\n"
                "Package: package2\nSize: 2048\n\n"
                "Package: package3\nSize: 4096\n",
                stderr="",
                returncode=0,
            ),  # batch size query
        ]

        packages = checker.check_updates()

        # All packages should be included (no distribution filtering)
        assert len(packages) == 3
        assert packages[0].name == "package1"
        assert packages[1].name == "package2"
        assert packages[2].name == "package3"
