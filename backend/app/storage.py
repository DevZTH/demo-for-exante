from __future__ import annotations

import json
import sqlite3
import struct
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.app.domain import MessageRecord, ScenarioRecord, SemanticMatch
from backend.settings import Settings


class ScenarioNotFoundError(LookupError):
    """Raised when a requested scenario does not exist."""


class ChatRepository:
    def __init__(self, settings: Settings) -> None:
        self.db_path = settings.sqlite_path
        self.storage_mode = settings.chat_storage_mode
        self.embedding_dimensions = settings.embedding_dimensions

    @property
    def vector_enabled(self) -> bool:
        return self.storage_mode == "sqlite_vec"

    def init_db(self) -> None:
        if self.db_path != Path(":memory:"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    embedding_indexed INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_chat_id_id
                ON messages(chat_id, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chats_updated_at
                ON chats(updated_at DESC)
                """
            )
            if self.vector_enabled:
                conn.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS message_vectors
                    USING vec0(embedding float[{self.embedding_dimensions}])
                    """
                )

            conn.commit()

    def create_scenario(
        self,
        title: str | None = None,
        scenario_id: str | None = None,
    ) -> ScenarioRecord:
        now = self._now()
        scenario_id = scenario_id or str(uuid.uuid4())

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chats (id, title, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (scenario_id, title, now, now),
            )
            conn.commit()

        scenario = self.get_scenario(scenario_id)
        if scenario is None:
            raise RuntimeError("Scenario was not created")
        return scenario

    def require_scenario(self, scenario_id: str) -> ScenarioRecord:
        scenario = self.get_scenario(scenario_id)
        if scenario is None:
            raise ScenarioNotFoundError(scenario_id)
        return scenario

    def get_scenario(self, scenario_id: str) -> ScenarioRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM chats
                WHERE id = ?
                """,
                (scenario_id,),
            ).fetchone()

        return self._scenario_from_row(row) if row else None

    def list_scenarios(self, limit: int = 50) -> list[ScenarioRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, created_at, updated_at
                FROM chats
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [self._scenario_from_row(row) for row in rows]

    def delete_scenario(self, scenario_id: str) -> bool:
        with self._connect() as conn:
            self._delete_vectors_for_chat(conn, scenario_id)

            cursor = conn.execute("DELETE FROM chats WHERE id = ?", (scenario_id,))
            conn.commit()

        return cursor.rowcount > 0

    def clear_messages(self, chat_id: str) -> int:
        now = self._now()

        with self._connect() as conn:
            self._delete_vectors_for_chat(conn, chat_id)

            cursor = conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (now, chat_id),
            )
            conn.commit()

        return cursor.rowcount

    def add_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
    ) -> MessageRecord:
        now = self._now()
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO messages (chat_id, role, content, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, role, content, now, metadata_json),
            )
            message_id = int(cursor.lastrowid)

            if self.vector_enabled and embedding is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO message_vectors(rowid, embedding) VALUES (?, ?)",
                    (message_id, self._serialize_vector(embedding)),
                )
                conn.execute(
                    "UPDATE messages SET embedding_indexed = 1 WHERE id = ?",
                    (message_id,),
                )

            conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (now, chat_id),
            )
            conn.commit()

        message = self.get_message(message_id)
        if message is None:
            raise RuntimeError("Message was not created")
        return message

    def get_message(self, message_id: int) -> MessageRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, chat_id, role, content, created_at, metadata_json
                FROM messages
                WHERE id = ?
                """,
                (message_id,),
            ).fetchone()

        return self._message_from_row(row) if row else None

    def list_messages(self, chat_id: str, limit: int | None = None) -> list[MessageRecord]:
        with self._connect() as conn:
            if limit is None:
                rows = conn.execute(
                    """
                    SELECT id, chat_id, role, content, created_at, metadata_json
                    FROM messages
                    WHERE chat_id = ?
                    ORDER BY id ASC
                    """,
                    (chat_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, chat_id, role, content, created_at, metadata_json
                    FROM messages
                    WHERE chat_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (chat_id, limit),
                ).fetchall()
                rows = list(reversed(rows))

        return [self._message_from_row(row) for row in rows]

    def search_similar_messages(
        self,
        chat_id: str,
        embedding: list[float],
        *,
        limit: int,
    ) -> list[SemanticMatch]:
        if not self.vector_enabled or limit <= 0:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    m.id,
                    m.chat_id,
                    m.role,
                    m.content,
                    m.created_at,
                    m.metadata_json,
                    v.distance
                FROM message_vectors AS v
                JOIN messages AS m ON m.id = v.rowid
                WHERE v.embedding MATCH ?
                  AND k = ?
                  AND m.chat_id = ?
                  AND m.role IN ('user', 'assistant')
                ORDER BY v.distance
                LIMIT ?
                """,
                (self._serialize_vector(embedding), limit, chat_id, limit),
            ).fetchall()

        return [
            SemanticMatch(message=self._message_from_row(row), distance=float(row["distance"]))
            for row in rows
        ]

    def health(self) -> dict[str, Any]:
        with self._connect() as conn:
            sqlite_version = conn.execute("SELECT sqlite_version()").fetchone()[0]
            sqlite_vec_version = None
            if self.vector_enabled:
                sqlite_vec_version = conn.execute("SELECT vec_version()").fetchone()[0]

        return {
            "sqlite": sqlite_version,
            "sqlite_vec": sqlite_vec_version,
            "storage_mode": self.storage_mode,
            "db_path": str(self.db_path),
        }

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

        if self.vector_enabled:
            self._load_sqlite_vec(conn)

        try:
            yield conn
        finally:
            conn.close()

    def _load_sqlite_vec(self, conn: sqlite3.Connection) -> None:
        try:
            import sqlite_vec
        except ImportError as exc:
            raise RuntimeError(
                "Install sqlite-vec or set CHAT_CHAT_STORAGE_MODE=sqlite"
            ) from exc

        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)

    def _delete_vectors_for_chat(self, conn: sqlite3.Connection, chat_id: str) -> None:
        if not self.vector_enabled:
            return

        message_ids = conn.execute(
            "SELECT id FROM messages WHERE chat_id = ?",
            (chat_id,),
        ).fetchall()
        for row in message_ids:
            conn.execute("DELETE FROM message_vectors WHERE rowid = ?", (row["id"],))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_dt(value: str) -> datetime:
        return datetime.fromisoformat(value)

    @staticmethod
    def _serialize_vector(vector: list[float]) -> bytes:
        return struct.pack(f"{len(vector)}f", *vector)

    def _scenario_from_row(self, row: sqlite3.Row) -> ScenarioRecord:
        return ScenarioRecord(
            id=row["id"],
            title=row["title"],
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
        )

    def _message_from_row(self, row: sqlite3.Row) -> MessageRecord:
        return MessageRecord(
            id=int(row["id"]),
            chat_id=row["chat_id"],
            role=row["role"],
            content=row["content"],
            created_at=self._parse_dt(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
