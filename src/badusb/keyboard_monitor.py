"""Global keystroke capture and keystroke-dynamics analysis (IKI, jitter, TTFK).

Key design decisions:
- IKI samples are kept **per device** (keyed by active_kbd_id) so that a
  human typing after a BadUSB attack does not pollute the bad device's window.
- Detection has two tiers:
    1. Consecutive-IKI: fires after CONSECUTIVE_FAST_THRESHOLD fast intervals
       in a row (immune to occasional human bursts).
    2. Statistical: once the per-device window has OBSERVATION_MIN_KEYS samples,
       jitter (std-dev) is evaluated to catch constant-speed emulators.
"""

import statistics
import time
from collections import deque
from typing import Callable

from pynput import keyboard

from .settings import (
    CONSECUTIVE_FAST_THRESHOLD,
    IKI_WINDOW_SIZE,
    LOW_JITTER_THRESHOLD,
    MAX_HUMAN_IKI,
    MAX_HUMAN_KPS,
    OBSERVATION_MIN_KEYS,
    OBS_MAX_LOG,
)
from .usb_monitor import UsbMonitor


class KeyboardMonitor:
    """
    Listens for global keystrokes and analyses typing dynamics per device.

    Callbacks:
        on_observation(line: str)  — new observation log entry.
        on_alert(msg: str)         — suspicious pattern detected.
    """

    def __init__(
        self,
        on_observation: Callable[[str], None],
        on_alert: Callable[[str], None],
    ) -> None:
        self._on_observation = on_observation
        self._on_alert = on_alert

        # Active keyboard identity (updated by refresh_active_keyboard)
        self.active_kbd_id: str = "Unknown device"
        self.active_kbd_vidpid: str | None = None

        # Focus mode
        self.focused_vidpid: str | None = None
        self.focused_label: str | None = None

        # Per-device state — each device gets its own rolling IKI window
        self._iki_buffers: dict[str, deque[float]] = {}
        self._last_press:  dict[str, float]        = {}
        self._ttfk_done:   dict[str, bool]         = {}
        # Consecutive superhuman IKI counter per device (resets on slow IKI)
        self._fast_streak: dict[str, int]           = {}

        self._monitoring_start: float = time.time()

        # Ring buffer of the last OBS_MAX_LOG observations (for export)
        self.obs_log: deque[str] = deque(maxlen=OBS_MAX_LOG)

        self._listener: keyboard.Listener | None = None

    # ── Listener control ────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the global keyboard listener.

        suppress=False keeps normal key delivery to other apps.
        The listener is resilient against bad keysyms from HID injectors
        (e.g. Rubber Ducky) because _on_key_press wraps everything in
        try/except — pynput's Xlib backend can produce a SIGSEGV if an
        unknown keysym reaches the C layer unguarded.
        """
        self._listener = keyboard.Listener(
            on_press=self._safe_on_key_press,
            suppress=False,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()

    # ── Active keyboard refresh ─────────────────────────────────────────────

    def refresh_active_keyboard(self) -> None:
        """Poll pyudev for the current active USB keyboard."""
        label, vidpid = UsbMonitor.resolve_active_keyboard()
        self.active_kbd_id     = label
        self.active_kbd_vidpid = vidpid

    # ── Focus helpers ───────────────────────────────────────────────────────

    def set_focus(self, label: str) -> None:
        self.focused_label  = label
        self.focused_vidpid = _vidpid_from_label(label)

    def clear_focus(self) -> None:
        self.focused_label  = None
        self.focused_vidpid = None

    def is_focused_device(self) -> bool:
        """Return True if the active keyboard is the focused device (or no focus)."""
        if self.focused_label is None:
            return True
        if self.focused_vidpid and self.active_kbd_vidpid:
            return self.focused_vidpid == self.active_kbd_vidpid
        return self.active_kbd_id == self.focused_label

    # ── Keystroke processing ────────────────────────────────────────────────

    def _safe_on_key_press(self, key: object) -> None:
        """Resilient wrapper: absorb any exception so the listener never dies."""
        try:
            self._on_key_press(key)
        except Exception:  # noqa: BLE001
            pass  # bad keysym / X11 error from HID injector — ignore

    def _on_key_press(self, key: object) -> None:
        """Internal pynput callback — runs in the pynput listener thread."""
        if not self.is_focused_device():
            return

        now = time.time()
        kbd = self.active_kbd_id   # snapshot to avoid race with hardware poll

        # TTFK (once per device)
        if not self._ttfk_done.get(kbd, False):
            ttfk = now - self._monitoring_start
            self._emit_obs(f"TTFK: {ttfk:.4f}s — analysing injection patterns...")
            self._ttfk_done[kbd] = True

        if kbd in self._last_press:
            iki = now - self._last_press[kbd]

            # Tier 1: consecutive-IKI detection
            if iki < MAX_HUMAN_IKI:
                self._fast_streak[kbd] = self._fast_streak.get(kbd, 0) + 1
                streak = self._fast_streak[kbd]
                cps_instant = 1.0 / iki
                self._emit_obs(
                    f"[!] Fast IKI {streak}/{CONSECUTIVE_FAST_THRESHOLD}: "
                    f"{cps_instant:.1f} CPS  (IKI={iki*1000:.1f}ms)"
                )
                if streak >= CONSECUTIVE_FAST_THRESHOLD:
                    self._on_alert(
                        f"INJECTION DETECTED: {streak} consecutive keystrokes at "
                        f"{cps_instant:.1f} CPS exceed human threshold ({MAX_HUMAN_KPS} CPS)."
                    )
                    self._fast_streak[kbd] = 0
            else:
                self._fast_streak[kbd] = 0

            # Tier 2: statistical window (jitter)
            buf = self._iki_buffers.setdefault(kbd, deque(maxlen=IKI_WINDOW_SIZE))
            buf.append(iki)
            if len(buf) >= OBSERVATION_MIN_KEYS:
                self._analyse_window(kbd, buf)

        self._last_press[kbd] = now

    def _analyse_window(self, kbd: str, buf: deque[float]) -> None:
        """Statistical analysis of the IKI window for a given device."""
        samples = list(buf)
        if len(samples) < 2:
            return

        avg_iki = statistics.mean(samples)
        jitter  = statistics.stdev(samples)
        cps_avg = 1.0 / avg_iki if avg_iki > 0 else 0.0

        self._emit_obs(
            f"Avg speed: {cps_avg:.2f} CPS | Jitter: {jitter:.6f}s | "
            f"Device: {kbd}"
        )

        if cps_avg > MAX_HUMAN_KPS:
            self._on_alert(
                f"INJECTION DETECTED: Average speed {cps_avg:.2f} CPS "
                f"exceeds human threshold."
            )

        if jitter < LOW_JITTER_THRESHOLD and len(samples) >= 10:
            self._on_alert(
                f"MECHANICAL PATTERN: Jitter {jitter:.6f}s suggests HID emulation."
            )

    def _emit_obs(self, msg: str) -> None:
        ts   = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{self.active_kbd_id}] {msg}"
        self.obs_log.append(line)
        self._on_observation(line)


# ── Label parsing ───────────────────────────────────────────────────────────

def _vidpid_from_label(label: str) -> str | None:
    """Extract 'vid:pid' from 'Vendor Model [vid:pid]'."""
    if "[" in label and label.endswith("]"):
        return label.split("[")[-1].rstrip("]")
    return None
