"""CLI-level regression tests."""

import json

from typer.testing import CliRunner

from distiller_update.__main__ import app
from distiller_update.models import Config, Package


def test_list_json_refresh_outputs_clean_json(tmp_path, monkeypatch):
    """Ensure --json --refresh emits only JSON without rich decorations."""

    runner = CliRunner()

    config = Config(
        cache_dir=tmp_path / "cache",
        motd_file=tmp_path / "motd" / "99-distiller-updates",
        distribution="stable",
    )
    config.ensure_directories()

    packages = [Package(name="pkg1", current_version="1.0", new_version="1.1", size=1024)]

    class DummyChecker:
        def __init__(self, cfg: Config) -> None:
            self.config = cfg

        def check_updates(self, refresh: bool = True):
            assert refresh is True
            return packages

        def get_status(self):
            return None

    monkeypatch.setattr("distiller_update.__main__.get_config", lambda _path: config)
    monkeypatch.setattr("distiller_update.__main__.UpdateChecker", DummyChecker)

    result = runner.invoke(app, ["list", "--json", "--refresh"])

    assert result.exit_code == 0
    output = result.stdout.strip()
    assert output.startswith("{")
    assert "✓" not in output

    payload = json.loads(output)
    assert payload["has_updates"] is True
    assert payload["packages"][0]["name"] == "pkg1"
