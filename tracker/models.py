from dataclasses import dataclass
from datetime import datetime


@dataclass
class WindowEvent:
    app_name: str
    window_title: str
    started_at: datetime
    duration_seconds: int
