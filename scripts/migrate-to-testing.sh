#!/bin/bash
set -e

LOGFILE="/var/log/pamir-migration.log"
MARKER="/var/lib/pamir-migration-complete"
SERVICE_FILE="/etc/systemd/system/pamir-migration.service"
SCRIPT_PATH="/usr/local/bin/migrate-to-testing.sh"
PLATFORM_DETECT="/usr/local/bin/platform-detect.sh"

log() {
	echo "[$(date -Iseconds)] $*" | tee -a "$LOGFILE"
}

cleanup_migration_artifacts() {
	log "Cleaning up migration artifacts..."

	# Remove service file first
	rm -f "$SERVICE_FILE"

	# Disable service (don't stop - we're running as this service!)
	systemctl disable pamir-migration.service 2>/dev/null || true

	# Remove scripts
	rm -f "$SCRIPT_PATH"
	rm -f "$PLATFORM_DETECT"

	# Reload systemd
	systemctl daemon-reload

	log "All migration artifacts removed"
}

# Check if already migrated
if [ -f "$MARKER" ]; then
	log "Migration already complete"
	cleanup_migration_artifacts
	exit 0
fi

log "=== Pamir AI Migration: unstable -> testing ==="

# Pre-flight: Network connectivity
log "Checking network connectivity..."
if ! curl -sSf --connect-timeout 10 https://apt.pamir.ai/ >/dev/null 2>&1; then
	log "WARNING: Cannot reach apt.pamir.ai - will retry in 60s"
	sleep 60
	exec "$0" # Retry
fi

# Pre-flight: Disk space (need at least 1GB)
log "Checking disk space..."
FREE_KB=$(df /var/cache/apt | tail -1 | awk '{print $4}')
if [ "$FREE_KB" -lt 1048576 ]; then
	log "ERROR: Insufficient disk space (need 1GB, have ${FREE_KB}KB)"
	exit 1
fi

# Wait for APT lock (max 30 minutes)
log "Waiting for APT lock to be released..."
WAIT_COUNT=0
while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 ||
	fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
	sleep 5
	WAIT_COUNT=$((WAIT_COUNT + 1))
	if [ $WAIT_COUNT -gt 360 ]; then
		log "ERROR: APT lock held for 30+ minutes, aborting"
		exit 1
	fi
done

log "APT lock released"

# Backup current sources
if [ -f /etc/apt/sources.list.d/pamir-ai.list ]; then
	BACKUP_FILE="/var/lib/pamir-ai.list.backup-$(date +%Y%m%d-%H%M%S)"
	cp /etc/apt/sources.list.d/pamir-ai.list "$BACKUP_FILE"
	log "Backed up sources to $BACKUP_FILE"
fi

# Update sources to testing
log "Updating sources.list to testing distribution..."
cat >/etc/apt/sources.list.d/pamir-ai.list <<'EOF'
deb [arch=arm64 signed-by=/usr/share/keyrings/pamir-ai-archive-keyring.gpg] https://apt.pamir.ai/ testing main
EOF

# Update package lists
log "Running apt update..."
if ! apt-get update; then
	log "ERROR: apt update failed, restoring backup"
	[ -f "$BACKUP_FILE" ] && cp "$BACKUP_FILE" /etc/apt/sources.list.d/pamir-ai.list
	apt-get update
	exit 1
fi

# Detect platform using bundled platform-detect.sh
log "Detecting hardware platform..."
PLATFORM="unknown"

if [ -f "$PLATFORM_DETECT" ]; then
	source "$PLATFORM_DETECT"
	PLATFORM=$(detect_platform)
	log "Detected platform: $PLATFORM ($(get_platform_description "$PLATFORM"))"
else
	log "ERROR: platform-detect.sh not found at $PLATFORM_DETECT"
	exit 1
fi

# Map platform to distiller-genesis package
GENESIS_PACKAGE=""
case "$PLATFORM" in
cm5)
	GENESIS_PACKAGE="distiller-genesis-cm5"
	;;
radxa | armbian | armsom-rk3576)
	GENESIS_PACKAGE="distiller-genesis-rockchip"
	;;
unknown)
	log "WARNING: Unknown platform, installing distiller-genesis-common"
	GENESIS_PACKAGE="distiller-genesis-common"
	;;
*)
	log "WARNING: Unexpected platform '$PLATFORM', defaulting to distiller-genesis-common"
	GENESIS_PACKAGE="distiller-genesis-common"
	;;
esac

log "Fixing any broken packages..."
DEBIAN_FRONTEND=noninteractive apt-get install -f -y || log "WARNING: Could not fix broken packages"

log "Purging old packages..."
DEBIAN_FRONTEND=noninteractive apt-get purge -y distiller-cm5-* || true
DEBIAN_FRONTEND=noninteractive apt-get purge -y distiller-test-harness || true
log "Old packages purged"

log "Installing $GENESIS_PACKAGE..."

# Install genesis meta-package (pulls in all new packages)
DEBIAN_FRONTEND=noninteractive apt-get install -y "$GENESIS_PACKAGE" --install-recommends || {
	log "ERROR: Failed to install $GENESIS_PACKAGE"
	exit 1
}

log "$GENESIS_PACKAGE installed successfully"

# Explicitly install critical packages (fallback if Recommends were skipped due to broken APT state)
log "Ensuring critical packages are installed..."
DEBIAN_FRONTEND=noninteractive apt-get install -y \
	distiller-sdk \
	distiller-services \
	distiller-update \
	distiller-telemetry \
	pamir-ai-sam-dkms \
	distiller-platform-update 2>&1 | tee -a "$LOGFILE" || \
	log "WARNING: Some recommended packages failed to install"

# Mark migration complete
touch "$MARKER"
log "=== Migration complete ==="

# Self-cleanup: Remove all migration artifacts
cleanup_migration_artifacts

log "Migration service cleaned up successfully"
exit 0
