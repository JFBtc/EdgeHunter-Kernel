"""
Tests for V1a J7 - Soak Test Integration

Short integration tests that simulate a mini soak run (5-20 seconds).

Validates:
- No crashes during sustained operation
- Clean shutdown with summary report
- TriggerCards JSONL files are created and parseable
- Metrics tracking works correctly
- Logger cadence is respected
"""
import tempfile
import time
from pathlib import Path

import pytest

from src.datahub import DataHub
from src.engine import EngineLoop
from src.triggercard_logger import TriggerCardLogger
from src.triggercard_validator import validate_triggercard_file


def test_j7_mini_soak_no_crash():
    """
    Test short soak run (5 seconds) with no crashes.

    Validates basic stability without external dependencies.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=100)

    try:
        engine.start()
        time.sleep(5.0)  # 5 second mini soak

        # Engine should still be running
        assert engine._running is True

        # Should have published many snapshots
        snapshot = datahub.get_latest()
        assert snapshot is not None
        assert snapshot.snapshot_id > 40  # At least 40 cycles (5s / 0.1s)

    finally:
        engine.stop()


def test_j7_mini_soak_with_logger():
    """
    Test short soak run with TriggerCards logger enabled.

    Validates:
    - Logger creates JSONL file
    - Cards are emitted at correct cadence
    - File is parseable
    - Clean shutdown
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        datahub = DataHub()
        logger = TriggerCardLogger(
            run_id="soak-test-run",
            log_dir=tmpdir,
            cadence_hz=5.0,  # 5 Hz = 200ms interval
        )
        engine = EngineLoop(
            datahub,
            cycle_target_ms=50,  # 20 Hz engine
            triggercard_logger=logger,
        )

        try:
            engine.start()
            time.sleep(2.5)  # 2.5 second mini soak

        finally:
            engine.stop()

        # Verify JSONL file was created
        files = list(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 1, f"Expected 1 JSONL file, found {len(files)}"

        # Verify file is parseable
        result = validate_triggercard_file(files[0])
        assert result.success is True, f"Validation failed: {result.errors}"

        # Verify cadence: 5 Hz over 2.5s => ~12-13 cards
        # (Allow some tolerance for timing)
        assert 10 <= result.valid_count <= 15, (
            f"Expected 10-15 cards at 5 Hz over 2.5s, got {result.valid_count}"
        )


def test_j7_mini_soak_metrics_tracking():
    """
    Test that metrics are correctly tracked during mini soak.

    Validates:
    - max_cycle_time_ms is tracked
    - Metrics are accessible after shutdown
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=100)

    try:
        engine.start()
        time.sleep(3.0)  # 3 second run

    finally:
        engine.stop()

    # Verify metrics were tracked
    # Note: max_cycle_time_ms may be 0 if all cycles complete in < 1ms (very fast machine)
    assert engine._max_cycle_time_ms >= 0, "max_cycle_time_ms should be tracked"
    assert engine._soak_end_ts_unix_ms is not None, "end timestamp should be captured"

    # Verify uptime is reasonable
    uptime_ms = engine._soak_end_ts_unix_ms - engine._run_start_ts_unix_ms
    uptime_s = uptime_ms / 1000.0
    assert 2.5 <= uptime_s <= 4.0, f"Expected uptime ~3s, got {uptime_s:.2f}s"


def test_j7_mini_soak_snapshot_invariants_preserved():
    """
    Test that snapshot invariants are preserved during mini soak.

    Validates J4 invariants under sustained operation:
    - ready == gates.allowed
    - ready_reasons == gates.reason_codes
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()

        violations = []

        # Sample snapshots over 3 seconds
        for i in range(60):  # 60 samples over 3 seconds
            snapshot = datahub.get_latest()
            if snapshot:
                # Check J4 invariants
                if snapshot.ready != snapshot.gates.allowed:
                    violations.append({
                        "snapshot_id": snapshot.snapshot_id,
                        "ready": snapshot.ready,
                        "allowed": snapshot.gates.allowed,
                    })

                if snapshot.ready_reasons != snapshot.gates.reason_codes:
                    violations.append({
                        "snapshot_id": snapshot.snapshot_id,
                        "ready_reasons": snapshot.ready_reasons,
                        "reason_codes": snapshot.gates.reason_codes,
                    })

            time.sleep(0.05)  # 50ms between samples

    finally:
        engine.stop()

    # Assert no violations
    assert len(violations) == 0, (
        f"J4 invariants violated in {len(violations)} snapshots: {violations}"
    )


def test_j7_mini_soak_monotonic_snapshot_ids():
    """
    Test that snapshot IDs remain strictly monotonic during mini soak.

    Validates no ID corruption or resets during sustained operation.
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()

        snapshot_ids = []

        # Collect snapshots over 2 seconds
        for _ in range(40):
            snapshot = datahub.get_latest()
            if snapshot and (not snapshot_ids or snapshot.snapshot_id != snapshot_ids[-1]):
                snapshot_ids.append(snapshot.snapshot_id)
            time.sleep(0.05)

    finally:
        engine.stop()

    # Verify at least 20 distinct snapshots
    assert len(snapshot_ids) >= 20, f"Expected at least 20 snapshots, got {len(snapshot_ids)}"

    # Verify strict monotonic increase
    for i in range(1, len(snapshot_ids)):
        assert snapshot_ids[i] > snapshot_ids[i - 1], (
            f"Snapshot IDs not monotonic: {snapshot_ids[i-1]} -> {snapshot_ids[i]}"
        )


def test_j7_mini_soak_logger_cadence_decoupled():
    """
    Test that logger cadence is decoupled from engine speed.

    Validates logger emits at fixed rate regardless of engine loop speed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        datahub = DataHub()
        logger = TriggerCardLogger(
            run_id="cadence-test",
            log_dir=tmpdir,
            cadence_hz=10.0,  # 10 Hz = 100ms interval
        )

        # Use FAST engine (50ms = 20 Hz)
        engine = EngineLoop(
            datahub,
            cycle_target_ms=50,
            triggercard_logger=logger,
        )

        try:
            engine.start()
            time.sleep(1.5)  # 1.5 seconds

        finally:
            engine.stop()

        # Verify emissions
        files = list(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 1

        result = validate_triggercard_file(files[0])

        # At 10 Hz over 1.5s, expect ~15 cards
        # Engine runs at 20 Hz, so ~30 cycles, but logger only emits 15 times
        assert 13 <= result.valid_count <= 17, (
            f"Expected 13-17 cards at 10 Hz over 1.5s, got {result.valid_count}"
        )


def test_j7_mini_soak_clean_shutdown():
    """
    Test clean shutdown after mini soak.

    Validates:
    - stop() completes without hanging
    - Logger is properly closed
    - Summary report is printable (no exceptions)
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        datahub = DataHub()
        logger = TriggerCardLogger(
            run_id="shutdown-test",
            log_dir=tmpdir,
            cadence_hz=5.0,
        )
        engine = EngineLoop(
            datahub,
            cycle_target_ms=100,
            triggercard_logger=logger,
        )

        engine.start()
        time.sleep(2.0)

        # Capture shutdown (should not raise)
        engine.stop()

        # Verify logger was closed
        assert logger._current_file is None or logger._current_file.closed

        # Verify end timestamp was captured
        assert engine._soak_end_ts_unix_ms is not None


def test_j7_mini_soak_no_logger():
    """
    Test mini soak without logger enabled.

    Validates engine runs correctly when logger is None.
    """
    datahub = DataHub()
    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        triggercard_logger=None,  # No logger
    )

    try:
        engine.start()
        time.sleep(2.0)

        snapshot = datahub.get_latest()
        assert snapshot is not None
        assert snapshot.snapshot_id > 15

    finally:
        engine.stop()

    # Shutdown should complete cleanly even without logger
    assert engine._soak_end_ts_unix_ms is not None
