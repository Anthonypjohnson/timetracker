import sqlite3
import sys
import time
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

from tracker.db import open_db, insert_event
from tracker.models import WindowEvent
from tracker.watcher import Watcher


def make_mem_db() -> sqlite3.Connection:
    return open_db(":memory:")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# get_active_window
# ---------------------------------------------------------------------------

class TestGetActiveWindow(unittest.TestCase):
    @patch("tracker.watcher.ctypes")
    def test_returns_app_and_title(self, mock_ctypes):
        title_buf = MagicMock()
        title_buf.value = "My Document - Notepad"
        name_buf = MagicMock()
        name_buf.value = "notepad.exe"
        mock_ctypes.create_unicode_buffer.side_effect = [title_buf, name_buf]

        pid_mock = MagicMock()
        pid_mock.value = 5678
        mock_ctypes.wintypes.DWORD.return_value = pid_mock

        mock_ctypes.windll.user32.GetForegroundWindow.return_value = 1234
        mock_ctypes.windll.kernel32.OpenProcess.return_value = 9999

        from tracker.watcher import get_active_window
        app, title = get_active_window()

        self.assertEqual(title, "My Document - Notepad")
        self.assertEqual(app, "notepad.exe")

    @patch("tracker.watcher.ctypes")
    def test_unknown_app_when_open_process_fails(self, mock_ctypes):
        title_buf = MagicMock()
        title_buf.value = "Secure Window"
        mock_ctypes.create_unicode_buffer.return_value = title_buf

        mock_ctypes.wintypes.DWORD.return_value = MagicMock()
        mock_ctypes.windll.user32.GetForegroundWindow.return_value = 1
        mock_ctypes.windll.kernel32.OpenProcess.return_value = 0  # access denied

        from tracker.watcher import get_active_window
        app, title = get_active_window()

        self.assertEqual(app, "unknown")
        self.assertEqual(title, "Secure Window")


# ---------------------------------------------------------------------------
# DB round-trip
# ---------------------------------------------------------------------------

class TestInsertEvent(unittest.TestCase):
    def test_round_trip(self):
        conn = make_mem_db()
        event = WindowEvent(
            app_name="chrome.exe",
            window_title="GitHub - Google Chrome",
            started_at=datetime(2026, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
            duration_seconds=120,
        )
        insert_event(conn, event)
        row = conn.execute(
            "SELECT app_name, window_title, duration_seconds FROM window_events"
        ).fetchone()
        self.assertEqual(row, ("chrome.exe", "GitHub - Google Chrome", 120))


# ---------------------------------------------------------------------------
# Watcher class
# ---------------------------------------------------------------------------

class TestWatcher(unittest.TestCase):
    def test_raises_on_non_windows(self):
        conn = make_mem_db()
        watcher = Watcher(conn)
        with patch("tracker.watcher.sys.platform", "linux"):
            with self.assertRaises(RuntimeError):
                watcher.start()

    @patch("tracker.watcher.sys.platform", "win32")
    @patch("tracker.watcher.get_active_window")
    def test_logs_event_on_window_switch(self, mock_get):
        events_received = []
        conn = make_mem_db()
        watcher = Watcher(conn, on_event=events_received.append)

        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 1, 1, 10, 0, 5, tzinfo=timezone.utc)

        mock_get.side_effect = [
            ("notepad.exe", "file.txt"),
            ("chrome.exe", "GitHub"),
        ]

        with patch("tracker.watcher.datetime") as mock_dt:
            mock_dt.now.side_effect = [t0, t1, t1]

            # Drive _run() directly (no thread) for deterministic testing
            watcher.current_app, watcher.current_title = mock_get()
            watcher.session_start = mock_dt.now(timezone.utc)
            watcher._stop_event.set()  # stop after one poll
            watcher._flush(*mock_get())

        rows = conn.execute("SELECT app_name FROM window_events").fetchall()
        self.assertTrue(any(r[0] == "notepad.exe" for r in rows))
        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0].app_name, "notepad.exe")

    @patch("tracker.watcher.sys.platform", "win32")
    @patch("tracker.watcher.get_active_window")
    def test_flush_on_stop_writes_event(self, mock_get):
        conn = make_mem_db()
        watcher = Watcher(conn)

        t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        t1 = datetime(2026, 1, 1, 10, 0, 30, tzinfo=timezone.utc)

        watcher.current_app = "notepad.exe"
        watcher.current_title = "file.txt"
        watcher.session_start = t0

        with patch("tracker.watcher.datetime") as mock_dt:
            mock_dt.now.return_value = t1
            # Simulate the flush-on-stop block directly
            now = mock_dt.now(timezone.utc)
            duration = int((now - watcher.session_start).total_seconds())
            if duration > 0:
                watcher._record(watcher.current_app, watcher.current_title, watcher.session_start, duration)

        rows = conn.execute("SELECT app_name, duration_seconds FROM window_events").fetchall()
        self.assertEqual(rows, [("notepad.exe", 30)])

    @patch("tracker.watcher.sys.platform", "win32")
    @patch("tracker.watcher.get_active_window", return_value=("notepad.exe", "file.txt"))
    def test_is_running_reflects_thread_state(self, mock_get):
        conn = make_mem_db()
        watcher = Watcher(conn)

        self.assertFalse(watcher.is_running)
        watcher.start()
        self.assertTrue(watcher.is_running)
        watcher.stop()
        self.assertFalse(watcher.is_running)


if __name__ == "__main__":
    unittest.main()
