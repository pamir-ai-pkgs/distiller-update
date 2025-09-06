import os
import tomllib
from pathlib import Path

import structlog

from ..models import Config

logger = structlog.get_logger()

DEFAULT_CONFIG_PATH = Path("/etc/distiller-update/config.toml")
USER_CONFIG_PATH = Path.home() / ".config/distiller-update/config.toml"


def load_config(config_path: Path | None = None) -> Config:
    if config_path:
        if config_path.exists():
            try:
                with open(config_path, "rb") as f:
                    data = tomllib.load(f)
                    cfg = Config(**data)
                    logger.info(f"Loaded config from {config_path}")
                    return cfg
            except ValueError as e:
                logger.error(f"Config validation failed for {config_path}: {e}")
                raise SystemExit(1) from None
            except Exception as e:
                logger.warning(f"Failed to load config from {config_path}: {e}")
        else:
            logger.warning(f"Config file not found: {config_path}")

    for path in [DEFAULT_CONFIG_PATH, USER_CONFIG_PATH]:
        if path.exists():
            try:
                with open(path, "rb") as f:
                    data = tomllib.load(f)
                    cfg = Config(**data)
                    logger.info(f"Loaded config from {path}")
                    return cfg
            except ValueError as e:
                logger.error(f"Config validation failed for {path}: {e}")
                raise SystemExit(1) from None
            except Exception as e:
                logger.debug(f"Failed to load config from {path}: {e}")
                continue

    if any(k.startswith("DISTILLER_") for k in os.environ):
        logger.info("Loading config from environment variables")
        return Config()

    logger.info("Using default configuration")
    return Config()
