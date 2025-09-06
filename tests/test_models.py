import pytest

from distiller_update.models import Config, Package, UpdateResult


def test_package_model():
    pkg = Package(
        name="test-package",
        current_version="1.0.0",
        new_version="2.0.0",
        size=1024 * 1024,
    )

    assert pkg.name == "test-package"
    assert pkg.current_version == "1.0.0"
    assert pkg.new_version == "2.0.0"
    assert pkg.display_size == "1.0MB"


def test_update_result():
    packages = [
        Package(name="pkg1", current_version="1.0", new_version="2.0", size=1024),
        Package(name="pkg2", current_version="2.0", new_version="3.0", size=2048),
    ]

    result = UpdateResult(packages=packages, distribution="stable")

    assert result.has_updates is True
    assert len(result.packages) == 2
    assert result.total_size == 3072
    assert result.summary == "2 packages can be upgraded"


def test_update_result_empty():
    result = UpdateResult()

    assert result.has_updates is False
    assert len(result.packages) == 0
    assert result.summary == "System is up to date"


def test_config_defaults():
    config = Config()

    assert config.check_interval == 14400
    assert config.repository_url == "http://apt.pamir.ai"
    assert config.distribution == "stable"
    assert config.notify_motd is True
    assert config.notify_dbus is True
    assert config.log_level == "info"


def test_config_env_override():
    import os

    os.environ["DISTILLER_CHECK_INTERVAL"] = "7200"
    os.environ["DISTILLER_DISTRIBUTION"] = "testing"

    config = Config()

    assert config.check_interval == 7200
    assert config.distribution == "testing"

    del os.environ["DISTILLER_CHECK_INTERVAL"]
    del os.environ["DISTILLER_DISTRIBUTION"]


def test_config_validation():
    with pytest.raises(ValueError):
        Config(check_interval=0)

    with pytest.raises(ValueError):
        Config(distribution="invalid")
