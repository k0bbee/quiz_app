"""Rebuildable SQLite metadata index for the JSON question store."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Callable, Iterable


SCHEMA_VERSION = "2"
INDEX_FILENAME = ".question_index.sqlite3"


class QuestionIndex:
    """Index question metadata while keeping JSON files authoritative."""

    def __init__(self, questions_dir: str):
        self.questions_dir = Path(questions_dir)
        self.path = self.questions_dir.parent / INDEX_FILENAME

    def ensure_current(
        self,
        loader: Callable[[str], dict | None],
    ) -> None:
        """Rebuild when the indexed JSON file signature no longer matches disk."""

        def operation(connection: sqlite3.Connection) -> None:
            directory_marker = self._directory_marker()
            stored_marker = connection.execute(
                "SELECT value FROM metadata WHERE key = 'directory_marker'"
            ).fetchone()
            if stored_marker is not None and str(stored_marker[0]) == directory_marker:
                return
            signature = self._directory_signature()
            indexed_signature = tuple(
                (str(row[0]), int(row[1]), int(row[2]))
                for row in connection.execute(
                    "SELECT file_name, mtime_ns, file_size FROM files ORDER BY file_name"
                )
            )
            if indexed_signature == signature:
                with connection:
                    self._set_directory_marker(connection, directory_marker)
                return
            with connection:
                connection.execute("DELETE FROM questions")
                connection.execute("DELETE FROM files")
                for file_name, mtime_ns, file_size in signature:
                    connection.execute(
                        "INSERT INTO files(file_name, mtime_ns, file_size) VALUES (?, ?, ?)",
                        (file_name, mtime_ns, file_size),
                    )
                    data = loader(file_name)
                    if isinstance(data, dict):
                        self._insert_question(connection, file_name, data, mtime_ns, file_size)
                self._set_directory_marker(connection, directory_marker)

        self._execute_with_recovery(operation)

    def upsert(self, file_name: str, data: dict, mtime_ns: int, file_size: int) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            with connection:
                connection.execute(
                    """
                    INSERT INTO files(file_name, mtime_ns, file_size) VALUES (?, ?, ?)
                    ON CONFLICT(file_name) DO UPDATE SET
                        mtime_ns=excluded.mtime_ns,
                        file_size=excluded.file_size
                    """,
                    (file_name, mtime_ns, file_size),
                )
                connection.execute("DELETE FROM questions WHERE file_name = ?", (file_name,))
                self._insert_question(connection, file_name, data, mtime_ns, file_size)
                self._set_directory_marker(connection, self._directory_marker())

        self._execute_with_recovery(operation)

    def upsert_many(self, records: Iterable[tuple[str, dict, int, int]]) -> None:
        """Update multiple JSON-backed records in one SQLite transaction."""
        pending = list(records)
        if not pending:
            return

        def operation(connection: sqlite3.Connection) -> None:
            with connection:
                for file_name, data, mtime_ns, file_size in pending:
                    connection.execute(
                        """
                        INSERT INTO files(file_name, mtime_ns, file_size) VALUES (?, ?, ?)
                        ON CONFLICT(file_name) DO UPDATE SET
                            mtime_ns=excluded.mtime_ns,
                            file_size=excluded.file_size
                        """,
                        (file_name, mtime_ns, file_size),
                    )
                    connection.execute("DELETE FROM questions WHERE file_name = ?", (file_name,))
                    self._insert_question(connection, file_name, data, mtime_ns, file_size)
                self._set_directory_marker(connection, self._directory_marker())

        self._execute_with_recovery(operation)

    def delete(self, file_name: str) -> None:
        def operation(connection: sqlite3.Connection) -> None:
            with connection:
                connection.execute("DELETE FROM questions WHERE file_name = ?", (file_name,))
                connection.execute("DELETE FROM files WHERE file_name = ?", (file_name,))
                self._set_directory_marker(connection, self._directory_marker())

        self._execute_with_recovery(operation)

    def query_ids(
        self,
        *,
        query: str = "",
        topic_values: Iterable[str] = (),
        difficulty: str = "",
        course_id: str = "",
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[str], int]:
        where, parameters = self._filters(
            query=query,
            topic_values=topic_values,
            difficulty=difficulty,
            course_id=course_id,
        )

        def operation(connection: sqlite3.Connection) -> tuple[list[str], int]:
            total = int(connection.execute(
                f"SELECT COUNT(*) FROM questions{where}", parameters
            ).fetchone()[0])
            sql = f"SELECT question_id FROM questions{where} ORDER BY file_name"
            page_parameters = list(parameters)
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                page_parameters.extend([max(0, int(limit)), max(0, int(offset))])
            rows = connection.execute(sql, page_parameters)
            return [str(row[0]) for row in rows], total

        return self._execute_with_recovery(operation)

    def topic_rows(self, course_id: str = "") -> list[tuple[str, str, str]]:
        def operation(connection: sqlite3.Connection) -> list[tuple[str, str, str]]:
            if course_id:
                rows = connection.execute(
                    """
                    SELECT question_id, topic_id, topic_title
                    FROM questions WHERE course_id = ? ORDER BY file_name
                    """,
                    (course_id,),
                )
            else:
                rows = connection.execute(
                    "SELECT question_id, topic_id, topic_title FROM questions ORDER BY file_name"
                )
            return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]

        return self._execute_with_recovery(operation)

    def scheduling_rows(
        self,
        course_id: str = "",
    ) -> list[tuple[str, str, str, str]]:
        """Return lightweight metadata needed by the daily scheduler."""

        def operation(
            connection: sqlite3.Connection,
        ) -> list[tuple[str, str, str, str]]:
            if course_id:
                rows = connection.execute(
                    """
                    SELECT question_id, topic_id, topic_title, difficulty
                    FROM questions WHERE course_id = ? ORDER BY file_name
                    """,
                    (course_id,),
                )
            else:
                rows = connection.execute(
                    """
                    SELECT question_id, topic_id, topic_title, difficulty
                    FROM questions ORDER BY file_name
                    """
                )
            return [
                (str(row[0]), str(row[1]), str(row[2]), str(row[3]))
                for row in rows
            ]

        return self._execute_with_recovery(operation)

    def _execute_with_recovery(self, operation):
        for attempt in range(2):
            try:
                connection = self._connect()
                try:
                    return operation(connection)
                finally:
                    connection.close()
            except sqlite3.DatabaseError:
                if attempt:
                    raise
                self._remove_database_files()
        raise RuntimeError("question index recovery failed")

    def _connect(self) -> sqlite3.Connection:
        self.questions_dir.mkdir(parents=True, exist_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            self._ensure_schema(connection)
            return connection
        except Exception:
            connection.close()
            raise

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None and str(row[0]) != SCHEMA_VERSION:
            connection.execute("DROP TABLE IF EXISTS questions")
            connection.execute("DROP TABLE IF EXISTS files")
            connection.execute("DELETE FROM metadata")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS files(
                file_name TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL,
                file_size INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS questions(
                question_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL UNIQUE,
                course_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                topic_title TEXT NOT NULL,
                type TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                source_status TEXT NOT NULL,
                stem_preview TEXT NOT NULL,
                search_text TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                mtime_ns INTEGER NOT NULL,
                file_size INTEGER NOT NULL,
                FOREIGN KEY(file_name) REFERENCES files(file_name) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_questions_course_topic
                ON questions(course_id, topic_id);
            CREATE INDEX IF NOT EXISTS idx_questions_course_difficulty
                ON questions(course_id, difficulty);
            CREATE INDEX IF NOT EXISTS idx_questions_type ON questions(type);
            CREATE INDEX IF NOT EXISTS idx_questions_quality_status
                ON questions(quality_status);
            CREATE INDEX IF NOT EXISTS idx_questions_updated_at ON questions(updated_at);
            """
        )
        connection.execute(
            """
            INSERT INTO metadata(key, value) VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (SCHEMA_VERSION,),
        )
        connection.commit()

    @staticmethod
    def _insert_question(
        connection: sqlite3.Connection,
        file_name: str,
        data: dict,
        mtime_ns: int,
        file_size: int,
    ) -> None:
        question_id = str(data.get("question_id", "") or "").strip()
        if not question_id:
            return
        metadata = data.get("metadata", {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        bilingual = data.get("bilingual", {}) or {}
        if not isinstance(bilingual, dict):
            bilingual = {}

        def content(language: str, field: str) -> str:
            language_data = bilingual.get(language, {}) or {}
            if not isinstance(language_data, dict):
                return ""
            return str(language_data.get(field, "") or "")

        topic_id = str(data.get("topic_id") or data.get("topic") or "general").strip().lower()
        topic_title = str(
            data.get("topic_title") or metadata.get("topic_title") or topic_id
        ).strip() or topic_id
        search_text = " ".join([
            content("zh", "stem"),
            content("en", "stem"),
            content("zh", "explanation"),
            content("en", "explanation"),
            str(data.get("subtopic", "") or ""),
            topic_id,
            topic_title,
            str(metadata.get("legacy_topic", "") or ""),
        ]).casefold()
        stem_preview = (content("zh", "stem") or content("en", "stem")).strip()[:240]
        connection.execute(
            """
            INSERT INTO questions(
                question_id, file_name, course_id, topic_id, topic_title, type,
                difficulty, quality_status, source_status, stem_preview,
                search_text, updated_at, mtime_ns, file_size
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question_id,
                file_name,
                str(metadata.get("course_id", "") or "").strip(),
                topic_id,
                topic_title,
                str(data.get("type", "") or ""),
                str(data.get("difficulty", "") or ""),
                str(metadata.get("quality_status", "") or ""),
                str(metadata.get("source_ref_status", "") or ""),
                stem_preview,
                search_text,
                str(metadata.get("updated_at") or metadata.get("created_at") or ""),
                int(mtime_ns),
                int(file_size),
            ),
        )

    @staticmethod
    def _filters(
        *, query: str, topic_values: Iterable[str], difficulty: str, course_id: str
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        parameters: list[object] = []
        if query:
            escaped = query.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("search_text LIKE ? ESCAPE '\\'")
            parameters.append(f"%{escaped}%")
        topics = sorted({str(value).strip().lower() for value in topic_values if str(value).strip()})
        if topics:
            placeholders = ", ".join("?" for _ in topics)
            clauses.append(f"topic_id IN ({placeholders})")
            parameters.extend(topics)
        if difficulty:
            clauses.append("difficulty = ?")
            parameters.append(difficulty)
        if course_id:
            clauses.append("course_id = ?")
            parameters.append(course_id)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), parameters

    def _directory_signature(self) -> tuple[tuple[str, int, int], ...]:
        signature: list[tuple[str, int, int]] = []
        for path in sorted(self.questions_dir.glob("*.json"), key=lambda item: item.name):
            try:
                stat = path.stat()
            except OSError:
                continue
            signature.append((path.name, stat.st_mtime_ns, stat.st_size))
        return tuple(signature)

    def _directory_marker(self) -> str:
        try:
            stat = self.questions_dir.stat()
        except OSError:
            return "missing"
        return f"{stat.st_mtime_ns}:{stat.st_size}"

    @staticmethod
    def _set_directory_marker(connection: sqlite3.Connection, marker: str) -> None:
        connection.execute(
            """
            INSERT INTO metadata(key, value) VALUES ('directory_marker', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (marker,),
        )

    def _remove_database_files(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(f"{self.path}{suffix}")
            except FileNotFoundError:
                pass
