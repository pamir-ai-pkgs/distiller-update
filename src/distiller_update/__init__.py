"""Distiller Update - APT update checker for Pamir AI devices.

Modern, async Python package for monitoring updates from apt.pamir.ai
with MOTD and DBus desktop notifications.
"""

from importlib.metadata import PackageNotFoundError, version

from .checker import UpdateChecker
from .models import Config

try:
    __version__ = version("distiller-update")
except PackageNotFoundError:
    __version__ = "dev"

__author__ = "PamirAI Incorporated"
__all__ = ["Config", "UpdateChecker", "__version__"]
