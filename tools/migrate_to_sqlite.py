"""Merge legacy FaceCheck files and an existing SQLite database safely.

The script is idempotent: current legacy files win for matching employee or
fingerprint keys, while historical SQLite-only rows are retained.  It creates
a timestamped backup before opening the database for writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import shutil
import sys
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import FaceCheckDatabase  # noqa: E402


LEGACY_FILES = (
    "embeddings.pkl",
    "attendance_history.json",
    "fingerprints.json",
    "door_events.json",
    "facecheck.db",
    "facecheck.db-wal",
    "facecheck.db-shm",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sao lưu và hợp nhất dữ liệu FaceCheck vào SQLite"
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--device-id", default="door-01")
    parser.add_argument(
        "--skip-backup", action="store_true",
        help="Chỉ dùng khi đã có bản sao lưu được xác minh",
    )
    return parser.parse_args()


def backup_data(data_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = data_dir / "backups" / f"sqlite_migration_{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    for name in LEGACY_FILES:
        source = data_dir / name
        if source.is_file():
            shutil.copy2(source, destination / name)
    faces = data_dir / "faces"
    if faces.is_dir():
        shutil.copytree(faces, destination / "faces")
    return destination


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def canonical(value) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=lambda item: item.tolist() if isinstance(item, np.ndarray) else str(item),
    )


def merge_profiles(current: dict, legacy: dict) -> dict:
    merged = {}
    lookup = {}
    for source in (current, legacy):
        for key, raw in (source or {}).items():
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            code = str(item.get("id") or key).strip()
            if not code:
                continue
            folded = code.casefold()
            previous = lookup.get(folded)
            if previous is not None:
                merged.pop(previous, None)
            item["id"] = code
            merged[code] = item
            lookup[folded] = code
    return merged


def merge_fingerprints(current: dict, legacy: dict) -> dict:
    merged = {}
    for source in (current, legacy):
        for key, raw in (source or {}).items():
            if not isinstance(raw, dict):
                continue
            try:
                fingerprint_id = int(raw.get("fingerprint_id", key))
            except (TypeError, ValueError):
                continue
            if 1 <= fingerprint_id <= 127:
                merged[str(fingerprint_id)] = {
                    **raw, "fingerprint_id": fingerprint_id,
                }
    return merged


def merge_logs(legacy: list, current: list) -> list:
    result = []
    seen_payloads = set()
    seen_door_events = set()
    # Legacy JSON is the live source immediately before migration. Keep its
    # newest-first order, then append SQLite-only historical records.
    for raw in list(legacy or []) + list(current or []):
        if not isinstance(raw, dict):
            continue
        payload_key = canonical(raw)
        event_id = str(raw.get("door_event_id") or "").strip()
        if payload_key in seen_payloads or (event_id and event_id in seen_door_events):
            continue
        seen_payloads.add(payload_key)
        if event_id:
            seen_door_events.add(event_id)
        result.append(dict(raw))
    return result


def merge_events(current: list, legacy: list) -> list:
    merged = {}
    anonymous = []
    for raw in list(current or []) + list(legacy or []):
        if not isinstance(raw, dict):
            continue
        event_id = str(raw.get("event_id") or "").strip()
        if event_id:
            merged[event_id] = dict(raw)
        else:
            anonymous.append(dict(raw))
    events = list(merged.values()) + anonymous
    events.sort(key=lambda item: (
        str(item.get("received_at") or ""),
        int(item.get("occurred_at") or 0),
        str(item.get("event_id") or ""),
    ))
    return events


def vector_count(profiles: dict) -> int:
    total = 0
    for profile in profiles.values():
        vectors = profile.get("embeddings")
        if vectors is not None and len(vectors):
            total += len(vectors)
        elif profile.get("embedding") is not None:
            total += 1
    return total


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    arguments = parse_args()
    data_dir = (ROOT / arguments.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    database_path = data_dir / "facecheck.db"

    backup = None
    if not arguments.skip_backup:
        backup = backup_data(data_dir)
        print(f"[MIGRATION] Backup: {backup}")

    store = FaceCheckDatabase(database_path)
    existing_profiles = store.load_profiles()
    existing_logs = store.load_authentication_logs()
    existing_fingerprints = store.load_fingerprints(arguments.device_id)
    existing_events = store.load_door_events(arguments.device_id)

    legacy_profiles = {}
    embeddings_path = data_dir / "embeddings.pkl"
    if embeddings_path.exists():
        with embeddings_path.open("rb") as handle:
            value = pickle.load(handle)
            if isinstance(value, dict):
                legacy_profiles = value
    legacy_logs = load_json(data_dir / "attendance_history.json", [])
    legacy_fingerprints = load_json(data_dir / "fingerprints.json", {})
    legacy_events = load_json(data_dir / "door_events.json", [])

    profiles = merge_profiles(existing_profiles, legacy_profiles)
    logs = merge_logs(legacy_logs, existing_logs)
    fingerprints = merge_fingerprints(existing_fingerprints, legacy_fingerprints)
    events = merge_events(existing_events, legacy_events)

    expected = {
        "employees": len(profiles),
        "face_embeddings": vector_count(profiles),
        "fingerprints": len(fingerprints),
        "authentication_logs": len(logs),
        "door_events": len({
            str(item.get("event_id")) for item in events if item.get("event_id")
        }),
    }
    store.replace_all(
        profiles=profiles,
        authentication_logs=logs,
        device_id=arguments.device_id,
        fingerprints=fingerprints,
        door_events=events,
    )
    actual = store.counts(arguments.device_id)
    if actual != expected:
        raise RuntimeError(
            f"Xác minh số lượng thất bại: expected={expected}, actual={actual}"
        )

    reloaded = store.load_profiles()
    for code, profile in legacy_profiles.items():
        employee_code = str(profile.get("id") or code)
        migrated = next(
            (item for key, item in reloaded.items()
             if key.casefold() == employee_code.casefold()),
            None,
        )
        if migrated is None:
            raise RuntimeError(f"Thiếu hồ sơ sau migration: {employee_code}")
        before = profile.get("embeddings") or []
        after = migrated.get("embeddings") or []
        if len(before) != len(after):
            raise RuntimeError(
                f"Sai số vector sau migration cho {employee_code}: "
                f"{len(before)} != {len(after)}"
            )
        for left, right in zip(before, after):
            if not np.array_equal(
                np.asarray(left, dtype=np.float64),
                np.asarray(right, dtype=np.float64),
            ):
                raise RuntimeError(
                    f"Vector bị thay đổi sau migration: {employee_code}"
                )

    print(f"[MIGRATION] SQLite: {database_path}")
    store.checkpoint()
    print(f"[MIGRATION] SHA256: {file_sha256(database_path)}")
    print(f"[MIGRATION] Counts: {actual}")
    print("[MIGRATION] Legacy files are preserved in backup; JSON/Pickle were not deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

