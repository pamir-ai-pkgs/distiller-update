"""Distiller Update - APT update checker for Pamir AI devices.

Modern, async Python package for monitoring updates from apt.pamir.ai
with MOTD and DBus desktop notifications.
"""

__version__ = "2.1.0"
__author__ = "PamirAI Incorporated"

from .checker import UpdateChecker
from .models import Config

__all__ = ["Config", "UpdateChecker", "__version__"]
