import asyncio
import signal
from pathlib import Path
from typing import Any

import structlog

from .checker import UpdateChecker
from .models import Config
from .news import NewsFetcher
from .notifiers import DBusNotifier, MOTDNotifier
from .utils.config import load_config

logger = structlog.get_logger()


def _get_directory_mtime(path: Path) -> float:
    """Get the modification time of a directory, handling errors gracefully."""
    try:
        return path.stat().st_mtime if path.exists() else 0.0
    except (OSError, PermissionError) as e:
        logger.warning(f"Cannot access directory {path} for mtime check", error=str(e))
        return 0.0


class UpdateDaemon:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.checker = UpdateChecker(config)
        self.news_fetcher = NewsFetcher(config)
        self.running = False
        self.check_task: asyncio.Task[Any] | None = None
        self.last_apt_cache_mtime: float = 0.0

        self.checker.add_notifier(MOTDNotifier(config))
        self.dbus_notifier: DBusNotifier | None = None
        if config.notify_dbus:
            self.dbus_notifier = DBusNotifier(config)
            self.checker.add_notifier(self.dbus_notifier)

    async def start(self) -> None:
        if self.config.check_interval < 3600:
            logger.warning(
                f"Check interval of {self.config.check_interval}s is very low. "
                f"Consider using >= 3600s (1 hour) for production use."
            )

        self._update_apt_cache_mtime()

        self.running = True
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(self.stop(s)),  # type: ignore
            )

        try:
            await asyncio.to_thread(self.checker.check)
            await asyncio.to_thread(self.news_fetcher.fetch)
            self.check_task = asyncio.create_task(self._check_loop())
            await self.check_task  # Wait for the check loop to complete

        except asyncio.CancelledError:
            logger.debug("Daemon start cancelled")
            raise
        except Exception as e:
            logger.error("Daemon error", error=str(e), exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def _check_loop(self) -> None:
        while self.running:
            try:
                if self._has_apt_cache_changed():
                    logger.info("APT cache changed, checking for updates")
                    await asyncio.to_thread(self.checker.check)
                    await asyncio.to_thread(self.news_fetcher.fetch)
                    self._update_apt_cache_mtime()

                await asyncio.sleep(self.config.check_interval)

                if not self.running:
                    break

                await asyncio.to_thread(self.checker.check)
                await asyncio.to_thread(self.news_fetcher.fetch)

            except asyncio.CancelledError:
                logger.debug("Check loop cancelled")
                break
            except Exception as e:
                logger.error(
                    "Check failed, will retry on next interval", error=str(e), exc_info=True
                )

    async def stop(self, sig: signal.Signals | None = None) -> None:
        if sig:
            logger.info("Received signal", signal=sig.name)

        self.running = False

        if self.check_task and not self.check_task.done():
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                logger.debug("Check task cancelled successfully")

    async def cleanup(self) -> None:
        if self.dbus_notifier:
            await self.dbus_notifier.close()

    def _has_apt_cache_changed(self) -> bool:
        """Check if APT cache directory has been modified since last check."""
        current_mtime = _get_directory_mtime(self.config.apt_lists_path)
        return current_mtime > self.last_apt_cache_mtime

    def _update_apt_cache_mtime(self) -> None:
        """Update the stored modification time of APT cache directory."""
        self.last_apt_cache_mtime = _get_directory_mtime(self.config.apt_lists_path)

    def run_once(self) -> None:
        # Only add notifiers if checker has none
        if not self.checker.notifiers:
            self.checker.add_notifier(MOTDNotifier(self.config))
            if self.config.notify_dbus:
                dbus_notifier = DBusNotifier(self.config)
                self.checker.add_notifier(dbus_notifier)
                try:
                    self.checker.check()
                    self.news_fetcher.fetch()
                finally:
                    asyncio.run(dbus_notifier.close())
            else:
                self.checker.check()
                self.news_fetcher.fetch()
        else:
            self.checker.check()
            self.news_fetcher.fetch()


async def run_daemon(config_path: Path | None = None) -> None:
    config = load_config(config_path)
    daemon = UpdateDaemon(config)
    await daemon.start()
