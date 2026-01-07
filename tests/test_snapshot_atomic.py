"""
Test: UI/reader always sees a complete Snapshot object (no partial/None field mutation)
"""
import time
import threading
import pytest

from src.datahub import DataHub
from src.engine import EngineLoop
from src.snapshot import SnapshotDTO


def test_snapshot_atomic_complete_object():
    """
    Verify that readers always observe complete, immutable snapshots.

    V1a.1 Slice 1 acceptance criterion:
    - No partial reads
    - No None field mutations
    - Snapshots are atomic
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.3)  # Let engine publish some snapshots

        # Read snapshot multiple times
        for _ in range(20):
            snapshot = datahub.get_latest()

            # Verify snapshot is complete
            assert snapshot is not None, "Snapshot should not be None after engine starts"
            assert isinstance(snapshot, SnapshotDTO), "Snapshot must be SnapshotDTO instance"

            # Verify required fields are present and valid
            assert snapshot.schema_version == "snapshot.v1", "Schema version must be set"
            assert snapshot.run_id, "run_id must be set"
            assert snapshot.snapshot_id > 0, "snapshot_id must be positive"
            assert snapshot.ts_unix_ms > 0, "ts_unix_ms must be positive"
            assert isinstance(snapshot.intent, str), "intent must be string"
            assert isinstance(snapshot.arm, bool), "arm must be boolean"
            assert isinstance(snapshot.allowed, bool), "allowed must be boolean"
            assert isinstance(snapshot.reason_codes, list), "reason_codes must be list"
            assert isinstance(snapshot.cycle_ms, int), "cycle_ms must be int"
            assert isinstance(snapshot.engine_degraded, bool), "engine_degraded must be boolean"
            assert isinstance(snapshot.extras, dict), "extras must be dict"

            time.sleep(0.05)

    finally:
        engine.stop()


def test_snapshot_immutability():
    """
    Verify that SnapshotDTO is immutable (frozen dataclass).

    Readers should not be able to modify snapshots.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=100)

    try:
        engine.start()
        time.sleep(0.2)

        snapshot = datahub.get_latest()
        assert snapshot is not None

        # Attempt to mutate should raise error (frozen dataclass)
        with pytest.raises(Exception):  # dataclass.FrozenInstanceError or AttributeError
            snapshot.snapshot_id = 999

        with pytest.raises(Exception):
            snapshot.allowed = True

    finally:
        engine.stop()


def test_snapshot_concurrent_reads():
    """
    Verify that concurrent readers always see complete snapshots.

    Multiple threads reading simultaneously should not see partial state.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    read_errors = []
    snapshots_read = []

    def reader_thread():
        """Reader thread that continuously reads snapshots."""
        try:
            for _ in range(30):
                snapshot = datahub.get_latest()
                if snapshot:
                    # Verify snapshot is complete
                    assert snapshot.schema_version == "snapshot.v1"
                    assert snapshot.snapshot_id > 0
                    assert snapshot.run_id
                    snapshots_read.append(snapshot.snapshot_id)
                time.sleep(0.02)
        except Exception as e:
            read_errors.append(str(e))

    try:
        engine.start()
        time.sleep(0.2)  # Let engine start publishing

        # Start multiple reader threads
        threads = [threading.Thread(target=reader_thread) for _ in range(3)]
        for t in threads:
            t.start()

        # Wait for readers to complete
        for t in threads:
            t.join(timeout=5.0)

        # Verify no read errors
        assert len(read_errors) == 0, f"Reader errors: {read_errors}"

        # Verify all readers got snapshots
        assert len(snapshots_read) > 0, "Readers should have read snapshots"

    finally:
        engine.stop()


def test_snapshot_no_partial_updates():
    """
    Verify that snapshot fields are never observed in a partially-updated state.

    When snapshot_id increments, all other fields should be consistent
    with that snapshot version.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.2)

        # Track snapshots and verify consistency
        seen_snapshots = {}

        for _ in range(30):
            snapshot = datahub.get_latest()
            if snapshot:
                sid = snapshot.snapshot_id

                # If we've seen this snapshot_id before, it must be identical
                if sid in seen_snapshots:
                    prev = seen_snapshots[sid]
                    assert prev.run_id == snapshot.run_id, "run_id changed for same snapshot_id"
                    assert prev.ts_unix_ms == snapshot.ts_unix_ms, "ts_unix_ms changed for same snapshot_id"
                    assert prev.intent == snapshot.intent, "intent changed for same snapshot_id"
                    assert prev.arm == snapshot.arm, "arm changed for same snapshot_id"
                else:
                    seen_snapshots[sid] = snapshot

            time.sleep(0.03)

    finally:
        engine.stop()
