# Distiller Update Notifier

APT update notification daemon for headless Debian/Ubuntu systems.

## Features

- MOTD notifications on SSH login
- Systemd journal integration
- JSON status file for monitoring
- Automatic log rotation
- Package priority classification
- Zero external dependencies

## Installation

### From Package
```bash
sudo dpkg -i distiller-update_0.1.0_all.deb
sudo apt-get -f install
```

### From Source
```bash
git clone https://github.com/pamir-ai/distiller-update.git
cd distiller-update
./build-deb.sh
sudo dpkg -i dist/distiller-update_*.deb
```

## Usage

```bash
distiller-update check    # Check once
distiller-update list     # List available updates
distiller-update status   # Show current status
distiller-update config   # Show configuration
distiller-update daemon   # Run as daemon
```

### Systemd Service

```bash
systemctl status distiller-update.timer
systemctl status distiller-update.service
journalctl -u distiller-update
```

## Configuration

Edit `/etc/distiller-update/config.yaml`:

```yaml
repository:
  url: "http://localhost"
  distributions: ["stable", "testing", "unstable"]

checking:
  interval_seconds: 3600
  on_startup: true

notifications:
  motd:
    enabled: true
    show_packages: true
    color: true
  journal:
    enabled: true
    priority: "info"
  status_file:
    enabled: true
    path: "/var/lib/distiller-update/status.json"
  log_file:
    enabled: true
    path: "/var/log/distiller-update.log"
    max_size_mb: 10

filters:
  include_packages: []
  exclude_packages: []
  priority_levels: ["critical", "high", "medium", "low"]
```

## Priority Levels

- **Critical**: kernel, systemd, openssl, libssl
- **High**: distiller-*, python3, ssh, security packages
- **Medium**: application updates
- **Low**: other packages

## Files

- `/etc/distiller-update/config.yaml` - Configuration
- `/var/lib/distiller-update/status.json` - Current status
- `/var/log/distiller-update.log` - Log file
- `/etc/update-motd.d/99-distiller-updates` - MOTD script

## Status File

```json
{
  "last_check": "2024-01-15T10:30:00",
  "next_check": "2024-01-15T11:30:00",
  "update_available": true,
  "total_updates": 5,
  "summary": {
    "by_priority": {
      "critical": 1,
      "high": 2,
      "medium": 2,
      "low": 0
    }
  },
  "updates": [
    {
      "name": "distiller-cc",
      "installed_version": "1.0.1",
      "available_version": "1.0.2",
      "priority": "high"
    }
  ]
}
```

## Monitoring Integration

```bash
# Check if updates available
jq '.update_available' /var/lib/distiller-update/status.json

# Count critical updates
jq '.summary.by_priority.critical' /var/lib/distiller-update/status.json
```

## Development

### Requirements
- Python 3.11+
- Debian build tools

### Build
```bash
# Install dependencies
uv pip install -e .[dev]

# Lint
ruff check src/

# Build package
./build-deb.sh
```

### Test
```bash
python -m distiller_update check
python -m distiller_update list
```

## Troubleshooting

### No updates shown
```bash
apt-cache policy
systemctl status distiller-update.timer
journalctl -u distiller-update -n 50
```

### Required Permissions
- Read: `/var/cache/apt/`
- Write: `/var/cache/distiller-update/`, `/var/lib/distiller-update/`, `/var/log/`, `/etc/update-motd.d/`

## License

MIT

## Author

PamirAI Incorporated - support@pamir.ai