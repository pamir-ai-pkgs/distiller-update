import logging
from typing import Literal

import structlog


def setup_logging(log_level: Literal["debug", "info", "warning", "error"] = "info") -> None:
    # Convert string log level to logging constant
    numeric_level = getattr(logging, log_level.upper())

    # Configure root logger level
    logging.basicConfig(
        level=numeric_level,
        format="%(message)s",
    )

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
