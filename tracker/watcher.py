import ctypes
import ctypes.wintypes
import sqlite3
import sys
import threading
import logging
from datetime import datetime, timezone
from typing import Callable

from tracker.db import insert_event, auto_categorize_event
from tracker.models import WindowEvent

logger = logging.getLogger(__name__)

POLL_INTERVAL = 3.0  # seconds

_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010

# Sentinel values used when the screen is locked
LOCK_APP = "[Screen Lock]"
LOCK_TITLE = "Screen Locked"


def _is_screen_locked() -> bool:
    """
    Return True when the Windows workstation is locked.

    Uses OpenInputDesktop: when the workstation is locked the input desktop
    switches to the Winlogon desktop, which regular processes cannot open
    with DESKTOP_SWITCHDESKTOP rights, so the call returns NULL.
    Always returns False on non-Windows platforms.
    """
    if sys.platform != "win32":
        return False
    _DESKTOP_SWITCHDESKTOP = 0x0100
    hdesk = ctypes.windll.user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if hdesk:
        ctypes.windll.user32.CloseDesktop(hdesk)
        return False
    return True


def get_active_window() -> tuple[str, str]:
    """Return (app_name, window_title) for the current foreground window."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    hwnd = user32.GetForegroundWindow()

    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    title = title_buf.value

    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    handle = kernel32.OpenProcess(
        _PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, pid
    )
    if handle:
        name_buf = ctypes.create_unicode_buffer(512)
        psapi.GetModuleBaseNameW(handle, None, name_buf, 512)
        kernel32.CloseHandle(handle)
        app_name = name_buf.value or "unknown"
    else:
        app_name = "unknown"

    return app_name, title


class Watcher:
    """
    Background thread that polls the active window every POLL_INTERVAL seconds
    and logs focus durations to the database.

    on_event is called (from the watcher thread) each time an event is written.
    Schedule any GUI updates with root.after(0, ...) inside that callback.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        on_event: Callable[[WindowEvent], None] | None = None,
    ) -> None:
        self._conn = conn
        self._on_event = on_event
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Exposed for live display — reads are safe under the GIL
        self.current_app: str = ""
        self.current_title: str = ""
        self.session_start: datetime | None = None

    def start(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("timetracker only runs on Windows.")
        if self.is_running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=POLL_INTERVAL + 2)

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _current_window(self) -> tuple[str, str]:
        """Return (app, title), substituting lock-screen sentinels when locked."""
        if _is_screen_locked():
            return LOCK_APP, LOCK_TITLE
        return get_active_window()

    def _run(self) -> None:
        self.current_app, self.current_title = self._current_window()
        self.session_start = datetime.now(timezone.utc)
        logger.info("Tracker started.")

        while not self._stop_event.wait(timeout=POLL_INTERVAL):
            app, title = self._current_window()
            if (app, title) != (self.current_app, self.current_title):
                self._flush(app, title)

        # Flush in-progress session on stop
        if self.session_start:
            now = datetime.now(timezone.utc)
            duration = int((now - self.session_start).total_seconds())
            if duration > 0:
                self._record(self.current_app, self.current_title, self.session_start, duration)

        logger.info("Tracker stopped.")

    def _flush(self, new_app: str, new_title: str) -> None:
        now = datetime.now(timezone.utc)
        duration = int((now - self.session_start).total_seconds())
        self._record(self.current_app, self.current_title, self.session_start, duration)
        self.current_app = new_app
        self.current_title = new_title
        self.session_start = now

    def _record(self, app: str, title: str, started_at: datetime, duration: int) -> None:
        event = WindowEvent(
            app_name=app,
            window_title=title,
            started_at=started_at,
            duration_seconds=duration,
        )
        event_id = insert_event(self._conn, event)
        auto_categorize_event(self._conn, event_id, app, title)
        logger.debug("Logged: %s — %s (%ds)", app, title, duration)
        if self._on_event:
            self._on_event(event)
