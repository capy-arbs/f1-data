"""Database connection management."""

import sqlite3
from contextlib import contextmanager

from config import DB_PATH


@contextmanager
def get_db():
    """Yield a SQLite connection with row factory set to sqlite3.Row."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
