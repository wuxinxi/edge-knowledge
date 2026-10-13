"""Durable device-local transcript snapshots. No conversation text is logged."""

import json
import os
import sqlite3
from pathlib import Path

from edge_knowledge.domain.models import AppError


class SQLiteConversationStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS state "
                "(id INTEGER PRIMARY KEY, revision INTEGER, value TEXT)"
            )
            db.execute("CREATE TABLE IF NOT EXISTS deleted (id TEXT PRIMARY KEY, value TEXT)")
        os.chmod(path, 0o600)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.execute("PRAGMA synchronous=FULL")
        return db

    def read(self) -> dict:
        with self._connect() as db:
            row = db.execute("SELECT revision,value FROM state WHERE id=1").fetchone()
        if row is None:
            return {"initialized": False, "revision": 0, "version": 1, "sessions": [], "active": {}}
        return {"initialized": True, "revision": row[0], **json.loads(row[1])}

    def write(self, value: dict, revision: int) -> int:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT revision,value FROM state WHERE id=1").fetchone()
            actual = row[0] if row else 0
            if actual != revision:
                raise AppError(
                    "会话已在另一窗口更新，请重新加载会话后再保存。", 409, "chat_conflict"
                )
            previous = json.loads(row[1]) if row else {"sessions": []}
            current = {chat["id"] for chat in value["sessions"]}
            for chat in previous["sessions"]:
                if chat["id"] not in current:
                    db.execute(
                        "INSERT OR REPLACE INTO deleted VALUES (?,?)",
                        (chat["id"], json.dumps(chat, ensure_ascii=False)),
                    )
            for id in current:
                db.execute("DELETE FROM deleted WHERE id=?", (id,))
            db.execute("INSERT OR REPLACE INTO state VALUES (1,?,?)", (actual + 1, encoded))
        return actual + 1
