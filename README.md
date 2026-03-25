# timetracker

![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)

A lightweight Windows desktop app that automatically tracks which applications you use and for how long. No manual input required — it runs in the background, logs every foreground window focus event to a local SQLite database, and lets you categorize and review your time through a built-in GUI.

## Features

- **Automatic tracking** — polls the active foreground window every 3 seconds using native Windows APIs (`user32`, `kernel32`, `psapi`) via `ctypes`
- **Local storage** — all data stays on your machine in a single SQLite file (`timetracker.db`)
- **Live view** — shows the current active app, window title, and time in focus
- **Review tab** — browse all recorded events, filter by app/title, and assign categories and sub-categories with a filterable combobox
- **Summary tab** — aggregated time totals grouped by category and sub-category
- **Zero dependencies** — stdlib only (`ctypes`, `sqlite3`, `tkinter`, `logging`)

## Requirements

- Windows 11 (or Windows 10)
- Python 3.11+

## Usage

```bash
python main.py
```

Click **Start Monitoring** to begin tracking. The live panel updates every second. Use the **Review** tab to categorize events and the **Summary** tab to see time totals.

Data is saved to `timetracker.db` in the same directory as `main.py`.

## Project Structure

```
timetracker/
├── tracker/
│   ├── app.py        # Main tkinter GUI (MainApp, StatusBar, ActiveWindowPanel)
│   ├── watcher.py    # Background polling thread (Watcher, get_active_window)
│   ├── db.py         # SQLite schema, queries, and migrations
│   ├── models.py     # WindowEvent dataclass
│   └── review.py     # EventsTab and SummaryTab widgets
├── main.py           # Entry point
└── requirements.txt
```

## Database Schema

Single table `window_events`:

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Primary key |
| `app_name` | TEXT | Process name (e.g. `chrome.exe`) |
| `window_title` | TEXT | Foreground window title |
| `started_at` | TEXT | ISO 8601 timestamp |
| `duration_seconds` | INTEGER | Seconds of focus |
| `category` | TEXT | User-assigned category (nullable) |
| `sub_category` | TEXT | Optional sub-category (nullable) |

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
