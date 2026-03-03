"""
Keyboard fuzzer — countermeasure against HID injection attacks.

When activated, periodically injects random characters via pynput's keyboard
controller to corrupt whatever payload the rogue HID device is typing.

Tunable parameters are read from badusb/settings.py:
    FUZZER_INTERVAL, FUZZER_BURST_SIZE, FUZZER_DURATION
"""

import random
import string
import threading
import time

from pynput.keyboard import Controller

from .settings import FUZZER_BURST_SIZE, FUZZER_DURATION, FUZZER_INTERVAL

# Characters injected as noise — weighted toward inputs that disrupt scripts
_FUZZ_POOL = (
    string.ascii_letters * 2   # letters (most common in payloads)
    + string.digits
    + string.punctuation        # includes ; , | & > < \ / " ' ` etc.
    + "\t" * 4                  # tabs — break indentation and script flow
    + " " * 3
)


class KeyboardFuzzer:
    """
    Injects random keystrokes at a regular interval to corrupt HID payloads.

    Parameters come from settings.py by default but can be overridden at
    construction time for testing.

    Usage:
        fuzzer = KeyboardFuzzer()
        fuzzer.start(label="MT YMD75 [20a0:422d]")
        ...
        fuzzer.stop(label)    # stop one device
        fuzzer.stop_all()     # stop all (e.g. on ACTIVE BLOCK OFF)
    """

    def __init__(
        self,
        interval: float = FUZZER_INTERVAL,
        burst: int = FUZZER_BURST_SIZE,
        duration: float = FUZZER_DURATION,
    ) -> None:
        """
        Args:
            interval: seconds between fuzz bursts.
            burst:    maximum characters per burst (minimum is always 3).
            duration: seconds after which fuzzing auto-stops (0 = unlimited).
        """
        self._interval = interval
        self._burst    = max(burst, 3)
        self._duration = duration
        self._ctrl     = Controller()
        self._stop_flags: dict[str, threading.Event] = {}

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self, label: str) -> None:
        """Start fuzzing for the given device label (no-op if already running)."""
        if label in self._stop_flags:
            return
        stop_evt = threading.Event()
        self._stop_flags[label] = stop_evt
        threading.Thread(
            target=self._loop,
            args=(stop_evt,),
            name=f"fuzzer-{label[:20]}",
            daemon=True,
        ).start()

    def stop(self, label: str) -> None:
        """Stop fuzzing for a specific device."""
        evt = self._stop_flags.pop(label, None)
        if evt:
            evt.set()

    def stop_all(self) -> None:
        """Stop all active fuzz loops."""
        for evt in self._stop_flags.values():
            evt.set()
        self._stop_flags.clear()

    @property
    def active_labels(self) -> list[str]:
        """Labels of devices currently being fuzzed."""
        return list(self._stop_flags.keys())

    # ── Internal loop ───────────────────────────────────────────────────────

    def _loop(self, stop: threading.Event) -> None:
        deadline = (
            time.monotonic() + self._duration if self._duration > 0 else None
        )
        while not stop.wait(self._interval):
            if deadline and time.monotonic() >= deadline:
                break
            count = random.randint(3, self._burst)
            chars = "".join(random.choices(_FUZZ_POOL, k=count))
            try:
                self._ctrl.type(chars)
            except Exception:
                pass  # ignore if display/keyboard access is unavailable
