"""SQLite connection management for the NYC 311 weather project."""

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "nyc311_weather.db"


def connect(
    db_path: str | Path | None = None,
) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key checks enabled."""

    database = str(DEFAULT_DB_PATH if db_path is None else db_path)

    if database != ":memory:":
        path = Path(database).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        database = str(path)

    connection = sqlite3.connect(database, timeout=60.0)

    try:
        # Enable foreign-key enforcement immediately after connecting.
        connection.execute("PRAGMA foreign_keys = ON")

        enabled = connection.execute(
            "PRAGMA foreign_keys"
        ).fetchone()

        if enabled is None or enabled[0] != 1:
            raise RuntimeError(
                "SQLite foreign-key enforcement could not be enabled."
            )

        connection.execute("PRAGMA busy_timeout = 60000")
        connection.row_factory = sqlite3.Row

        return connection

    except Exception:
        connection.close()
        raise
