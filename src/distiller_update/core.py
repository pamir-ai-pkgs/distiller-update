"""Core update checking logic."""

import asyncio
from datetime import datetime
from typing import Protocol

import structlog

from .apt import AptInterface
from .models import Config, UpdateResult

logger = structlog.get_logger()


class Notifier(Protocol):
    """Protocol for notification handlers."""

    async def notify(self, result: UpdateResult) -> None:
        """Send notification about update status."""
        ...


class UpdateChecker:
    """Main update checker with async support."""

    def __init__(self, config: Config) -> None:
        """Initialize update checker."""
        self.config = config
        self.apt = AptInterface(config)
        self.notifiers: list[Notifier] = []

        # Ensure cache directory exists
        config.ensure_directories()

        # Configure structured logging
        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer(),
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    def add_notifier(self, notifier: Notifier) -> None:
        """Add a notification handler."""
        self.notifiers.append(notifier)

    async def check(self) -> UpdateResult:
        """Check for updates from apt.pamir.ai."""
        logger.info("Starting update check", distribution=self.config.distribution)

        try:
            packages = await self.apt.check_updates()
            result = UpdateResult(
                packages=packages,
                checked_at=datetime.now(),
                distribution=self.config.distribution,
            )

            logger.info(
                "Update check complete",
                has_updates=result.has_updates,
                package_count=len(packages),
                total_size=result.total_size,
            )

            # Save result to cache
            await self._save_result(result)

            # Notify all handlers
            await self._notify_all(result)

            return result

        except Exception as e:
            logger.error("Update check failed", error=str(e), exc_info=True)
            # Return empty result on error
            return UpdateResult(distribution=self.config.distribution)

    async def _save_result(self, result: UpdateResult) -> None:
        """Save check result to cache."""
        cache_file = self.config.cache_dir / "last_check.json"
        try:
            import json

            import aiofiles

            # Use model_dump() to get dict, then json.dumps for serialization
            # This is more robust across Pydantic versions
            data = result.model_dump(mode="json")
            json_str = json.dumps(data, indent=2, default=str)

            async with aiofiles.open(cache_file, "w") as f:
                await f.write(json_str)
        except Exception as e:
            logger.warning("Failed to save cache", error=str(e))

    async def _load_cached_result(self) -> UpdateResult | None:
        """Load cached result if available."""
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
        """Send notifications to all handlers."""
        if not self.notifiers:
            return

        # Run all notifiers concurrently
        # Use TaskGroup for better error handling (Python 3.11+)
        async with asyncio.TaskGroup() as tg:
            for notifier in self.notifiers:
                tg.create_task(self._safe_notify(notifier, result))

    async def _safe_notify(self, notifier: Notifier, result: UpdateResult) -> None:
        """Safely call a notifier with error handling."""
        try:
            await notifier.notify(result)
        except Exception as e:
            logger.warning(
                "Notifier failed",
                notifier=notifier.__class__.__name__,
                error=str(e),
            )

    async def get_status(self) -> UpdateResult | None:
        """Get current status from cache."""
        return await self._load_cached_result()
