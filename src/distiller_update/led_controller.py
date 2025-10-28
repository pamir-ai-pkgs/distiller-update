import time
from types import TracebackType
from typing import Any

import structlog

logger = structlog.get_logger()


class LEDController:
    """
    Controller for LED status indicators during updates.

    Provides visual feedback using distiller-sdk LED animations:
    - Blue fade: Update in progress
    - Green fade: Update successful (10 seconds)
    - Red blink: Update failed (10 seconds)
    - Off: Idle state

    LED operations gracefully degrade if SDK or hardware unavailable.
    """

    def __init__(self) -> None:
        """Initialize LED controller with graceful fallback."""
        self.led: Any | None = None
        self.available_leds: list[int] = []
        self.enabled = False

        try:
            # Dynamic import to avoid hard dependency
            from distiller_sdk.hardware.sam.led import create_led_with_sudo

            self.led = create_led_with_sudo()
            self.available_leds = self.led.get_available_leds()
            self.enabled = len(self.available_leds) > 0

            if self.enabled:
                logger.info(
                    "LED controller initialized",
                    led_count=len(self.available_leds),
                    led_ids=self.available_leds,
                )
            else:
                logger.warning("No LEDs found, LED indicators disabled")

        except ImportError:
            logger.warning("distiller-sdk not available, LED indicators disabled")
        except Exception as e:
            logger.error("LED initialization failed", error=str(e), exc_info=True)

    def set_updating(self) -> None:
        """
        Set all LEDs to blue fade animation (update in progress).

        Blue fade runs continuously in kernel driver until changed.
        All LEDs are set to blue simultaneously, then fade animation is enabled.
        """
        if not self.enabled or not self.led:
            return

        try:
            self.led.set_color_all(0, 0, 255)

            for led_id in self.available_leds:
                self.led.set_animation_mode(led_id, "fade", 1000)

        except Exception as e:
            logger.error("Failed to set updating LED state", error=str(e), exc_info=True)

    def set_success(self) -> None:
        """
        Set all LEDs to green fade for 10 seconds, then turn off.

        Green fade indicates successful update completion.
        Blocks for 10 seconds while animation runs.
        """
        if not self.enabled or not self.led:
            return

        try:
            self.led.set_color_all(0, 255, 0)

            for led_id in self.available_leds:
                self.led.set_animation_mode(led_id, "fade", 1000)

            time.sleep(10)
            self.turn_off()
        except Exception as e:
            logger.error("Failed to set success LED state", error=str(e), exc_info=True)
            self.turn_off()

    def set_error(self) -> None:
        """
        Set all LEDs to red blink for 10 seconds, then turn off.

        Red blink indicates update failure or error.
        Blocks for 10 seconds while animation runs.
        """
        if not self.enabled or not self.led:
            return

        try:
            self.led.set_color_all(255, 0, 0)

            for led_id in self.available_leds:
                self.led.set_animation_mode(led_id, "blink", 1000)

            time.sleep(10)
            self.turn_off()
        except Exception as e:
            logger.error("Failed to set error LED state", error=str(e), exc_info=True)
            self.turn_off()

    def turn_off(self) -> None:
        """Turn off all LEDs.

        Stops all animations by setting to static mode before turning off.
        This ensures kernel-based animations (fade, blink) are properly terminated.
        """
        if not self.enabled or not self.led:
            return

        try:
            # Stop all animations first by setting to static mode
            for led_id in self.available_leds:
                self.led.set_animation_mode(led_id, "static", 0)

            # Then turn off all LEDs
            self.led.turn_off_all()
        except Exception as e:
            logger.error("Failed to turn off LEDs", error=str(e), exc_info=True)

    def __enter__(self) -> "LEDController":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Context manager exit - ensure LEDs are turned off."""
        self.turn_off()
