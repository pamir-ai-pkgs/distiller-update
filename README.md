# Distiller Update

APT update checker for Pamir AI Distiller devices.

## Features

- **Efficient APT checking** - Single query to check updates from apt.pamir.ai
- **News integration** - Fetches and displays news from Pamir AI on terminal login
- **Automated monitoring** - Systemd timer runs checks hourly with intelligent caching
- **Desktop notifications** - DBus integration for desktop alerts
- **MOTD integration** - Terminal login notifications with news and update status
- **Security validation** - Package name validation, command timeouts, and lock files
- **JSON output** - Scriptable with `--json` flag for automation
- **Async/await** - Modern Python 3.11+ with full async support
- **Simple configuration** - TOML-based config with sensible defaults

## Installation

```bash
# Install from source
uv sync

# Or install the Debian package (recommended)
./build-deb.sh
sudo dpkg -i dist/distiller-update_*.deb
```

The Debian package automatically enables and starts the systemd timer for hourly checks.

## Usage

Most commands require root privileges. Use `sudo` for all commands except `version`.

```bash
# Check for updates once
sudo distiller-update check

# List available updates
sudo distiller-update list
sudo distiller-update list --json      # JSON output for scripting
sudo distiller-update list --refresh   # Force APT cache refresh

# Apply available updates
sudo distiller-update apply

# Run as daemon (usually via systemd, not manually)
sudo distiller-update daemon

# Show version
distiller-update version
```

## Configuration

Configuration file: `/etc/distiller-update/config.toml`

```toml
# Core settings
check_interval = 14400              # Check interval in seconds (4 hours)
repository_url = "http://apt.pamir.ai"
distribution = "stable"             # Options: stable, testing, unstable
log_level = "info"                  # Options: debug, info, warning, error

# Notifications
notify_motd = true                  # Show updates in terminal MOTD
notify_dbus = true                  # Send desktop notifications

# News fetching
news_enabled = true                 # Enable news fetching
news_url = "https://apt.pamir.ai/NEWS"
news_fetch_timeout = 5              # Timeout in seconds (1-30)
news_cache_ttl = 86400              # Cache TTL in seconds (24 hours)

# APT command timeouts (in seconds)
apt_update_timeout = 120            # apt-get update
apt_list_timeout = 60               # apt list --upgradable
apt_query_timeout = 10              # Quick queries (dpkg, apt-cache)
apt_install_timeout = 1800          # Package installation (30 minutes)

# Policy settings
policy_allow_new_packages = true    # Allow installation of curated new packages
```

See [CLAUDE.md](CLAUDE.md) for complete configuration reference.

## Systemd Integration

The package includes a systemd timer that runs hourly checks automatically:

```bash
# Check timer status
sudo systemctl status distiller-update.timer

# View logs
sudo journalctl -u distiller-update -f

# Manually trigger a check (timer does this automatically)
sudo systemctl start distiller-update.service
```

## Troubleshooting

**Permission denied**: Most commands require root. Use `sudo`.

**Lock file error**: Another update is running. Wait or check for stuck processes with `ps aux | grep distiller-update`.

**Debug mode**: Set `log_level = "debug"` in config and view logs with `sudo journalctl -u distiller-update -f`.

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
uv run pytest

# Type checking
uv run mypy src/

# Linting
uv run ruff check src/
```

## License

MIT License - Copyright (c) 2024 PamirAI Incorporated
