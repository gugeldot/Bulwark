"""BadUSB heuristic detector — main GUI (tkinter)."""

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

from badusb.alert_manager import AlertManager
from badusb.blocker import KeyboardFuzzer
from badusb.config import ALERT_COOLDOWN, OS_TYPE
from badusb.settings import FUZZER_DURATION, FUZZER_INTERVAL, CONSECUTIVE_FAST_THRESHOLD, MAX_HUMAN_KPS, LOW_JITTER_THRESHOLD, TRUSTED_TEST_DURATION, OBS_MAX_LOG
from badusb.keyboard_monitor import KeyboardMonitor
from badusb.report import generate_report
from badusb.trust_manager import TrustManager
from badusb.usb_monitor import UsbMonitor

# ── Help text ───────────────────────────────────────────────────────────────
_HELP_TEXT = """\
BadUSB Heuristic Analyser — Quick Guide

WATCH mode (default)
  Monitors all connected USB devices and logs global keystroke dynamics.

FOCUS mode
  Click any device in the Detected USBs list to focus on it.
  Keystroke analysis and alerts will only apply to that device.
  Click the same device again to return to WATCH mode.

Trusted USBs
  A device is marked as trusted after it has been present for
  {trust}s without triggering any alert.

Critical Alerts
  An alert fires when keystroke speed exceeds {kps} CPS (superhuman)
  or inter-key jitter is below {jitter}s (mechanical pattern).
  Each alert type fires only once per device per session.

Observation — Keystroke Dynamics
  Logs TTFK, speed (CPS) and jitter for the active keyboard.
  Use the Clear button to reset the log.

Save Report
  Exports a Markdown report to your Desktop (or Home folder)
  with all session data, including the last {obs} log entries.
""".format(
    trust=20, kps=15, jitter=0.005, obs=50
)


def _default_save_dir() -> Path:
    """Return the user's Desktop if it exists, otherwise their home directory."""
    home    = Path.home()
    desktop = home / "Desktop"
    if not desktop.exists():          # Spanish-locale Linux convention
        desktop = home / "Escritorio"
    return desktop if desktop.exists() else home


class BadUSBDetectorGUI:
    """Main window of the BadUSB detector."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"BadUSB Heuristic Analysis ({OS_TYPE}) — UAH")
        self.root.geometry("950x1100")
        self.root.configure(bg="#2c3e50")

        # Business-logic components
        self._usb_monitor   = UsbMonitor()
        self._alert_manager = AlertManager()
        self._trust_manager = TrustManager()
        self._kbd_monitor   = KeyboardMonitor(
            on_observation=self._on_observation,
            on_alert=self._on_alert,
        )

        # UI state
        self._current_devices: list[str] = []
        self._focused_usb: str | None    = None
        self._alert_log: list[str]        = []
        self._fuzzer = KeyboardFuzzer()

        self._setup_ui()

        # Start background threads
        self._stop = False
        threading.Thread(target=self._hardware_loop, daemon=True).start()
        self._kbd_monitor.start()

    # ══════════════════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════════════════

    def _setup_ui(self) -> None:
        hf = ("Consolas", 12, "bold")
        lf = ("Consolas", 10)

        # ── Scrollable container (canvas + optional scrollbar) ─────────────
        self._scroll_canvas = tk.Canvas(
            self.root, bg="#2c3e50", highlightthickness=0
        )
        self._scroll_vsb = tk.Scrollbar(
            self.root, orient="vertical", command=self._scroll_canvas.yview
        )
        self._scroll_canvas.configure(yscrollcommand=self._on_scroll_update)
        self._scroll_canvas.pack(side="left", fill="both", expand=True)
        # scrollbar packed on demand by _on_scroll_update

        self._container = tk.Frame(self._scroll_canvas, bg="#2c3e50")
        _cwin = self._scroll_canvas.create_window(
            (0, 0), window=self._container, anchor="nw"
        )

        def _on_inner_resize(event):
            self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all")
            )
            self._update_scrollbar_visibility()

        def _on_canvas_resize(event):
            self._scroll_canvas.itemconfig(_cwin, width=event.width)
            self._update_scrollbar_visibility()

        self._container.bind("<Configure>", _on_inner_resize)
        self._scroll_canvas.bind("<Configure>", _on_canvas_resize)

        # Linux mouse-wheel — only when hovering the canvas, not the listboxes
        self._scroll_canvas.bind("<Button-4>",
            lambda e: self._scroll_canvas.yview_scroll(-1, "units"))
        self._scroll_canvas.bind("<Button-5>",
            lambda e: self._scroll_canvas.yview_scroll(1, "units"))
        self._container.bind("<Button-4>",
            lambda e: self._scroll_canvas.yview_scroll(-1, "units"))
        self._container.bind("<Button-5>",
            lambda e: self._scroll_canvas.yview_scroll(1, "units"))

        # ── Top bar: Mode indicator · ACTIVE BLOCK toggle · Help button ──────
        top_bar = tk.Frame(self._container, bg="#2c3e50")
        top_bar.pack(fill="x", padx=10, pady=(8, 0))

        tk.Label(top_bar, text="Mode:", fg="#ecf0f1", bg="#2c3e50",
                 font=("Consolas", 11, "bold")).pack(side="left")
        self._mode_label = tk.Label(
            top_bar, text=" WATCH ",
            fg="#2c3e50", bg="#00bcd4",
            font=("Consolas", 11, "bold"), padx=6, pady=1,
        )
        self._mode_label.pack(side="left", padx=(6, 0))

        # Help button (far right)
        tk.Button(
            top_bar, text=" ? ",
            fg="#ecf0f1", bg="#7f8c8d",
            activebackground="#616a6b", activeforeground="#ecf0f1",
            font=("Consolas", 11, "bold"),
            relief="flat", cursor="hand2",
            command=self._show_help,
        ).pack(side="right")

        # ACTIVE BLOCK toggle
        self._block_active = False
        self._block_btn = tk.Button(
            top_bar, text="ACTIVE BLOCK: OFF",
            fg="#ecf0f1", bg="#7f8c8d",
            activebackground="#616a6b", activeforeground="#ecf0f1",
            font=("Consolas", 10, "bold"),
            relief="flat", cursor="hand2", padx=8,
            command=self._toggle_block,
        )
        self._block_btn.pack(side="right", padx=(0, 6))

        # ── Detected USBs (2-column Listbox, shared scrollbar) ────────────
        self._detected_label = tk.Label(
            self._container, text="Detected USB Devices: (0)",
            fg="#ecf0f1", bg="#2c3e50", font=hf)
        self._detected_label.pack(pady=(8, 2))

        # Search bar
        self._search_var = tk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._apply_search())
        search_row = tk.Frame(self._container, bg="#2c3e50")
        search_row.pack(fill="x", padx=10, pady=(0, 4))
        tk.Label(search_row, text="Search:", fg="#95a5a6", bg="#2c3e50",
                 font=("Consolas", 10)).pack(side="left", padx=(0, 4))
        tk.Entry(
            search_row, textvariable=self._search_var,
            font=("Consolas", 10), bg="#1e2b37", fg="#ecf0f1",
            insertbackground="#ecf0f1", relief="flat",
        ).pack(side="left", fill="x", expand=True)
        lb_frame = tk.Frame(self._container, bg="#2c3e50")
        lb_frame.pack(fill="x", padx=10)

        # Shared scrollbar (rightmost)
        shared_sb = tk.Scrollbar(lb_frame, orient="vertical")
        shared_sb.pack(side="right", fill="y")

        def _sync_scroll(*args):
            """Move both columns when the scrollbar is dragged."""
            self._lb_left.yview(*args)
            self._lb_right.yview(*args)

        def _on_lb_scroll(first, last):
            """Update shared scrollbar when either column is scrolled."""
            shared_sb.set(first, last)

        shared_sb.config(command=_sync_scroll)

        lb_cfg = dict(
            height=6, font=lf,
            bg="#1e2b37", fg="#ecf0f1",
            selectbackground="#f39c12", selectforeground="#2c3e50",
            activestyle="none",
            yscrollcommand=_on_lb_scroll,
            exportselection=False,
        )

        col_l = tk.Frame(lb_frame, bg="#2c3e50")
        col_r = tk.Frame(lb_frame, bg="#2c3e50")
        col_l.pack(side="left", fill="both", expand=True, padx=(0, 2))
        col_r.pack(side="left", fill="both", expand=True)

        self._lb_left  = tk.Listbox(col_l, **lb_cfg)
        self._lb_right = tk.Listbox(col_r, **lb_cfg)
        self._lb_left.pack(fill="both", expand=True)
        self._lb_right.pack(fill="both", expand=True)
        self._lb_left.bind("<<ListboxSelect>>",  lambda e: self._on_lb_select(e, "left"))
        self._lb_right.bind("<<ListboxSelect>>", lambda e: self._on_lb_select(e, "right"))
        # Sync the other column when mouse-wheel scrolls one
        self._lb_left.bind("<MouseWheel>",  lambda e: self._lb_right.yview("scroll", -1 if e.delta > 0 else 1, "units"))
        self._lb_right.bind("<MouseWheel>", lambda e: self._lb_left.yview("scroll",  -1 if e.delta > 0 else 1, "units"))
        self._lb_left.bind("<Button-4>",  lambda e: (self._lb_right.yview("scroll", -1, "units"), None))
        self._lb_left.bind("<Button-5>",  lambda e: (self._lb_right.yview("scroll",  1, "units"), None))
        self._lb_right.bind("<Button-4>", lambda e: (self._lb_left.yview("scroll",  -1, "units"), None))
        self._lb_right.bind("<Button-5>", lambda e: (self._lb_left.yview("scroll",   1, "units"), None))


        # ── Trusted USBs ───────────────────────────────────────────────────
        tk.Label(self._container, text="Trusted USB Devices:", fg="#2ecc71", bg="#2c3e50",
                 font=hf).pack(pady=(10, 2))
        self._trusted_box = scrolledtext.ScrolledText(
            self._container, height=6, width=110, font=lf,
            bg="#34495e", fg="#2ecc71",
        )
        self._trusted_box.pack(padx=10, fill="x")

        # ── Critical Alerts ────────────────────────────────────────────────
        alert_hrow = tk.Frame(self._container, bg="#2c3e50")
        alert_hrow.pack(fill="x", padx=10, pady=(10, 2))
        tk.Label(alert_hrow, text="Critical Alerts:", fg="#e74c3c", bg="#2c3e50",
                 font=hf).pack(side="left")
        tk.Button(
            alert_hrow, text="Clear Alerts",
            fg="#ecf0f1", bg="#7f8c8d",
            activebackground="#616a6b", activeforeground="#ecf0f1",
            font=("Consolas", 10, "bold"),
            relief="flat", cursor="hand2", padx=6,
            command=self._clear_alerts,
        ).pack(side="right")
        self._alert_box = scrolledtext.ScrolledText(
            self._container, height=8, width=110, font=lf,
            bg="#34495e", fg="#e74c3c",
        )
        self._alert_box.pack(padx=10, fill="x")

        # ── Observation — Keystroke Dynamics (collapsible) ─────────────────
        self._obs_collapsed = False
        self._build_obs_section(lf)

        # ── Save Report button ─────────────────────────────────────────────
        tk.Button(
            self._container,
            text="  Save Report (Markdown)",
            font=("Consolas", 11, "bold"),
            bg="#2980b9", fg="#ecf0f1",
            activebackground="#1a5276", activeforeground="#ecf0f1",
            relief="flat", cursor="hand2", pady=6,
            command=self._save_results,
        ).pack(fill="x", padx=10, pady=(10, 8))

    def _build_obs_section(self, list_font: tuple) -> None:
        obs_frame = tk.Frame(self._container, bg="#2c3e50")
        obs_frame.pack(fill="x", padx=10, pady=(10, 5))

        hrow = tk.Frame(obs_frame, bg="#2c3e50")
        hrow.pack(fill="x")

        self._obs_toggle = tk.Button(
            hrow,
            text="▼  Observation — Keystroke Dynamics:",
            fg="#f1c40f", bg="#2c3e50",
            font=("Consolas", 12, "bold"),
            relief="flat", cursor="hand2", anchor="w",
            command=self._toggle_obs,
        )
        self._obs_toggle.pack(side="left", fill="x", expand=True)

        tk.Button(
            hrow, text="Clear",
            fg="#ecf0f1", bg="#7f8c8d",
            activebackground="#616a6b", activeforeground="#ecf0f1",
            font=("Consolas", 10, "bold"),
            relief="flat", cursor="hand2", padx=6,
            command=self._clear_obs,
        ).pack(side="right")

        self._obs_box = scrolledtext.ScrolledText(
            obs_frame, height=8, width=110, font=("Consolas", 10),
            bg="#34495e", fg="#f1c40f",
        )
        self._obs_box.pack(padx=0, fill="x")

    # ══════════════════════════════════════════════════════════════════════
    # Observation panel
    # ══════════════════════════════════════════════════════════════════════

    def _on_scroll_update(self, first: str, last: str) -> None:
        """Called by the canvas yscrollcommand; shows/hides the scrollbar."""
        self._scroll_vsb.set(first, last)
        self._update_scrollbar_visibility()

    def _update_scrollbar_visibility(self) -> None:
        """Show the scrollbar only when content overflows the visible area."""
        if not hasattr(self, "_container"):
            return
        content_h = self._container.winfo_reqheight()
        canvas_h  = self._scroll_canvas.winfo_height()
        if content_h > canvas_h:
            self._scroll_vsb.pack(side="right", fill="y", before=self._scroll_canvas)
        else:
            self._scroll_vsb.pack_forget()

    def _toggle_obs(self) -> None:
        if self._obs_collapsed:
            self._obs_box.pack(padx=0, fill="x")
            self._obs_toggle.config(text="▼  Observation — Keystroke Dynamics:")
            self._obs_collapsed = False
        else:
            self._obs_box.pack_forget()
            self._obs_toggle.config(text="▶  Observation — Keystroke Dynamics:")
            self._obs_collapsed = True

    def _clear_obs(self) -> None:
        self._kbd_monitor.obs_log.clear()
        self._obs_box.delete("1.0", tk.END)

    def _clear_alerts(self) -> None:
        """Clear alert box, log, and reset alert_manager so alerts can fire again."""
        self._alert_log.clear()
        self._alert_manager.reset()
        self._alert_box.configure(state="normal", bg="#34495e", fg="#e74c3c")
        self._alert_box.delete("1.0", tk.END)
        self._alert_box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════
    # Focus mode / Listbox
    # ══════════════════════════════════════════════════════════════════════

    def _on_lb_select(self, _event: tk.Event, column: str) -> None:
        lb     = self._lb_left if column == "left" else self._lb_right
        sel    = lb.curselection()
        if not sel:
            return
        half   = (len(self._current_devices) + 1) // 2
        offset = 0 if column == "left" else half
        idx    = sel[0] + offset
        clicked = self._current_devices[idx] if idx < len(self._current_devices) else None
        if clicked:
            self._toggle_focus(clicked)

    def _toggle_focus(self, device: str) -> None:
        if self._focused_usb == device:
            # Deselect → return to WATCH mode
            self._focused_usb = None
            self._kbd_monitor.clear_focus()
            self._lb_left.selection_clear(0, tk.END)
            self._lb_right.selection_clear(0, tk.END)
            self._mode_label.config(text=" WATCH ", bg="#00bcd4", fg="#2c3e50")
        else:
            # Select → FOCUS mode
            self._focused_usb = device
            self._kbd_monitor.set_focus(device)
            self._mode_label.config(text=f" FOCUS: {device} ", bg="#f39c12", fg="#2c3e50")

    def _refresh_listbox(self, devices: list[str]) -> None:
        self._all_devices     = devices
        self._current_devices = devices
        self._detected_label.config(
            text=f"Detected USB Devices: ({len(devices)})"
        )
        self._apply_search()

    def _apply_search(self) -> None:
        """Filter the listboxes by the current search term."""
        term    = self._search_var.get().lower()
        devices = [
            d for d in getattr(self, "_all_devices", self._current_devices)
            if term in d.lower()
        ] if term else getattr(self, "_all_devices", self._current_devices)

        self._current_devices = devices
        half  = (len(devices) + 1) // 2
        left  = devices[:half]
        right = devices[half:]

        for lb, items in ((self._lb_left, left), (self._lb_right, right)):
            lb.delete(0, tk.END)
            for dev in items:
                lb.insert(tk.END, dev)

        if self._focused_usb:
            if self._focused_usb in devices:
                if self._focused_usb in left:
                    self._lb_left.selection_set(left.index(self._focused_usb))
                    self._lb_right.selection_clear(0, tk.END)
                else:
                    self._lb_right.selection_set(right.index(self._focused_usb))
                    self._lb_left.selection_clear(0, tk.END)
            else:
                # Focused device disconnected — return to WATCH
                self._focused_usb = None
                self._kbd_monitor.clear_focus()
                self._mode_label.config(text=" WATCH ", bg="#00bcd4", fg="#2c3e50")

    # ══════════════════════════════════════════════════════════════════════
    # Business-logic callbacks
    # ══════════════════════════════════════════════════════════════════════

    def _on_observation(self, line: str) -> None:
        """Called by KeyboardMonitor with a new observation log entry."""
        self._obs_box.insert(tk.END, line + "\n")
        self._obs_box.see(tk.END)

    def _on_alert(self, msg: str) -> None:
        """Called by KeyboardMonitor when a suspicious pattern is detected."""
        dev_key = self._kbd_monitor.active_kbd_vidpid or self._kbd_monitor.active_kbd_id

        if not self._alert_manager.try_fire(dev_key, msg):
            return  # Duplicate alert — suppress

        # Flag device as suspicious in TrustManager
        self._trust_manager.mark_suspicious(self._kbd_monitor.active_kbd_id)

        # ── ACTIVE BLOCK (keyboard fuzzer) ──────────────────────────────────
        if self._block_active:
            active_label = self._kbd_monitor.active_kbd_id
            if active_label not in self._fuzzer.active_labels:
                self._fuzzer.start(active_label)
                notice = (
                        f"[FUZZING] {active_label} — injecting noise "
                        f"every {FUZZER_INTERVAL}s for {FUZZER_DURATION}s"
                    )
                self._alert_log.append(notice)
                self.root.after(0, lambda n=notice: self._append_alert(n, blocked=True))

        ts   = time.strftime("%H:%M:%S")
        line = f"[{ts}] [{dev_key}] ALERT: {msg}"
        self._alert_log.append(line)
        self._append_alert(line)

    def _append_alert(self, line: str, blocked: bool = False) -> None:
        """Thread-safe helper to write a line to the alert box."""
        self._alert_box.configure(state="normal")
        self._alert_box.insert(tk.END, line + "\n")
        self._alert_box.see(tk.END)
        self._alert_box.configure(state="disabled")

        if not blocked:
            self._alert_box.configure(bg="#c0392b", fg="#ecf0f1")
            self.root.after(
                ALERT_COOLDOWN * 1000,
                lambda: self._alert_box.configure(bg="#34495e", fg="#e74c3c"),
            )

    # ══════════════════════════════════════════════════════════════════════
    # Hardware polling loop
    # ══════════════════════════════════════════════════════════════════════

    def _hardware_loop(self) -> None:
        while not self._stop:
            try:
                self._kbd_monitor.refresh_active_keyboard()
                devices = self._usb_monitor.enumerate()

                alerted = {
                    dev for dev in devices
                    if self._alert_manager.has_any_alert(dev)
                }
                self._trust_manager.evaluate(devices, alerted)

                self.root.after(0, lambda d=devices: self._refresh_listbox(d))
                self.root.after(0, self._refresh_trusted)
            except Exception:
                pass
            time.sleep(3)

    def _refresh_trusted(self) -> None:
        content = "\n".join(self._trust_manager.summary_lines())
        self._trusted_box.configure(state="normal")
        self._trusted_box.delete("1.0", tk.END)
        self._trusted_box.insert(tk.END, content)
        self._trusted_box.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════
    # ACTIVE BLOCK toggle (placeholder)
    # ══════════════════════════════════════════════════════════════════════

    def _toggle_block(self) -> None:
        """Toggle ACTIVE BLOCK (keyboard fuzzer) on/off."""
        self._block_active = not self._block_active
        if self._block_active:
            self._block_btn.config(text="ACTIVE BLOCK: ON",
                                   bg="#27ae60", activebackground="#1e8449")
        else:
            self._fuzzer.stop_all()
            self._block_btn.config(text="ACTIVE BLOCK: OFF",
                                   bg="#7f8c8d", activebackground="#616a6b")

    # ══════════════════════════════════════════════════════════════════════
    # Help popup
    # ══════════════════════════════════════════════════════════════════════

    def _show_help(self) -> None:
        """Open a compact, scrollable help dialog."""
        win = tk.Toplevel(self.root)
        win.title("How it works")
        win.geometry("540x360")
        win.configure(bg="#2c3e50")
        win.resizable(True, True)
        win.grab_set()  # modal

        # Scrollable text area
        frame = tk.Frame(win, bg="#2c3e50")
        frame.pack(fill="both", expand=True, padx=12, pady=(12, 4))

        sb = tk.Scrollbar(frame, orient="vertical")
        txt = tk.Text(
            frame,
            wrap="word",
            font=("Consolas", 10),
            bg="#34495e", fg="#ecf0f1",
            relief="flat", bd=0,
            yscrollcommand=sb.set,
            cursor="arrow",
            state="normal",
        )
        sb.config(command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        # Text tags for formatting
        txt.tag_configure("heading",
            font=("Consolas", 11, "bold"), foreground="#00bcd4",
            spacing1=8, spacing3=2)
        txt.tag_configure("body",
            font=("Consolas", 10), foreground="#ecf0f1",
            lmargin1=12, lmargin2=12, spacing3=1)
        txt.tag_configure("sep",
            font=("Consolas", 6), foreground="#7f8c8d")

        # Content blocks: (tag, text)
        blocks = [
            ("heading", "WATCH mode (default)"),
            ("body",    "Monitors all USB devices and logs global keystroke dynamics.\n"),
            ("heading", "FOCUS mode"),
            ("body",    "Click a device in the list to focus on it.\n"
                         "Keystroke analysis and alerts apply only to that device.\n"
                         "Click it again to return to WATCH mode.\n"),
            ("heading", "Trusted USB Devices"),
            ("body",    f"A device is trusted after {TRUSTED_TEST_DURATION}s with no alerts.\n"),
            ("heading", "Critical Alerts"),
            ("body",    f"Fires when speed > {MAX_HUMAN_KPS} CPS or jitter < {LOW_JITTER_THRESHOLD}s.\n"
                         f"Requires {CONSECUTIVE_FAST_THRESHOLD} consecutive fast IKIs.\n"
                         "Each alert type fires only once per device per session.\n"),
            ("heading", "Observation — Keystroke Dynamics"),
            ("body",    "Logs TTFK, speed (CPS) and jitter for the active keyboard.\n"
                         "Use the Clear button to reset the log.\n"),
            ("heading", "Save Report"),
            ("body",    "Exports Markdown to your Desktop (or Home) with all session data.\n"),
        ]
        for tag, text in blocks:
            txt.insert(tk.END, text + "\n", tag)

        txt.configure(state="disabled")
        txt.yview_moveto(0)

        # Close button
        tk.Button(
            win, text="Close",
            bg="#2980b9", fg="#ecf0f1",
            activebackground="#1a5276", activeforeground="#ecf0f1",
            font=("Consolas", 10, "bold"),
            relief="flat", cursor="hand2", pady=4,
            command=win.destroy,
        ).pack(fill="x", padx=12, pady=(4, 10))

    # ══════════════════════════════════════════════════════════════════════
    # Save report
    # ══════════════════════════════════════════════════════════════════════

    def _save_results(self) -> None:
        filepath = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt"), ("All files", "*.*")],
            title="Save analysis report",
            initialdir=str(_default_save_dir()),
            initialfile=f"badusb_report_{time.strftime('%Y%m%d_%H%M%S')}.md",
        )
        if not filepath:
            return

        content = generate_report(
            os_type=OS_TYPE,
            focused_usb=self._focused_usb,
            devices=self._current_devices,
            trusted=self._trust_manager.trusted,
            alert_log=self._alert_log,
            obs_log=self._kbd_monitor.obs_log,
        )
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
