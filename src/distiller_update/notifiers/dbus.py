import structlog
from dbus_fast import BusType, Message, Variant
from dbus_fast.aio import MessageBus

from ..models import Config, UpdateResult
from ..utils.formatting import format_size

logger = structlog.get_logger()


class DBusNotifier:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.app_name = "distiller-update"
        self.app_icon = "system-software-update"
        self.bus: MessageBus | None = None

    async def notify(self, result: UpdateResult) -> None:
        if not self.config.notify_dbus:
            return

        if not result.has_updates:
            return

        try:
            await self._ensure_connected()
            title = "System Updates Available"
            body = self._create_body(result)
            await self._send_notification(title, body, urgency=1)

        except Exception:
            pass  # DBus notifications are optional

    async def _ensure_connected(self) -> None:
        if self.bus is None:
            try:
                self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
            except Exception:
                try:
                    self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                except Exception:
                    raise

    def _create_body(self, result: UpdateResult) -> str:
        lines = [result.summary]

        if len(result.packages) <= 5:
            lines.append("")
            lines.append("Packages:")
            for pkg in result.packages[:5]:
                lines.append(f"• {pkg.name} ({pkg.new_version})")

        if result.total_size > 0:
            lines.append("")
            lines.append(f"Download size: {format_size(result.total_size)}")

        return "\n".join(lines)

    async def _send_notification(
        self, title: str, body: str, urgency: int = 1, timeout: int = 10000
    ) -> None:
        if not self.bus:
            raise RuntimeError("Not connected to DBus")

        message = Message(
            destination="org.freedesktop.Notifications",
            path="/org/freedesktop/Notifications",
            interface="org.freedesktop.Notifications",
            member="Notify",
            signature="susssasa{sv}i",
            body=[
                self.app_name,
                0,
                self.app_icon,
                title,
                body,
                [],
                {
                    "urgency": Variant("y", urgency),
                    "category": Variant("s", "system"),
                },
                timeout,
            ],
        )

        reply = await self.bus.call(message)
        if reply:
            pass  # Notification ID not needed

    async def close(self) -> None:
        if self.bus:
            self.bus.disconnect()
            self.bus = None
