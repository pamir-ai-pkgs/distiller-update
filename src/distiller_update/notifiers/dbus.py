"""DBus notifier for desktop notifications."""

import structlog
from dbus_fast import BusType, Message, Variant
from dbus_fast.aio import MessageBus

from ..models import Config, UpdateResult

logger = structlog.get_logger()


class DBusNotifier:
    """Send desktop notifications via DBus."""

    def __init__(self, config: Config) -> None:
        """Initialize DBus notifier."""
        self.config = config
        self.app_name = "distiller-update"
        self.app_icon = "system-software-update"
        self.bus: MessageBus | None = None

    async def notify(self, result: UpdateResult) -> None:
        """Send desktop notification about updates."""
        if not self.config.notify_dbus:
            return

        # Only notify if there are updates
        if not result.has_updates:
            return

        try:
            # Connect to session bus (user notifications)
            await self._ensure_connected()

            # Create notification
            title = "System Updates Available"
            body = self._create_body(result)

            # Send notification
            await self._send_notification(title, body, urgency=1)  # Normal urgency

            logger.info("Sent DBus notification", package_count=len(result.packages))

        except Exception as e:
            logger.debug("Failed to send DBus notification", error=str(e))
            # Don't fail hard on notification errors

    async def _ensure_connected(self) -> None:
        """Ensure we're connected to DBus."""
        if self.bus is None:
            try:
                # Try session bus first (for user notifications)
                self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
            except Exception:
                # Fall back to system bus if session bus not available
                try:
                    self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                except Exception as e:
                    logger.debug("Failed to connect to DBus", error=str(e))
                    raise

    def _create_body(self, result: UpdateResult) -> str:
        """Create notification body text."""
        lines = [result.summary]

        # Add package details if not too many
        if len(result.packages) <= 5:
            lines.append("")
            lines.append("Packages:")
            for pkg in result.packages[:5]:
                lines.append(f"• {pkg.name} ({pkg.new_version})")

        # Add total size if available
        if result.total_size > 0:
            lines.append("")
            lines.append(f"Download size: {self._format_size(result.total_size)}")

        return "\n".join(lines)

    def _format_size(self, size: int) -> str:
        """Format size in human-readable format."""
        if size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f}MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f}GB"

    async def _send_notification(
        self, title: str, body: str, urgency: int = 1, timeout: int = 10000
    ) -> None:
        """Send notification via DBus."""
        if not self.bus:
            raise RuntimeError("Not connected to DBus")

        # Build the notification message
        message = Message(
            destination="org.freedesktop.Notifications",
            path="/org/freedesktop/Notifications",
            interface="org.freedesktop.Notifications",
            member="Notify",
            signature="susssasa{sv}i",
            body=[
                self.app_name,  # app_name
                0,  # replaces_id (0 = new notification)
                self.app_icon,  # app_icon
                title,  # summary
                body,  # body
                [],  # actions
                {  # hints
                    "urgency": Variant("y", urgency),
                    "category": Variant("s", "system"),
                },
                timeout,  # expire_timeout in ms (-1 = never, 0 = default)
            ],
        )

        # Send the notification
        reply = await self.bus.call(message)
        if reply:
            notification_id = reply.body[0] if reply.body else 0
            logger.debug("Notification sent", id=notification_id)

    async def close(self) -> None:
        """Close DBus connection."""
        if self.bus:
            self.bus.disconnect()
            self.bus = None
