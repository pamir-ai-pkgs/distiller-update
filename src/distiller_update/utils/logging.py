import logging
from pathlib import Path
from typing import Literal

import structlog


def setup_logging(log_level: Literal["debug", "info", "warning", "error"] = "info") -> None:
    # Convert string log level to logging constant
    numeric_level = getattr(logging, log_level.upper())

    # Configure root logger level and handlers
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove any existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    root_logger.addHandler(console_handler)
    log_dir = Path("/var/log/distiller-update")
    log_file = log_dir / "distiller-update.log"

    if log_dir.exists() and log_dir.is_dir():
        try:
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(numeric_level)
            root_logger.addHandler(file_handler)
        except (PermissionError, OSError) as e:
            console_handler.setLevel(logging.WARNING)
            root_logger.warning(f"Could not set up file logging: {e}")

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
