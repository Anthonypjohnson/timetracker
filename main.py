import logging
import sys
from pathlib import Path

from tracker.db import open_db
from tracker.app import launch

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DB_PATH = Path(__file__).parent / "timetracker.db"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, stream=sys.stdout)
    conn = open_db(DB_PATH)
    try:
        launch(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
