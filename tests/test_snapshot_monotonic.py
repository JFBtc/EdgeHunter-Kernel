"""
Test: Snapshot IDs are monotonic increasing over multiple loop ticks
"""
import time
import pytest

from src.datahub import DataHub
from src.engine import EngineLoop


def test_snapshot_id_monotonic_increasing():
    """
    Verify that snapshot_id increases monotonically over multiple engine cycles.

    V1a.1 Slice 1 acceptance criterion.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)  # 20 Hz for faster testing

    try:
        # Start engine
        engine.start()

        # Wait for engine to publish several snapshots
        time.sleep(0.5)  # Allow ~10 cycles

        # Collect snapshot IDs
        snapshot_ids = []
        for _ in range(10):
            snapshot = datahub.get_latest()
            if snapshot:
                snapshot_ids.append(snapshot.snapshot_id)
            time.sleep(0.05)

        # Verify we got snapshots
        assert len(snapshot_ids) > 0, "No snapshots published"

        # Verify monotonic increasing
        for i in range(1, len(snapshot_ids)):
            assert snapshot_ids[i] > snapshot_ids[i - 1], (
                f"Snapshot IDs not monotonic: {snapshot_ids[i]} <= {snapshot_ids[i-1]}"
            )

        # Verify all IDs are positive
        assert all(sid > 0 for sid in snapshot_ids), "Snapshot IDs must be positive"

    finally:
        engine.stop()


def test_snapshot_id_starts_at_one():
    """
    Verify that the first snapshot has snapshot_id >= 1 (positive).

    Note: We may observe snapshot_id > 1 due to timing, but the
    engine guarantees the first snapshot it creates has ID 1.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=100)

    try:
        engine.start()
        time.sleep(0.15)  # Wait for first snapshot

        snapshot = datahub.get_latest()
        assert snapshot is not None, "No snapshot published"
        assert snapshot.snapshot_id >= 1, f"First snapshot_id should be >= 1, got {snapshot.snapshot_id}"

        # Verify snapshot_id is small (we haven't run many cycles yet)
        assert snapshot.snapshot_id <= 5, f"snapshot_id too high after short wait: {snapshot.snapshot_id}"

    finally:
        engine.stop()


def test_snapshot_id_continuous_sequence():
    """
    Verify that snapshot_ids form a continuous sequence (1, 2, 3, ...).
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.6)  # Allow multiple cycles

        # Collect snapshots over time
        snapshots = []
        for _ in range(15):
            snapshot = datahub.get_latest()
            if snapshot and (not snapshots or snapshot.snapshot_id != snapshots[-1].snapshot_id):
                snapshots.append(snapshot)
            time.sleep(0.05)

        # Verify we have multiple distinct snapshots
        assert len(snapshots) >= 5, f"Expected at least 5 snapshots, got {len(snapshots)}"

        # Verify continuous sequence
        for i in range(1, len(snapshots)):
            expected_id = snapshots[i - 1].snapshot_id + 1
            actual_id = snapshots[i].snapshot_id
            assert actual_id == expected_id, (
                f"Snapshot IDs not continuous: expected {expected_id}, got {actual_id}"
            )

    finally:
        engine.stop()
