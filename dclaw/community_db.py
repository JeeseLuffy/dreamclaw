import sqlite3
import threading
from typing import Any, Iterable


class CommunityDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._initialize_schema()

    def _initialize_schema(self):
        schema_statements = [
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                handle TEXT UNIQUE NOT NULL,
                persona TEXT NOT NULL,
                emotion_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author_type TEXT NOT NULL,
                author_user_id INTEGER,
                ai_account_id INTEGER,
                parent_id INTEGER,
                content_type TEXT NOT NULL,
                body TEXT NOT NULL,
                quality_score REAL NOT NULL DEFAULT 0,
                persona_score REAL NOT NULL DEFAULT 0,
                emotion_score REAL NOT NULL DEFAULT 0,
                day_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(author_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(ai_account_id) REFERENCES ai_accounts(id) ON DELETE CASCADE,
                FOREIGN KEY(parent_id) REFERENCES content(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id INTEGER NOT NULL,
                actor_type TEXT NOT NULL,
                actor_user_id INTEGER,
                ai_account_id INTEGER,
                interaction_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(content_id, actor_type, actor_user_id, ai_account_id, interaction_type),
                FOREIGN KEY(content_id) REFERENCES content(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_quota (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_type TEXT NOT NULL,
                subject_id INTEGER NOT NULL,
                day_key TEXT NOT NULL,
                post_count INTEGER NOT NULL DEFAULT 0,
                comment_count INTEGER NOT NULL DEFAULT 0,
                total_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                UNIQUE(subject_type, subject_id, day_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS thought_trace (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ai_account_id INTEGER NOT NULL,
                phase TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL,
                day_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(ai_account_id) REFERENCES ai_accounts(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS emotion_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ai_account_id INTEGER NOT NULL,
                emotion_json TEXT NOT NULL,
                day_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(ai_account_id) REFERENCES ai_accounts(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS scheduler_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
        ]
        with self._lock:
            for statement in schema_statements:
                self._conn.execute(statement)
            self._conn.commit()

    def execute(self, query: str, params: Iterable[Any] = ()):
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            self._conn.commit()
            return cursor

    def fetchone(self, query: str, params: Iterable[Any] = ()):
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            return cursor.fetchone()

    def fetchall(self, query: str, params: Iterable[Any] = ()):
        with self._lock:
            cursor = self._conn.execute(query, tuple(params))
            return cursor.fetchall()

    def close(self):
        with self._lock:
            self._conn.close()
