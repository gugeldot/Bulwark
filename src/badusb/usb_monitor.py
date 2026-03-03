"""USB device enumeration and active keyboard detection by platform."""

from .config import OS_TYPE


def _vidpid_from_label(label: str) -> str | None:
    """Extract 'vid:pid' from a label like 'Vendor Model [vid:pid]'."""
    if "[" in label and label.endswith("]"):
        return label.split("[")[-1].rstrip("]")
    return None


class UsbMonitor:
    """Detects and enumerates USB devices on the current platform."""

    def enumerate(self) -> list[str]:
        """
        Return a deduplicated list of USB device labels with real metadata.

        Linux format  : 'Vendor Model [vid:pid]'
        Windows format: registry key string.
        """
        if OS_TYPE == "Windows":
            return self._enumerate_windows()
        if OS_TYPE == "Linux":
            return self._enumerate_linux()
        return []

    # ── Platform implementations ────────────────────────────────────────────

    @staticmethod
    def _enumerate_windows() -> list[str]:
        try:
            import winreg
            devs = []
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Enum\USB"
            ) as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    devs.append(winreg.EnumKey(key, i))
            return devs
        except Exception:
            return []

    @staticmethod
    def _enumerate_linux() -> list[str]:
        try:
            import pyudev  # type: ignore
            context = pyudev.Context()
            seen: set[str] = set()
            devs: list[str] = []

            for device in context.list_devices(subsystem="usb"):
                vendor = device.get("ID_VENDOR", "Unknown")
                model  = device.get("ID_MODEL",  "Unknown")
                if vendor == "Unknown" and model == "Unknown":
                    continue
                vid = device.get("ID_VENDOR_ID", "")
                pid = device.get("ID_MODEL_ID",  "")
                entry = f"{vendor} {model}"
                if vid and pid:
                    entry += f" [{vid}:{pid}]"
                if entry not in seen:
                    seen.add(entry)
                    devs.append(entry)

            return devs
        except Exception:
            return []

    @staticmethod
    def resolve_active_keyboard() -> tuple[str, str | None]:
        """
        Detect the active USB keyboard on Linux via pyudev.

        Returns:
            (label, vid_pid) where label is 'Vendor Model [vid:pid]'
            and vid_pid is 'vid:pid' or None.
        """
        if OS_TYPE != "Linux":
            return "Unknown device", None
        try:
            import pyudev  # type: ignore
            context = pyudev.Context()
            for device in context.list_devices(subsystem="input"):
                if device.get("ID_INPUT_KEYBOARD") != "1":
                    continue
                parent = device.find_parent(subsystem="usb", device_type="usb_device")
                if parent is None:
                    continue
                vendor = parent.get("ID_VENDOR", "Unknown")
                model  = parent.get("ID_MODEL",  "Unknown")
                vid    = parent.get("ID_VENDOR_ID", "")
                pid    = parent.get("ID_MODEL_ID",  "")
                label  = f"{vendor} {model}"
                if vid and pid:
                    label += f" [{vid}:{pid}]"
                vidpid = f"{vid}:{pid}" if vid and pid else None
                return label, vidpid
        except Exception:
            pass
        return "Unknown device", None
