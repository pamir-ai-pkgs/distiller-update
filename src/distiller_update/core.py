import asyncio
from datetime import datetime
from typing import Protocol

import structlog

from .apt import AptInterface
from .models import Config, UpdateResult
from .utils.logging import setup_logging

logger = structlog.get_logger()


class Notifier(Protocol):
    async def notify(self, result: UpdateResult) -> None: ...


class UpdateChecker:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.apt = AptInterface(config)
        self.notifiers: list[Notifier] = []
        config.ensure_directories()
        setup_logging(config.log_level)

    def add_notifier(self, notifier: Notifier) -> None:
        self.notifiers.append(notifier)

    async def check(self) -> UpdateResult:
        try:
            packages = await self.apt.check_updates()
            result = UpdateResult(
                packages=packages,
                checked_at=datetime.now(),
                distribution=self.config.distribution,
            )

            await self._save_result(result)
            await self._notify_all(result)

            return result

        except Exception as e:
            logger.error("Update check failed", error=str(e), exc_info=True)
            return UpdateResult(distribution=self.config.distribution)

    async def _save_result(self, result: UpdateResult) -> None:
        cache_file = self.config.cache_dir / "last_check.json"
        try:
            import json

            import aiofiles

            data = result.model_dump(mode="json")
            json_str = json.dumps(data, indent=2, default=str)

            async with aiofiles.open(cache_file, "w") as f:
                await f.write(json_str)
        except Exception as e:
            logger.warning("Failed to save cache", error=str(e))

    async def _load_cached_result(self) -> UpdateResult | None:
        cache_file = self.config.cache_dir / "last_check.json"
        if not cache_file.exists():
            return None

        try:
            import aiofiles

            async with aiofiles.open(cache_file) as f:
                content = await f.read()
                return UpdateResult.model_validate_json(content)
        except Exception as e:
            logger.debug("Failed to load cache", error=str(e))
            return None

    async def _notify_all(self, result: UpdateResult) -> None:
        if not self.notifiers:
            return

        async with asyncio.TaskGroup() as tg:
            for notifier in self.notifiers:
                tg.create_task(self._safe_notify(notifier, result))

    async def _safe_notify(self, notifier: Notifier, result: UpdateResult) -> None:
        try:
            await notifier.notify(result)
        except Exception as e:
            logger.warning(
                "Notifier failed",
                notifier=notifier.__class__.__name__,
                error=str(e),
            )

    async def get_status(self) -> UpdateResult | None:
        return await self._load_cached_result()
