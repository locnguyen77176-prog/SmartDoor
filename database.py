"""SQLite persistence for FaceCheck.

The runtime keeps AI embeddings in memory for fast recognition, while this
module is the durable source of truth for profiles, fingerprint metadata and
access history.  Every operation opens a short-lived connection so calls from
the camera, MQTT and web threads do not share sqlite3 connection objects.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np


SCHEMA_VERSION = 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def _json_text(value) -> str:
    return json.dumps(
        _json_safe(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _json_object(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class FaceCheckDatabase:
    """Thread-safe facade around the local FaceCheck SQLite database."""

    def __init__(self, path: str | Path = "data/facecheck.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }

    @classmethod
    def _ensure_column(
        cls, connection: sqlite3.Connection, table: str,
        column: str, declaration: str,
    ) -> None:
        if column not in cls._columns(connection, table):
            connection.execute(
                f'ALTER TABLE "{table}" ADD COLUMN "{column}" {declaration}'
            )

    def initialize(self) -> None:
        with self._write_lock, self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS employees (
                    employee_code TEXT PRIMARY KEY COLLATE NOCASE,
                    name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    department TEXT NOT NULL,
                    image_path TEXT,
                    recognition_enabled INTEGER NOT NULL DEFAULT 1,
                    source TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    profile_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS face_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee_code TEXT NOT NULL COLLATE NOCASE,
                    sample_index INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    dimension INTEGER NOT NULL,
                    model_name TEXT NOT NULL DEFAULT 'ArcFace',
                    created_at TEXT NOT NULL,
                    dtype TEXT NOT NULL DEFAULT 'float32',
                    UNIQUE(employee_code, sample_index),
                    FOREIGN KEY(employee_code) REFERENCES employees(employee_code)
                        ON UPDATE CASCADE ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS fingerprints (
                    device_id TEXT NOT NULL,
                    fingerprint_id INTEGER NOT NULL,
                    employee_code TEXT COLLATE NOCASE,
                    name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    department TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    registered_at TEXT,
                    first_seen_at TEXT,
                    updated_at TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY(device_id, fingerprint_id)
                );

                CREATE TABLE IF NOT EXISTS authentication_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    display_time TEXT NOT NULL,
                    employee_code TEXT,
                    name TEXT NOT NULL,
                    role TEXT,
                    department TEXT,
                    status TEXT NOT NULL,
                    reason TEXT,
                    source TEXT,
                    door_event_id TEXT UNIQUE,
                    distance REAL,
                    second_distance REAL,
                    margin REAL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS door_events (
                    event_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source TEXT,
                    fingerprint_id INTEGER,
                    uptime_ms INTEGER,
                    occurred_at INTEGER,
                    received_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    state TEXT,
                    firmware TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    last_seen_at TEXT
                );

                CREATE TABLE IF NOT EXISTS app_settings (
                    setting_key TEXT PRIMARY KEY,
                    setting_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    description TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_auth_created_at
                    ON authentication_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_auth_employee
                    ON authentication_logs(employee_code, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_door_events_received
                    ON door_events(device_id, received_at DESC);
                CREATE INDEX IF NOT EXISTS idx_fingerprints_employee
                    ON fingerprints(employee_code);
                """
            )
            # Upgrade the pre-existing database without dropping any row.
            self._ensure_column(
                connection, "employees", "profile_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            self._ensure_column(
                connection, "face_embeddings", "dtype",
                "TEXT NOT NULL DEFAULT 'float32'",
            )
            self._ensure_column(
                connection, "fingerprints", "payload_json",
                "TEXT NOT NULL DEFAULT '{}'",
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations
                    (version, applied_at, description)
                VALUES (?, ?, ?)
                """,
                (SCHEMA_VERSION, _utc_now(), "SQLite source of truth"),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    @staticmethod
    def _vector_rows(profile: dict) -> list[tuple[np.ndarray, str]]:
        raw_vectors = profile.get("embeddings")
        if raw_vectors is None or len(raw_vectors) == 0:
            singular = profile.get("embedding")
            raw_vectors = [] if singular is None else [singular]
        result = []
        for vector in raw_vectors:
            # Python/JSON embeddings are doubles. Keep float64 so migration is
            # lossless; rows already stored as float32 retain their own dtype.
            array = np.asarray(vector, dtype=np.float64).reshape(-1)
            if array.size:
                result.append((array, str(array.dtype)))
        return result

    @staticmethod
    def _centroid(vectors: list[list[float]]) -> list[float]:
        if not vectors:
            return []
        normalized = []
        for vector in vectors:
            value = np.asarray(vector, dtype=np.float64)
            norm = float(np.linalg.norm(value))
            if norm > 1e-12:
                normalized.append(value / norm)
        if not normalized:
            return []
        centroid = np.mean(np.stack(normalized), axis=0)
        norm = float(np.linalg.norm(centroid))
        return (centroid / norm if norm > 1e-12 else centroid).tolist()

    def _replace_profiles(
        self, connection: sqlite3.Connection, profiles: dict,
    ) -> None:
        normalized: dict[str, dict] = {}
        for key, value in (profiles or {}).items():
            if not isinstance(value, dict):
                continue
            code = str(value.get("id") or key).strip()
            if code:
                normalized[code] = dict(value)

        codes = list(normalized)
        if codes:
            placeholders = ",".join("?" for _ in codes)
            connection.execute(
                f"DELETE FROM employees WHERE employee_code NOT IN ({placeholders})",
                codes,
            )
        else:
            connection.execute("DELETE FROM employees")

        now = _utc_now()
        for code, profile in normalized.items():
            name = str(profile.get("name") or "Nhân viên").strip()
            role = str(profile.get("role") or "Nhân viên").strip()
            department = str(
                profile.get("department") or profile.get("dept") or "Phòng IT"
            ).strip()
            image_path = str(profile.get("image_path") or "").strip() or None
            source = str(profile.get("source") or "").strip() or None
            enabled = int(bool(profile.get("recognition_enabled", True)))
            payload = dict(profile)
            payload.pop("embeddings", None)
            payload.pop("dept", None)
            payload.update({
                "id": code,
                "name": name,
                "role": role,
                "department": department,
                "image_path": image_path,
                "recognition_enabled": bool(enabled),
            })
            connection.execute(
                """
                INSERT INTO employees (
                    employee_code, name, role, department, image_path,
                    recognition_enabled, source, created_at, updated_at,
                    profile_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(employee_code) DO UPDATE SET
                    name = excluded.name,
                    role = excluded.role,
                    department = excluded.department,
                    image_path = excluded.image_path,
                    recognition_enabled = excluded.recognition_enabled,
                    source = excluded.source,
                    updated_at = excluded.updated_at,
                    profile_json = excluded.profile_json
                """,
                (
                    code, name, role, department, image_path, enabled, source,
                    now, now, _json_text(payload),
                ),
            )
            connection.execute(
                "DELETE FROM face_embeddings WHERE employee_code = ?", (code,)
            )
            for index, (vector, dtype) in enumerate(self._vector_rows(profile)):
                connection.execute(
                    """
                    INSERT INTO face_embeddings (
                        employee_code, sample_index, vector, dimension,
                        model_name, created_at, dtype
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        code, index, sqlite3.Binary(vector.tobytes(order="C")),
                        int(vector.size), "ArcFace", now, dtype,
                    ),
                )

    def replace_profiles(self, profiles: dict) -> None:
        with self._write_lock, self.connect() as connection:
            self._replace_profiles(connection, profiles)

    def load_profiles(self) -> dict:
        with self.connect() as connection:
            employees = connection.execute(
                "SELECT * FROM employees ORDER BY employee_code COLLATE NOCASE"
            ).fetchall()
            result = {}
            for row in employees:
                profile = _json_object(row["profile_json"])
                code = str(row["employee_code"])
                profile.update({
                    "id": code,
                    "name": row["name"],
                    "role": row["role"],
                    "department": row["department"],
                    "image_path": row["image_path"],
                    "recognition_enabled": bool(row["recognition_enabled"]),
                })
                if row["source"]:
                    profile["source"] = row["source"]
                vectors = []
                vector_rows = connection.execute(
                    """
                    SELECT vector, dimension, dtype
                    FROM face_embeddings
                    WHERE employee_code = ?
                    ORDER BY sample_index
                    """,
                    (code,),
                ).fetchall()
                for vector_row in vector_rows:
                    try:
                        dtype = np.dtype(vector_row["dtype"] or "float32")
                        vector = np.frombuffer(vector_row["vector"], dtype=dtype)
                    except (TypeError, ValueError):
                        continue
                    dimension = int(vector_row["dimension"] or 0)
                    if dimension > 0 and vector.size == dimension:
                        vectors.append(vector.astype(np.float64, copy=False).tolist())
                profile["embeddings"] = vectors
                profile["embedding_count"] = len(vectors)
                if not profile.get("embedding") and vectors:
                    profile["embedding"] = self._centroid(vectors)
                result[code] = profile
            return result

    @staticmethod
    def _log_values(record: dict) -> tuple:
        metrics = record.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        display_time = str(record.get("time") or "").strip()
        return (
            display_time,
            str(record.get("id") or "").strip() or None,
            str(record.get("name") or "Không xác định").strip(),
            str(record.get("role") or "").strip() or None,
            str(record.get("dept") or record.get("department") or "").strip() or None,
            str(record.get("status") or "Không xác định").strip(),
            str(record.get("reason") or "").strip() or None,
            str(record.get("source") or "").strip() or None,
            str(record.get("door_event_id") or "").strip() or None,
            metrics.get("distance", record.get("distance")),
            metrics.get("second_distance", record.get("second_distance")),
            metrics.get("margin", record.get("margin")),
            _json_text(record),
            _utc_now(),
        )

    def _replace_authentication_logs(
        self, connection: sqlite3.Connection, records: Iterable[dict],
    ) -> None:
        connection.execute("DELETE FROM authentication_logs")
        seen_door_events = set()
        valid_records = []
        for record in records or []:
            if not isinstance(record, dict):
                continue
            event_id = str(record.get("door_event_id") or "").strip()
            if event_id and event_id in seen_door_events:
                continue
            if event_id:
                seen_door_events.add(event_id)
            valid_records.append(record)
        # Runtime representation is newest-first; AUTOINCREMENT order is the
        # reverse so ORDER BY id DESC reconstructs it exactly.
        for record in reversed(valid_records):
            connection.execute(
                """
                INSERT INTO authentication_logs (
                    display_time, employee_code, name, role, department,
                    status, reason, source, door_event_id, distance,
                    second_distance, margin, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._log_values(record),
            )

    def replace_authentication_logs(self, records: Iterable[dict]) -> None:
        with self._write_lock, self.connect() as connection:
            self._replace_authentication_logs(connection, records)

    def append_authentication_log(self, record: dict) -> bool:
        """Append one runtime record without rewriting the history table."""
        if not isinstance(record, dict):
            return False
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO authentication_logs (
                    display_time, employee_code, name, role, department,
                    status, reason, source, door_event_id, distance,
                    second_distance, margin, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._log_values(record),
            )
            return cursor.rowcount > 0

    def load_authentication_logs(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM authentication_logs ORDER BY id DESC"
            ).fetchall()
        return [_json_object(row["payload_json"]) for row in rows]

    def _replace_fingerprints(
        self, connection: sqlite3.Connection, device_id: str, registry: dict,
    ) -> None:
        connection.execute(
            "DELETE FROM fingerprints WHERE device_id = ?", (device_id,)
        )
        now = _utc_now()
        for key, raw in (registry or {}).items():
            if not isinstance(raw, dict):
                continue
            try:
                fingerprint_id = int(raw.get("fingerprint_id", key))
            except (TypeError, ValueError):
                continue
            if not 1 <= fingerprint_id <= 127:
                continue
            item = dict(raw)
            connection.execute(
                """
                INSERT INTO fingerprints (
                    device_id, fingerprint_id, employee_code, name, role,
                    department, status, registered_at, first_seen_at,
                    updated_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    fingerprint_id,
                    str(item.get("employee_id") or "").strip() or None,
                    str(item.get("name") or "").strip(),
                    str(item.get("role") or "").strip(),
                    str(item.get("department") or "").strip(),
                    str(item.get("status") or "active").strip(),
                    item.get("registered_at"),
                    item.get("first_seen_at"),
                    item.get("updated_at") or now,
                    _json_text(item),
                ),
            )

    def replace_fingerprints(self, device_id: str, registry: dict) -> None:
        with self._write_lock, self.connect() as connection:
            self._replace_fingerprints(connection, device_id, registry)

    def load_fingerprints(self, device_id: str) -> dict:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM fingerprints
                WHERE device_id = ? ORDER BY fingerprint_id
                """,
                (device_id,),
            ).fetchall()
        result = {}
        for row in rows:
            item = _json_object(row["payload_json"])
            item.update({
                "fingerprint_id": int(row["fingerprint_id"]),
                "employee_id": row["employee_code"] or "",
                "name": row["name"],
                "role": row["role"],
                "department": row["department"],
                "status": row["status"],
            })
            for key in ("registered_at", "first_seen_at", "updated_at"):
                if row[key]:
                    item[key] = row[key]
            result[str(row["fingerprint_id"])] = item
        return result

    def _replace_door_events(
        self, connection: sqlite3.Connection, device_id: str,
        events: Iterable[dict],
    ) -> None:
        connection.execute("DELETE FROM door_events WHERE device_id = ?", (device_id,))
        seen = set()
        for raw in events or []:
            if not isinstance(raw, dict):
                continue
            event = dict(raw)
            event_id = str(event.get("event_id") or "").strip()
            if not event_id or event_id in seen:
                continue
            seen.add(event_id)
            self._insert_door_event(connection, device_id, event)

    @staticmethod
    def _insert_door_event(
        connection: sqlite3.Connection, device_id: str, event: dict,
    ) -> sqlite3.Cursor:
        event_id = str(event.get("event_id") or "").strip()
        received_at = str(event.get("received_at") or _utc_now())
        fingerprint_id = event.get("fingerprint_id")
        return connection.execute(
            """
            INSERT OR IGNORE INTO door_events (
                event_id, device_id, event_type, source, fingerprint_id,
                uptime_ms, occurred_at, received_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(event.get("device_id") or device_id),
                str(event.get("event") or "unknown"),
                str(event.get("source") or "") or None,
                fingerprint_id if isinstance(fingerprint_id, int) else None,
                event.get("uptime_ms") if isinstance(event.get("uptime_ms"), int) else None,
                event.get("occurred_at") if isinstance(event.get("occurred_at"), int) else None,
                received_at,
                _json_text(event),
            ),
        )

    def replace_door_events(
        self, device_id: str, events: Iterable[dict],
    ) -> None:
        with self._write_lock, self.connect() as connection:
            self._replace_door_events(connection, device_id, events)

    def append_door_event(self, device_id: str, event: dict) -> bool:
        """Append one device event, ignoring an already persisted event ID."""
        if not isinstance(event, dict) or not str(event.get("event_id") or "").strip():
            return False
        with self._write_lock, self.connect() as connection:
            cursor = self._insert_door_event(connection, device_id, dict(event))
            return cursor.rowcount > 0

    def load_door_events(self, device_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM door_events
                WHERE device_id = ?
                ORDER BY received_at ASC, rowid ASC
                """,
                (device_id,),
            ).fetchall()
        return [_json_object(row["payload_json"]) for row in rows]

    def upsert_device_status(self, payload: dict) -> None:
        device_id = str(payload.get("device_id") or "").strip()
        if not device_id:
            return
        received_at = str(payload.get("received_at") or _utc_now())
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO devices (
                    device_id, state, firmware, payload_json, last_seen_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    state = excluded.state,
                    firmware = excluded.firmware,
                    payload_json = excluded.payload_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    device_id,
                    str(payload.get("state") or "") or None,
                    str(payload.get("firmware") or "") or None,
                    _json_text(payload),
                    received_at,
                ),
            )

    def replace_all(
        self, *, profiles: dict, authentication_logs: Iterable[dict],
        device_id: str, fingerprints: dict, door_events: Iterable[dict],
    ) -> None:
        """Atomically replace the four migrated datasets."""
        with self._write_lock, self.connect() as connection:
            self._replace_profiles(connection, profiles)
            self._replace_authentication_logs(connection, authentication_logs)
            self._replace_fingerprints(connection, device_id, fingerprints)
            self._replace_door_events(connection, device_id, door_events)
            connection.execute(
                """
                INSERT INTO app_settings(setting_key, setting_value, updated_at)
                VALUES ('storage_backend', 'sqlite', ?)
                ON CONFLICT(setting_key) DO UPDATE SET
                    setting_value = excluded.setting_value,
                    updated_at = excluded.updated_at
                """,
                (_utc_now(),),
            )

    def counts(self, device_id: str = "door-01") -> dict[str, int]:
        with self.connect() as connection:
            return {
                "employees": int(connection.execute(
                    "SELECT COUNT(*) FROM employees"
                ).fetchone()[0]),
                "face_embeddings": int(connection.execute(
                    "SELECT COUNT(*) FROM face_embeddings"
                ).fetchone()[0]),
                "fingerprints": int(connection.execute(
                    "SELECT COUNT(*) FROM fingerprints WHERE device_id = ?",
                    (device_id,),
                ).fetchone()[0]),
                "authentication_logs": int(connection.execute(
                    "SELECT COUNT(*) FROM authentication_logs"
                ).fetchone()[0]),
                "door_events": int(connection.execute(
                    "SELECT COUNT(*) FROM door_events WHERE device_id = ?",
                    (device_id,),
                ).fetchone()[0]),
            }

    def checkpoint(self) -> None:
        """Flush committed WAL pages into the main database file."""
        with self._write_lock, self.connect() as connection:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

