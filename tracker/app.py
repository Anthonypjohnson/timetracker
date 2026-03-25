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
from tkinter import messagebox, ttk
from datetime import datetime, timezone

from tracker.db import get_uncategorized_count
from tracker.models import WindowEvent
from tracker.review import EventsTab, SummaryTab, RulesTab, CategoriesTab
from tracker.watcher import Watcher, get_active_window

_LIVE_POLL_MS = 1000  # how often the GUI refreshes the active-window display


def _fmt_duration(seconds: int) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class StatusBar(tk.Frame):
    """Top bar: coloured status dot, label, and start/stop toggle button."""

    def __init__(self, parent: tk.Widget, on_toggle: callable) -> None:
        super().__init__(parent, padx=10, pady=6)
        self.configure(relief="groove", bd=1)

        self._dot = tk.Label(self, text="●", font=("TkDefaultFont", 14), fg="#999999")
        self._dot.pack(side="left")

        self._label = tk.Label(self, text="Stopped", width=12, anchor="w")
        self._label.pack(side="left", padx=(4, 16))

        self._btn = tk.Button(self, text="Start Monitoring", width=18, command=on_toggle)
        self._btn.pack(side="left")

    def set_running(self, running: bool) -> None:
        if running:
            self._dot.config(fg="#22bb44")
            self._label.config(text="Monitoring")
            self._btn.config(text="Stop Monitoring")
        else:
            self._dot.config(fg="#cc3333")
            self._label.config(text="Stopped")
            self._btn.config(text="Start Monitoring")


class ActiveWindowPanel(tk.LabelFrame):
    """Shows the current foreground window and how long it has been in focus."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text="Active Window", padx=10, pady=6)
        self._last_key: tuple[str, str] = ("", "")
        self._focus_since: datetime = datetime.now(timezone.utc)

        self._app_var = tk.StringVar(value="—")
        self._title_var = tk.StringVar(value="—")
        self._dur_var = tk.StringVar(value="—")

        row_cfg = {"sticky": "w", "padx": (0, 16)}

        tk.Label(self, text="App:", width=7, anchor="w").grid(row=0, column=0, **row_cfg)
        tk.Label(self, textvariable=self._app_var, anchor="w").grid(row=0, column=1, sticky="w")

        tk.Label(self, text="Title:", width=7, anchor="w").grid(row=1, column=0, **row_cfg)
        tk.Label(self, textvariable=self._title_var, anchor="w").grid(row=1, column=1, sticky="w")

        tk.Label(self, text="In focus:", width=7, anchor="w").grid(row=2, column=0, **row_cfg)
        tk.Label(self, textvariable=self._dur_var, fg="#555555", anchor="w").grid(row=2, column=1, sticky="w")

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

        self._build()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._status_bar = StatusBar(self, on_toggle=self._toggle)
        self._status_bar.pack(fill="x", padx=4, pady=(4, 0))

        self._active_panel = ActiveWindowPanel(self)
        self._active_panel.pack(fill="x", padx=8, pady=(8, 0))

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self._events_tab = EventsTab(self._notebook, self._conn)
        self._summary_tab = SummaryTab(self._notebook, self._conn)
        self._rules_tab = RulesTab(self._notebook, self._conn)
        self._categories_tab = CategoriesTab(self._notebook, self._conn)

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
