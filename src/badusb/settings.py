"""
settings.py — All tunable parameters for the BadUSB Heuristic Analyser.

Edit this file to adjust detection sensitivity, UI behaviour, and countermeasures.
"""

import platform

# ════════════════════════════════════════════════════════════════════════════
# Platform
# ════════════════════════════════════════════════════════════════════════════

# Detected automatically at import time — do not change.
OS_TYPE: str = platform.system()

# ════════════════════════════════════════════════════════════════════════════
# Keystroke-dynamics detection thresholds
# ════════════════════════════════════════════════════════════════════════════

# Maximum keystroke speed considered achievable by a human typist (keys/second).
# Badge USB injectors typically operate at 200–1000 CPS.
# Raise this value to reduce sensitivity; lower it to catch slower injectors.
MAX_HUMAN_KPS: float = 18.0

# Inter-Key Interval (seconds) corresponding to MAX_HUMAN_KPS.
# Computed automatically — do not change directly.
MAX_HUMAN_IKI: float = 1.0 / MAX_HUMAN_KPS   # ≈ 0.0667 s

# Number of *consecutive* superhuman IKIs required before a speed alert fires.
# Higher values reduce false positives from fast human typists.
# Recommended range: 4–8.
CONSECUTIVE_FAST_THRESHOLD: int = 5

# Standard deviation (seconds) of IKI below which constant-speed emulation is
# suspected. Human typing always shows natural jitter > this value.
LOW_JITTER_THRESHOLD: float = 0.005

# Minimum IKI samples in a device's window before jitter analysis is performed.
OBSERVATION_MIN_KEYS: int = 5

# Maximum IKI samples retained per device in the rolling analysis window.
IKI_WINDOW_SIZE: int = 30

# ════════════════════════════════════════════════════════════════════════════
# Trust classification
# ════════════════════════════════════════════════════════════════════════════

# Seconds a device must remain connected without any alert to be marked trusted.
TRUSTED_TEST_DURATION: int = 20

# ════════════════════════════════════════════════════════════════════════════
# Alert display
# ════════════════════════════════════════════════════════════════════════════

# Duration (seconds) of the red visual flash in the alert box after an alert.
ALERT_COOLDOWN: int = 100

# ════════════════════════════════════════════════════════════════════════════
# Observation log
# ════════════════════════════════════════════════════════════════════════════

# Maximum number of observation entries kept in memory (ring buffer).
# Also the number exported to the Markdown report.
OBS_MAX_LOG: int = 50

# ════════════════════════════════════════════════════════════════════════════
# Keyboard fuzzer (ACTIVE BLOCK countermeasure)
# ════════════════════════════════════════════════════════════════════════════

# Seconds between noise bursts injected by the fuzzer.
FUZZER_INTERVAL: float = 0.2

# Maximum number of random characters injected per burst (minimum is always 3).
FUZZER_BURST_SIZE: int = 10

# Seconds after which fuzzing auto-stops. Set to 0 for unlimited duration.
FUZZER_DURATION: float = 10

# ════════════════════════════════════════════════════════════════════════════
# Window size (relative to screen dimensions)
# ════════════════════════════════════════════════════════════════════════════

# Fraction of the screen width the main window should occupy (0.0–1.0).
WINDOW_WIDTH_RATIO: float = 0.40

# Fraction of the screen height the main window should occupy (0.0–1.0).
WINDOW_HEIGHT_RATIO: float = 0.75
