# BadUSB Heuristic Analyser

A desktop application that monitors connected USB devices and analyses keystroke dynamics in real time to detect HID injection attacks (BadUSB / Rubber Ducky / O.MG Cable, etc.).

Built with Python + Tkinter. No external cloud services. Runs entirely on-device.

---

## Features

- **USB enumeration** — lists all connected USB devices with Vendor ID and Product ID
- **WATCH / FOCUS mode** — monitor all devices or pin attention to a single one
- **Keystroke dynamics analysis** — detects superhuman typing speed (CPS) and mechanical jitter (two tiers)
- **Trusted device tracking** — marks devices clean after a configurable quiet period
- **ACTIVE BLOCK** — injects random keyboard noise to corrupt live HID payloads
- **Observation log** — per-device TTFK, speed and jitter, collapsible and clearable
- **Markdown report** — one-click export to Desktop with all session data

---

## Platform Compatibility

| Feature | Linux | Windows |
|---|:---:|:---:|
| USB device listing | ✅ Full (pyudev) | ⚠️ Basic (winreg keys) |
| Active keyboard identification | ✅ (pyudev input subsystem) | ❌ Returns "Unknown device" |
| Keystroke dynamics (pynput) | ✅ X11 / Wayland* | ✅ |
| ACTIVE BLOCK fuzzer (pynput) | ✅ | ✅ |
| GUI (tkinter) | ✅ | ✅ |
| Save dialog / Desktop path | ✅ | ✅ |

> **\* Wayland note:** `pynput` global keyboard listener requires `python3-xlib` on X11.
> On Wayland it may not capture keystrokes from other applications without additional permissions.

> **Windows note:** USB label resolution uses the registry (device IDs, no friendly names).
> Active keyboard identification is not implemented — all keystroke events are attributed to "Unknown device".


---

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`

### Linux additional dependencies

```bash
# pynput on X11
sudo apt install python3-xlib   # Debian/Ubuntu
sudo pacman -S python-xlib      # Arch

# pyudev for USB detection
sudo apt install python3-pyudev # Debian/Ubuntu (or via pip)

```

### Windows

No additional system packages needed. `winreg` is part of the standard library.

---

## Installation

```bash
git clone https://github.com/gugeldot/Bulwark.git
cd Bulwark

# Create and activate virtual environment (recommended)
python -m venv venv
source venv/bin/activate        # Linux/macOS
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

---

## Usage

```bash
python main.py
```

### Workflow

1. Launch the app — it starts in **WATCH mode** monitoring all USB devices.
2. The **Detected USB Devices** list updates every 3 seconds. Use the **Search** bar to filter.
3. Keystroke speed and jitter for the active keyboard appear in **Observation — Keystroke Dynamics**.
4. If a device types at superhuman speed (default: 5 consecutive intervals > 15 CPS), a **Critical Alert** fires.
5. Optionally click a device to enter **FOCUS mode** — only that device's keystrokes are analysed.
6. Enable **ACTIVE BLOCK** to automatically inject random characters when an alert fires, corrupting the payload.
7. Click **Save Report** to export a Markdown summary to your Desktop.

---

## How detection works

### Tier 1 — Speed (real-time)

Every keystroke IKI (Inter-Key Interval) is compared against `1 / MAX_HUMAN_KPS`.
If `CONSECUTIVE_FAST_THRESHOLD` consecutive IKIs are all below that limit, an alert fires immediately.
A human typist can exceed the threshold momentarily; a BadUSB sustains it.

### Tier 2 — Jitter (statistical)

Over a sliding window of up to 30 IKI samples, the standard deviation is computed.
If jitter < `LOW_JITTER_THRESHOLD` over 10+ samples, the device is flagged as a constant-speed emulator.

Both tiers are **per-device** — your own keyboard's samples never contaminate the suspect device's window.

---

## Known limitations

- Active keyboard identification only works on Linux (pyudev input subsystem).
- The ACTIVE BLOCK fuzzer injects characters into whichever window has focus — avoid running with sensitive documents open.
- KVM switches and USB hubs can introduce variable latency, potentially raising jitter and suppressing Tier 2 alerts for a real BadUSB.
- `pynput` on Wayland may require additional configuration to capture global events.

---

## Academic context

Developed as part of a Final Degree Project (TFG) at Universidad de Alcalá (UAH), GISI degree, 2025–2026.
Research focus: heuristic detection of BadUSB HID injection attacks.
