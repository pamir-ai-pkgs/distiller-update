"""Daemon mode for continuous update checking"""

import logging
import signal
import time
from datetime import datetime
from types import FrameType
from typing import Any

from .checker import Package, UpdateChecker
from .config import Config
from .notifiers import JournalNotifier, LogNotifier, MOTDNotifier, StatusNotifier

logger = logging.getLogger(__name__)


class UpdateDaemon:
    """Daemon for continuous update checking"""

    def __init__(self, config_path: str | None = None) -> None:
        """Initialize daemon"""
        self.config = Config(config_path)
        self.checker = UpdateChecker(self.config)
        self.running = False
        self.signals_registered = False

        self.motd_notifier = MOTDNotifier(self.config)
        self.journal_notifier = JournalNotifier(self.config)
        self.status_notifier = StatusNotifier(self.config)
        self.log_notifier = LogNotifier(self.config)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        """Handle termination signals"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def _handle_reload(self, signum: int, frame: FrameType | None) -> None:
        """Handle reload signal (SIGHUP)"""
        logger.info("Received SIGHUP, reloading configuration...")
        self.config = Config()
        self.checker = UpdateChecker(self.config)

    def _register_signals(self) -> None:
        """Register signal handlers once"""
        if not self.signals_registered:
            signal.signal(signal.SIGTERM, self._handle_signal)
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGHUP, self._handle_reload)
            self.signals_registered = True

    def run(self) -> None:
        """Run the daemon"""
        logger.info("Starting Distiller Update daemon")
        self._register_signals()
        self.running = True

        # Log to journal that we're starting
        self.journal_notifier.log_check(checking=False)

        # Check on startup if configured
        if self.config.checking.on_startup:
            self._run_check()

        # Main loop
        while self.running:
            try:
                # Sleep for the configured interval
                interval = self.config.checking.interval_seconds
                logger.debug(f"Sleeping for {interval} seconds")

                # Use short sleeps to be responsive to signals
                for _ in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)

                if self.running:
                    self._run_check()

            except Exception as e:
                logger.error(f"Error in daemon loop: {e}")
                # Continue running despite errors
                time.sleep(60)  # Wait a bit before retrying

        logger.info("Distiller Update daemon stopped")

    def _run_check(self) -> None:
        """Run a single update check"""
        try:
            start_time = time.time()

            logger.info("Running update check")
            self.log_notifier.log_check_start()
            self.journal_notifier.log_check(checking=True)

            updates = self.checker.check_updates()
            summary = self.checker.get_update_summary(updates)

            cache_data = {
                "last_check": datetime.now().isoformat(),
                "updates": len(updates),
                "summary": summary,
            }
            self.config.save_cache(cache_data)

            self._send_notifications(updates, summary)

            duration = time.time() - start_time
            self.log_notifier.log_check_complete(duration)
            self.journal_notifier.log_check(checking=False)

            logger.info(f"Update check completed in {duration:.2f} seconds")

        except Exception as e:
            logger.error(f"Update check failed: {e}")
            self.log_notifier.log_error(f"Update check failed: {e}")

    def _send_notifications(self, updates: list[Package], summary: dict[str, Any]) -> None:
        """Send all configured notifications"""
        try:
            self.motd_notifier.notify(updates, summary)
        except Exception as e:
            logger.error(f"MOTD notification failed: {e}")

        try:
            self.journal_notifier.notify(updates, summary)
        except Exception as e:
            logger.error(f"Journal notification failed: {e}")

        try:
            self.status_notifier.notify(updates, summary)
        except Exception as e:
            logger.error(f"Status file notification failed: {e}")

        try:
            # Write to log file
            self.log_notifier.notify(updates, summary)
        except Exception as e:
            logger.error(f"Log file notification failed: {e}")

    def run_once(self) -> None:
        """Run a single check and exit"""
        logger.info("Running single update check")
        self._register_signals()  # Register signals for clean shutdown
        self._run_check()
        logger.info("Single update check complete")
