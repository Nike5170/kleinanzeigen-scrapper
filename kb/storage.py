import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class Storage:
    """Запоминает уже обработанные объявления, чтобы не постить дубли."""

    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen (
                ad_id TEXT PRIMARY KEY,
                url TEXT,
                title TEXT,
                status TEXT,
                seen_at TEXT
            )
            """
        )
        self.conn.commit()

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0

    def has(self, ad_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM seen WHERE ad_id = ?", (ad_id,)).fetchone() is not None

    def mark(self, ad_id: str, url: str, title: str, status: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO seen VALUES (?, ?, ?, ?, ?)",
            (ad_id, url, title, status, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
