# Distiller Update

APT update checker for Pamir AI Distiller devices.

## Features

- **Efficient APT checking** - Single query to check updates from apt.pamir.ai
- **Async/await** - Modern Python 3.11+ with full async support
- **Desktop notifications** - DBus integration for desktop alerts
- **MOTD integration** - Terminal login notifications
- **Simple configuration** - TOML-based config with sensible defaults

## Installation

```bash
# Install from source
uv sync

# Or install the Debian package
./build-deb.sh
sudo dpkg -i dist/distiller-update_*.deb
```

## Usage

```bash
# Check for updates once
distiller-update check

# Run as daemon
distiller-update daemon

# List available updates
distiller-update list

# Show configuration
distiller-update config-show
```

## Configuration

Configuration file: `/etc/distiller-update/config.toml`

```toml
check_interval = 14400  # 4 hours
repository_url = "http://apt.pamir.ai"
distribution = "stable"
notify_motd = true
notify_dbus = true
```

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
