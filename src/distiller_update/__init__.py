"""
Distiller Update Notifier
"""

__version__ = "0.1.0"
__author__ = "PamirAI Incorporated"

from .checker import UpdateChecker
from .config import Config

__all__ = ["Config", "UpdateChecker", "__version__"]
