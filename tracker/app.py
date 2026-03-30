"""
Main GUI application for timetracker.

Window layout:
  ┌─────────────────────────────────────────────────────┐
  │  ● Monitoring  [Stop Monitoring]                    │  ← status bar
  ├─────────────────────────────────────────────────────┤
  │  Active Window                                      │
  │  App:   chrome.exe                                  │  ← live panel
  │  Title: GitHub – Google Chrome                      │
  │  In focus: 0h 02m 14s                               │
  ├─────────────────────────────────────────────────────┤
  │  [ Review (3 uncategorized) ]  [ Summary ]          │  ← notebook tabs
  │  …                                                  │
  └─────────────────────────────────────────────────────┘
"""

import sqlite3
import sys
import tkinter as tk
from typing import Callable
from tkinter import messagebox, ttk
from datetime import datetime, timezone

from tracker.db import get_uncategorized_count, get_setting, set_setting
from tracker.models import WindowEvent
from tracker.review import EventsTab, SummaryTab, RulesTab, CategoriesTab
from tracker.watcher import Watcher, get_active_window

_LIVE_POLL_MS = 1000  # how often the GUI refreshes the active-window display

# Color palette
_BG = "#f0f2f5"
_SURFACE = "#ffffff"
_ACCENT = "#0078d4"
_ACCENT_DARK = "#005a9e"
_TEXT = "#1a1a1a"
_SUBTEXT = "#6b7280"
_BORDER = "#d1d5db"
_SUCCESS = "#16a34a"
_DANGER = "#dc2626"
_MUTED = "#9ca3af"
_STATUS_BG = "#1e293b"
_STATUS_FG = "#f1f5f9"


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class StatusBar(tk.Frame):
    """Top bar: coloured status dot, label, start/stop toggle, and autostart checkbox."""

    def __init__(
        self,
        parent: tk.Widget,
        on_toggle: Callable,
        autostart_value: bool = False,
        on_autostart_change: Callable | None = None,
    ) -> None:
        super().__init__(parent, bg=_STATUS_BG, padx=12, pady=9)

        self._dot = tk.Label(self, text="●", font=("Segoe UI", 12), fg=_MUTED, bg=_STATUS_BG)
        self._dot.pack(side="left")

        self._label = tk.Label(
            self, text="Stopped", width=12, anchor="w",
            font=("Segoe UI", 9), fg=_STATUS_FG, bg=_STATUS_BG,
        )
        self._label.pack(side="left", padx=(6, 16))

        self._btn = ttk.Button(self, text="Start Monitoring", width=18, command=on_toggle,
                               style="Accent.TButton")
        self._btn.pack(side="left")

        # Autostart checkbox on the right
        self._autostart_var = tk.BooleanVar(value=autostart_value)
        tk.Checkbutton(
            self,
            text="Auto-start on launch",
            variable=self._autostart_var,
            command=on_autostart_change,
            bg=_STATUS_BG, fg=_STATUS_FG,
            selectcolor=_STATUS_BG,
            activebackground=_STATUS_BG, activeforeground=_STATUS_FG,
            font=("Segoe UI", 9),
            borderwidth=0, highlightthickness=0,
        ).pack(side="right", padx=(0, 4))

    @property
    def autostart(self) -> bool:
        return self._autostart_var.get()

    def set_running(self, running: bool) -> None:
        if running:
            self._dot.config(fg=_SUCCESS)
            self._label.config(text="Monitoring")
            self._btn.config(text="Stop Monitoring", style="TButton")
        else:
            self._dot.config(fg=_DANGER)
            self._label.config(text="Stopped")
            self._btn.config(text="Start Monitoring", style="Accent.TButton")


class ActiveWindowPanel(ttk.LabelFrame):
    """Shows the current foreground window and how long it has been in focus."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text="Active Window", padding=(12, 8))
        self._last_key: tuple[str, str] = ("", "")
        self._focus_since: datetime = datetime.now(timezone.utc)

        self._app_var = tk.StringVar(value="—")
        self._title_var = tk.StringVar(value="—")
        self._dur_var = tk.StringVar(value="—")

        row_cfg = {"sticky": "w", "padx": (0, 16), "pady": 2}

        ttk.Label(self, text="App:", width=8, anchor="w").grid(row=0, column=0, **row_cfg)
        ttk.Label(self, textvariable=self._app_var, anchor="w").grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(self, text="Title:", width=8, anchor="w").grid(row=1, column=0, **row_cfg)
        ttk.Label(self, textvariable=self._title_var, anchor="w").grid(row=1, column=1, sticky="w", pady=2)

        ttk.Label(self, text="In focus:", width=8, anchor="w").grid(row=2, column=0, **row_cfg)
        ttk.Label(self, textvariable=self._dur_var, foreground=_SUBTEXT, anchor="w").grid(
            row=2, column=1, sticky="w", pady=2
        )

        self.columnconfigure(1, weight=1)

    def update_display(self) -> None:
        """Poll the OS for the current window and refresh labels. Safe to call from the main thread."""
        if sys.platform != "win32":
            self._app_var.set("(not available on Linux)")
            self._title_var.set("")
            self._dur_var.set("")
            return

        try:
            app, title = get_active_window()
        except Exception:
            return

        key = (app, title)
        if key != self._last_key:
            self._last_key = key
            self._focus_since = datetime.now(timezone.utc)

        elapsed = (datetime.now(timezone.utc) - self._focus_since).total_seconds()
        self._app_var.set(app or "—")
        self._title_var.set(title or "—")
        self._dur_var.set(_fmt_duration(elapsed))


class MainApp(tk.Tk):
    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self.title("timetracker")
        self.geometry("980x700")
        self.minsize(720, 520)

        self._conn = conn
        self._watcher = Watcher(conn, on_event=self._on_event)

        self._setup_theme()
        self._build()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Auto-start monitoring if the setting is enabled
        if sys.platform == "win32" and get_setting(conn, "autostart_monitoring", "0") == "1":
            self._toggle()

    # ------------------------------------------------------------------
    # Theme
    # ------------------------------------------------------------------

    def _setup_theme(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        self.configure(bg=_BG)

        _font = ("Segoe UI", 9)
        _font_bold = ("Segoe UI", 9, "bold")

        # Frame / LabelFrame
        style.configure("TFrame", background=_BG)
        style.configure("TLabelframe", background=_BG, relief="groove",
                        borderwidth=1, bordercolor=_BORDER)
        style.configure("TLabelframe.Label", background=_BG, foreground=_TEXT, font=_font_bold)

        # Label
        style.configure("TLabel", background=_BG, foreground=_TEXT, font=_font)
        style.configure("Subtext.TLabel", foreground=_SUBTEXT)

        # Button — neutral
        style.configure("TButton",
            font=_font, relief="flat", padding=(8, 4),
            background="#e5e7eb", foreground=_TEXT, borderwidth=0,
        )
        style.map("TButton",
            background=[("active", "#d1d5db"), ("pressed", _BORDER), ("disabled", "#f3f4f6")],
            foreground=[("disabled", _MUTED)],
            relief=[("pressed", "flat"), ("!pressed", "flat")],
        )

        # Button — primary accent
        style.configure("Accent.TButton",
            font=_font, relief="flat", padding=(8, 4),
            background=_ACCENT, foreground="#ffffff", borderwidth=0,
        )
        style.map("Accent.TButton",
            background=[("active", _ACCENT_DARK), ("pressed", "#004578")],
            foreground=[("active", "#ffffff"), ("pressed", "#ffffff")],
            relief=[("pressed", "flat"), ("!pressed", "flat")],
        )

        # Button — danger
        style.configure("Danger.TButton",
            font=_font, relief="flat", padding=(8, 4),
            background="#fee2e2", foreground=_DANGER, borderwidth=0,
        )
        style.map("Danger.TButton",
            background=[("active", "#fecaca"), ("pressed", "#fca5a5")],
            foreground=[("active", _DANGER)],
            relief=[("pressed", "flat"), ("!pressed", "flat")],
        )

        # Notebook
        style.configure("TNotebook", background=_BG, borderwidth=0, tabmargins=[0, 4, 0, 0])
        style.configure("TNotebook.Tab",
            font=_font, padding=(14, 7),
            background="#e5e7eb", foreground=_SUBTEXT,
        )
        style.map("TNotebook.Tab",
            background=[("selected", _SURFACE), ("active", "#f3f4f6")],
            foreground=[("selected", _ACCENT), ("active", _TEXT)],
            expand=[("selected", [0, 0, 0, 0])],
        )

        # Treeview
        style.configure("Treeview",
            font=_font, rowheight=26,
            background=_SURFACE, foreground=_TEXT, fieldbackground=_SURFACE,
            borderwidth=0,
        )
        style.configure("Treeview.Heading",
            font=_font_bold, background="#f3f4f6", foreground=_TEXT,
            relief="flat", padding=(6, 5),
        )
        style.map("Treeview",
            background=[("selected", "#dbeafe")],
            foreground=[("selected", _TEXT)],
        )
        style.map("Treeview.Heading",
            background=[("active", "#e5e7eb"), ("pressed", _BORDER)],
            relief=[("pressed", "flat"), ("!pressed", "flat")],
        )

        # Entry / Combobox
        style.configure("TEntry",
            font=_font, padding=(5, 3),
            fieldbackground=_SURFACE, bordercolor=_BORDER,
        )
        style.configure("TCombobox",
            font=_font, padding=(5, 3),
            fieldbackground=_SURFACE, bordercolor=_BORDER,
        )

        # Scrollbar — slim
        style.configure("TScrollbar",
            background=_BORDER, troughcolor=_BG,
            arrowcolor=_SUBTEXT, borderwidth=0, arrowsize=10,
        )
        style.map("TScrollbar",
            background=[("active", _SUBTEXT)],
        )

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        autostart = get_setting(self._conn, "autostart_monitoring", "0") == "1"
        self._status_bar = StatusBar(
            self,
            on_toggle=self._toggle,
            autostart_value=autostart,
            on_autostart_change=self._save_autostart,
        )
        self._status_bar.pack(fill="x")

        self._active_panel = ActiveWindowPanel(self)
        self._active_panel.pack(fill="x", padx=12, pady=(10, 0))

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=12, pady=10)

        self._events_tab = EventsTab(self._notebook, self._conn, on_event_added=self._update_review_tab_label)
        self._summary_tab = SummaryTab(self._notebook, self._conn)
        self._rules_tab = RulesTab(self._notebook, self._conn, on_data_changed=self._on_rules_cats_changed)
        self._categories_tab = CategoriesTab(self._notebook, self._conn, on_data_changed=self._on_rules_cats_changed)

        self._notebook.add(self._events_tab, text="  Review  ")
        self._notebook.add(self._summary_tab, text="  Summary  ")
        self._notebook.add(self._rules_tab, text="  Rules  ")
        self._notebook.add(self._categories_tab, text="  Categories  ")
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._update_review_tab_label()

    # ------------------------------------------------------------------
    # Monitoring toggle
    # ------------------------------------------------------------------

    def _toggle(self) -> None:
        if self._watcher.is_running:
            self._watcher.stop()
            self._status_bar.set_running(False)
        else:
            try:
                self._watcher.start()
                self._status_bar.set_running(True)
            except RuntimeError as exc:
                messagebox.showerror("Cannot start", str(exc))

    # ------------------------------------------------------------------
    # Periodic live update (main thread)
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self._active_panel.update_display()
        self.after(_LIVE_POLL_MS, self._tick)

    # ------------------------------------------------------------------
    # Watcher callback (called from watcher thread — use after() for GUI)
    # ------------------------------------------------------------------

    def _on_event(self, event: WindowEvent) -> None:
        self.after(0, self._on_event_main)

    def _on_event_main(self) -> None:
        self._update_review_tab_label()
        # If Review tab is visible, keep it up to date
        current = self._notebook.tab(self._notebook.select(), "text").strip()
        if current == "Review":
            self._events_tab.refresh()

    # ------------------------------------------------------------------
    # Tab helpers
    # ------------------------------------------------------------------

    def _update_review_tab_label(self) -> None:
        count = get_uncategorized_count(self._conn)
        label = f"  Review ({count} uncategorized)  " if count else "  Review  "
        self._notebook.tab(0, text=label)

    def _save_autostart(self) -> None:
        value = "1" if self._status_bar.autostart else "0"
        set_setting(self._conn, "autostart_monitoring", value)

    def _on_rules_cats_changed(self) -> None:
        """Refresh both Rules and Categories tabs after an import."""
        self._rules_tab.refresh()
        self._categories_tab.refresh()

    def _on_tab_change(self, event=None) -> None:
        tab = self._notebook.tab(self._notebook.select(), "text").strip()
        if "Summary" in tab:
            self._summary_tab.refresh()
        elif "Review" in tab:
            self._events_tab.refresh()
            self._update_review_tab_label()
        elif "Rules" in tab:
            self._rules_tab.refresh()
        elif "Categories" in tab:
            self._categories_tab.refresh()

    # ------------------------------------------------------------------
    # Clean shutdown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._watcher.is_running:
            self._watcher.stop()
        self.destroy()


def launch(conn: sqlite3.Connection) -> None:
    app = MainApp(conn)
    app.mainloop()
