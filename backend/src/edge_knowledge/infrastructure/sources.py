"""Per-model source ownership. Absolute authorized paths remain in the desktop host."""

import os
import sqlite3
from pathlib import Path

from edge_knowledge.domain.folders import SourceFile


class SQLiteSourceStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = path
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS source_files (library TEXT, source TEXT, path TEXT, "
                "fingerprint TEXT, document_id TEXT, PRIMARY KEY(library, source, path))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sync_epochs (library TEXT PRIMARY KEY, epoch INTEGER)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sync_enabled "
                "(library TEXT, source TEXT, epoch INTEGER, "
                "PRIMARY KEY(library, source))"
            )
        os.chmod(path, 0o600)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def lease(self, library: str, source: str) -> tuple[int, bool]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT epoch FROM sync_epochs WHERE library=?", (library,)
            ).fetchone()
            epoch = row[0] if row else 0
            enabled = connection.execute(
                "SELECT epoch FROM sync_enabled WHERE library=? AND source=?", (library, source)
            ).fetchone()
            return epoch, epoch == 0 or bool(enabled and enabled[0] == epoch)

    def activate(self, library: str, source: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT epoch FROM sync_epochs WHERE library=?", (library,)
            ).fetchone()
            connection.execute(
                "INSERT OR REPLACE INTO sync_enabled VALUES (?, ?, ?)",
                (library, source, row[0] if row else 0),
            )

    def suspend_library(self, library: str) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT epoch FROM sync_epochs WHERE library=?", (library,)
            ).fetchone()
            connection.execute(
                "INSERT OR REPLACE INTO sync_epochs VALUES (?, ?)",
                (library, (row[0] if row else 0) + 1),
            )
            connection.execute("DELETE FROM sync_enabled WHERE library=?", (library,))

    def files(self, library: str, source: str) -> list[SourceFile]:
        with self._connect() as connection:
            return [
                SourceFile(*row)
                for row in connection.execute(
                    "SELECT path, fingerprint, document_id FROM source_files "
                    "WHERE library=? AND source=? ORDER BY path",
                    (library, source),
                )
            ]

    def paths(self, library: str) -> dict[str, str]:
        with self._connect() as connection:
            return dict(
                connection.execute(
                    "SELECT document_id, path FROM source_files WHERE library=? ORDER BY path",
                    (library,),
                )
            )

    def get(self, library: str, source: str, path: str) -> SourceFile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT path, fingerprint, document_id FROM source_files "
                "WHERE library=? AND source=? AND path=?",
                (library, source, path),
            ).fetchone()
            return SourceFile(*row) if row else None

    def put(self, library: str, source: str, entry: SourceFile) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO source_files VALUES (?, ?, ?, ?, ?)",
                (library, source, entry.path, entry.fingerprint, entry.document_id),
            )

    def remove(self, library: str, source: str, path: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM source_files WHERE library=? AND source=? AND path=?",
                (library, source, path),
            )
