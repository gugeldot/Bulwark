"""Per-device alert deduplication keyed by VID:PID."""


class AlertManager:
    """
    Tracks which alert types have already been fired for each device.

    Key: 'vid:pid' string (or full label if VID/PID unavailable).
    Once a device fires a given alert type, it will not fire again
    during the same session (permanent deduplication).
    """

    def __init__(self) -> None:
        # { dev_key: set(alert_type) }
        self._fired: dict[str, set[str]] = {}

    def try_fire(self, dev_key: str, msg: str) -> bool:
        """
        Attempt to register an alert.

        Returns True if the alert is new (should be displayed),
        False if the same type was already fired for this device.
        """
        alert_type = msg.split(":")[0].strip()
        if dev_key not in self._fired:
            self._fired[dev_key] = set()
        if alert_type in self._fired[dev_key]:
            return False
        self._fired[dev_key].add(alert_type)
        return True

    def mark_suspicious(self, dev_key: str) -> None:
        """Flag a device as suspicious even without a specific alert type."""
        if dev_key not in self._fired:
            self._fired[dev_key] = set()

    def has_any_alert(self, dev_key: str) -> bool:
        """Return True if the device has triggered any alert this session."""
        return bool(self._fired.get(dev_key))

    def reset(self) -> None:
        """Clear all alert history (useful for tests)."""
        self._fired.clear()
