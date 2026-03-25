import sqlite3
from pathlib import Path

from tracker.models import WindowEvent

SCHEMA = """
CREATE TABLE IF NOT EXISTS window_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    app_name         TEXT    NOT NULL,
    window_title     TEXT    NOT NULL,
    started_at       TEXT    NOT NULL,
    duration_seconds INTEGER NOT NULL,
    category         TEXT,
    sub_category     TEXT
);
"""

_MIGRATIONS = [
    "ALTER TABLE window_events ADD COLUMN category TEXT;",
    "ALTER TABLE window_events ADD COLUMN sub_category TEXT;",
]


def open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add new columns to existing databases that pre-date the schema update."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(window_events)")}
    for stmt in _MIGRATIONS:
        col = stmt.split("ADD COLUMN")[1].split()[0]
        if col not in existing:
            conn.execute(stmt)
    conn.commit()


def insert_event(conn: sqlite3.Connection, event: WindowEvent) -> None:
    conn.execute(
        "INSERT INTO window_events (app_name, window_title, started_at, duration_seconds) VALUES (?, ?, ?, ?)",
        (
            event.app_name,
            event.window_title,
            event.started_at.isoformat(),
            event.duration_seconds,
        ),
    )
    conn.commit()


def update_event_category(
    conn: sqlite3.Connection,
    event_id: int,
    category: str | None,
    sub_category: str | None,
) -> None:
    conn.execute(
        "UPDATE window_events SET category = ?, sub_category = ? WHERE id = ?",
        (category or None, sub_category or None, event_id),
    )
    conn.commit()


def get_all_events(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        "SELECT id, app_name, window_title, started_at, duration_seconds, category, sub_category "
        "FROM window_events ORDER BY started_at DESC"
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_known_categories(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        "SELECT DISTINCT category FROM window_events WHERE category IS NOT NULL ORDER BY category"
    )
    return [row[0] for row in cur.fetchall()]


def get_known_sub_categories(conn: sqlite3.Connection, category: str | None = None) -> list[str]:
    if category:
        cur = conn.execute(
            "SELECT DISTINCT sub_category FROM window_events "
            "WHERE sub_category IS NOT NULL AND category = ? ORDER BY sub_category",
            (category,),
        )
    else:
        cur = conn.execute(
            "SELECT DISTINCT sub_category FROM window_events "
            "WHERE sub_category IS NOT NULL ORDER BY sub_category"
        )
    return [row[0] for row in cur.fetchall()]


def get_uncategorized_count(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM window_events WHERE category IS NULL"
    ).fetchone()[0]


def get_summary(conn: sqlite3.Connection) -> list[dict]:
    cur = conn.execute(
        """
        SELECT
            COALESCE(category, '(Uncategorized)') AS category,
            COALESCE(sub_category, '')             AS sub_category,
            SUM(duration_seconds)                  AS total_seconds,
            COUNT(*)                               AS event_count
        FROM window_events
        GROUP BY category, sub_category
        ORDER BY total_seconds DESC
        """
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
