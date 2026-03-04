"""USB device enumeration and active keyboard detection by platform."""

import re

from .config import OS_TYPE

# Registry pattern: VID_XXXX&PID_XXXX
_VIDPID_RE = re.compile(r"VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})", re.IGNORECASE)


def _vidpid_from_label(label: str) -> str | None:
    """Extract 'vid:pid' from a label like 'Vendor Model [vid:pid]'."""
    if "[" in label and label.endswith("]"):
        return label.split("[")[-1].rstrip("]")
    return None


def _label_from_vidpid(vid: str, pid: str) -> str:
    """Build a display label from raw VID/PID hex strings."""
    return f"USB (VID_{vid.upper()}, PID_{pid.upper()})"


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
        """Return USB device labels from the registry.

        Tries to read FriendlyName from each device instance; falls back to
        'USB (VID_XXXX, PID_XXXX)' when no friendly name exists.
        """
        try:
            import winreg
            seen: set[str] = set()
            devs: list[str] = []

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Enum\USB",
            ) as usb_key:
                vid_pid_count = winreg.QueryInfoKey(usb_key)[0]
                for i in range(vid_pid_count):
                    vp_name = winreg.EnumKey(usb_key, i)   # e.g. "VID_045E&PID_0750"
                    m = _VIDPID_RE.search(vp_name)
                    vid, pid = (m.group(1), m.group(2)) if m else ("", "")

                    with winreg.OpenKey(usb_key, vp_name) as vp_key:
                        inst_count = winreg.QueryInfoKey(vp_key)[0]
                        for j in range(inst_count):
                            inst_name = winreg.EnumKey(vp_key, j)
                            try:
                                with winreg.OpenKey(vp_key, inst_name) as inst_key:
                                    try:
                                        friendly, _ = winreg.QueryValueEx(inst_key, "FriendlyName")
                                        label = str(friendly)
                                    except FileNotFoundError:
                                        label = _label_from_vidpid(vid, pid) if vid else vp_name
                            except OSError:
                                label = _label_from_vidpid(vid, pid) if vid else vp_name

                            if label not in seen:
                                seen.add(label)
                                devs.append(label)
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
        Detect the active USB keyboard.

        Returns:
            (label, vid_pid) where:
              - Linux  : label = 'Vendor Model [vid:pid]', vid_pid = 'vid:pid'
              - Windows: label = FriendlyName or 'USB (VID_XXXX, PID_XXXX)',
                         vid_pid = 'vid:pid' parsed from the registry key.
        """
        if OS_TYPE == "Windows":
            return UsbMonitor._resolve_windows_keyboard()
        if OS_TYPE == "Linux":
            return UsbMonitor._resolve_linux_keyboard()
        return "Unknown device", None

    @staticmethod
    def _resolve_windows_keyboard() -> tuple[str, str | None]:
        """Find the first HID keyboard in the registry and return its label."""
        try:
            import winreg

            hid_path = r"SYSTEM\CurrentControlSet\Enum\HID"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hid_path) as hid_key:
                for i in range(winreg.QueryInfoKey(hid_key)[0]):
                    vp_name = winreg.EnumKey(hid_key, i)  # e.g. "VID_045E&PID_0750"
                    m = _VIDPID_RE.search(vp_name)
                    if not m:
                        continue
                    vid, pid = m.group(1).upper(), m.group(2).upper()
                    vidpid = f"{vid}:{pid}"

                    with winreg.OpenKey(hid_key, vp_name) as vp_key:
                        for j in range(winreg.QueryInfoKey(vp_key)[0]):
                            inst_name = winreg.EnumKey(vp_key, j)
                            try:
                                with winreg.OpenKey(vp_key, inst_name) as inst_key:
                                    # Only consider devices whose service is a keyboard driver
                                    try:
                                        service, _ = winreg.QueryValueEx(inst_key, "Service")
                                        if "kbdhid" not in str(service).lower():
                                            continue
                                    except FileNotFoundError:
                                        continue

                                    try:
                                        friendly, _ = winreg.QueryValueEx(inst_key, "FriendlyName")
                                        label = str(friendly)
                                    except FileNotFoundError:
                                        label = _label_from_vidpid(vid, pid)

                                    return label, vidpid
                            except OSError:
                                continue
        except Exception:
            pass
        return "Unknown device", None

    @staticmethod
    def _resolve_linux_keyboard() -> tuple[str, str | None]:
        """Detect the active USB keyboard on Linux via pyudev."""
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
