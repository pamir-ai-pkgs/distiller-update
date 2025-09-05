"""Distiller Update - Simple APT update checker for Pamir AI devices.

Modern, async Python package for monitoring updates from apt.pamir.ai
with MOTD and DBus desktop notifications.
"""

__version__ = "0.2.0"
__author__ = "PamirAI Incorporated"

from .core import UpdateChecker
from .models import Config

__all__ = ["Config", "UpdateChecker", "__version__"]
