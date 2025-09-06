import asyncio
import signal
from pathlib import Path
from typing import Any

import structlog

from .core import UpdateChecker
from .models import Config
from .notifiers import DBusNotifier, MOTDNotifier
from .utils.config import load_config

logger = structlog.get_logger()


class UpdateDaemon:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.checker = UpdateChecker(config)
        self.running = False
        self.check_task: asyncio.Task[Any] | None = None
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

        self.running = True
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(self.stop(s)),  # type: ignore
            )

        try:
            await self.checker.check()
            async with asyncio.TaskGroup() as tg:
                self.check_task = tg.create_task(self._check_loop())

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Daemon error", error=str(e), exc_info=True)
            raise
        finally:
            await self.cleanup()

    async def _check_loop(self) -> None:
        while self.running:
            try:
                await asyncio.sleep(self.config.check_interval)

                if not self.running:
                    break
                await self.checker.check()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Check failed", error=str(e))

    async def stop(self, sig: signal.Signals | None = None) -> None:
        if sig:
            logger.info("Received signal", signal=sig.name)

        self.running = False

        if self.check_task and not self.check_task.done():
            self.check_task.cancel()
            try:
                await self.check_task
            except asyncio.CancelledError:
                pass

    async def cleanup(self) -> None:
        if self.dbus_notifier:
            await self.dbus_notifier.close()

    async def run_once(self) -> None:
        self.checker.add_notifier(MOTDNotifier(self.config))
        if self.config.notify_dbus:
            dbus_notifier = DBusNotifier(self.config)
            self.checker.add_notifier(dbus_notifier)
            try:
                await self.checker.check()
            finally:
                await dbus_notifier.close()
        else:
            await self.checker.check()


async def run_daemon(config_path: Path | None = None) -> None:
    config = load_config(config_path)
    daemon = UpdateDaemon(config)
    await daemon.start()
