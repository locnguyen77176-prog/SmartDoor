from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from database import FaceCheckDatabase


class FaceCheckDatabaseTests(unittest.TestCase):
    def make_store(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return FaceCheckDatabase(Path(temporary.name) / "facecheck.db")

    def test_profile_embeddings_round_trip_without_precision_loss(self):
        store = self.make_store()
        vectors = [
            np.linspace(0.0, 1.0, 512, dtype=np.float64).tolist(),
            np.linspace(1.0, 2.0, 512, dtype=np.float64).tolist(),
        ]
        profiles = {
            "NV001": {
                "id": "NV001",
                "name": "Nguyen Van A",
                "role": "Ky su",
                "department": "AI",
                "image_path": "data/faces/NV001.jpg",
                "timestamp": "20261116_120000",
                "recognition_enabled": True,
                "embedding": vectors[0],
                "embeddings": vectors,
                "embedding_count": 2,
            }
        }

        store.replace_profiles(profiles)
        loaded = store.load_profiles()["NV001"]

        self.assertEqual(loaded["timestamp"], "20261116_120000")
        self.assertEqual(loaded["embedding_count"], 2)
        for expected, actual in zip(vectors, loaded["embeddings"]):
            self.assertTrue(np.array_equal(expected, actual))

    def test_all_persistent_datasets_round_trip(self):
        store = self.make_store()
        profiles = {
            "NV001": {
                "id": "NV001", "name": "A", "role": "R",
                "department": "D", "embedding": [1.0, 0.0],
                "embeddings": [[1.0, 0.0]],
            }
        }
        logs = [
            {"time": "12:00:00 16/11/2026", "id": "NV001", "name": "A",
             "status": "Thành công", "source": "face"},
            {"time": "11:59:00 16/11/2026", "id": "—", "name": "Lạ",
             "status": "Thất bại", "source": "face"},
        ]
        fingerprints = {
            "3": {"fingerprint_id": 3, "employee_id": "NV001", "name": "A",
                  "role": "R", "department": "D", "status": "active"}
        }
        events = [
            {"event_id": "evt-1", "device_id": "door-01",
             "event": "fingerprint_granted", "source": "fingerprint",
             "fingerprint_id": 3, "received_at": "2026-11-16T12:00:00+00:00"}
        ]

        store.replace_all(
            profiles=profiles, authentication_logs=logs,
            device_id="door-01", fingerprints=fingerprints,
            door_events=events,
        )

        self.assertEqual(store.load_authentication_logs(), logs)
        self.assertEqual(store.load_fingerprints("door-01")["3"]["name"], "A")
        self.assertEqual(store.load_door_events("door-01"), events)
        self.assertEqual(store.counts(), {
            "employees": 1,
            "face_embeddings": 1,
            "fingerprints": 1,
            "authentication_logs": 2,
            "door_events": 1,
        })

    def test_replacing_profiles_removes_deleted_employee(self):
        store = self.make_store()
        base = {
            "name": "A", "role": "R", "department": "D",
            "embedding": [1.0, 0.0], "embeddings": [[1.0, 0.0]],
        }
        store.replace_profiles({
            "NV001": {**base, "id": "NV001"},
            "NV002": {**base, "id": "NV002"},
        })
        store.replace_profiles({"NV002": {**base, "id": "NV002"}})

        self.assertEqual(set(store.load_profiles()), {"NV002"})
        self.assertEqual(store.counts()["face_embeddings"], 1)

    def test_incremental_history_and_event_inserts_are_idempotent(self):
        store = self.make_store()
        log = {
            "time": "12:00:00 16/11/2026", "id": "NV001", "name": "A",
            "status": "Thành công", "source": "fingerprint",
            "door_event_id": "evt-1",
        }
        event = {
            "event_id": "evt-1", "device_id": "door-01",
            "event": "fingerprint_granted", "received_at": "2026-11-16T12:00:00Z",
        }

        self.assertTrue(store.append_authentication_log(log))
        self.assertFalse(store.append_authentication_log(log))
        self.assertTrue(store.append_door_event("door-01", event))
        self.assertFalse(store.append_door_event("door-01", event))
        self.assertEqual(store.counts()["authentication_logs"], 1)
        self.assertEqual(store.counts()["door_events"], 1)


if __name__ == "__main__":
    unittest.main()

