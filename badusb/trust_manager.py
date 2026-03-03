"""Trust period tracking for each connected USB device."""

import time
from .config import TRUSTED_TEST_DURATION


class TrustManager:
    """
    Marks a USB device as trusted once it has been present for
    TRUSTED_TEST_DURATION seconds without triggering any alert.
    """

    def __init__(self) -> None:
        self.trusted: set[str] = set()
        self._first_seen: dict[str, float] = {}
        self._has_alert: set[str] = set()

    def evaluate(self, devices: list[str], alerted_devices: set[str]) -> None:
        """
        Update trust state for the currently visible devices.

        Args:
            devices: current list of detected device labels.
            alerted_devices: labels that have triggered at least one alert.
        """
        now = time.time()
        self._has_alert |= alerted_devices

        for dev in devices:
            if dev in self.trusted:
                continue
            if dev not in self._first_seen:
                self._first_seen[dev] = now
            elapsed = now - self._first_seen[dev]
            if elapsed >= TRUSTED_TEST_DURATION and dev not in self._has_alert:
                self.trusted.add(dev)

    def mark_suspicious(self, dev: str) -> None:
        """Prevent a device from ever being marked as trusted."""
        self._has_alert.add(dev)
        self.trusted.discard(dev)

    def summary_lines(self) -> list[str]:
        """Return display lines for the Trusted USBs panel."""
        if not self.trusted:
            return ["(No device has completed the verification period yet)"]
        return [
            f"[OK] {d}  [no alerts >{TRUSTED_TEST_DURATION}s]"
            for d in sorted(self.trusted)
        ]
