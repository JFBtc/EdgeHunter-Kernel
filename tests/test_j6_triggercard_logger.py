"""
Tests for V1a J6 - TriggerCards Logger

Validates:
- JSONL append-only format
- Crash tolerance (parseable except possibly last truncated line)
- Fixed cadence (1 Hz) independent of engine loop speed
- File rotation by local date + run_id
- Schema version "triggercard.v1"
- Snapshot reference (latest snapshot_id)
"""
import json
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.triggercard_logger import TriggerCard, TriggerCardLogger
from src.snapshot import SnapshotDTO
from src.datahub import DataHub
from src.engine import EngineLoop


class FrozenClock:
    """Deterministic clock for testing."""

    def __init__(self, unix_ms: int, mono_ns: int, local_dt: datetime):
        self._unix_ms = unix_ms
        self._mono_ns = mono_ns
        self._local_dt = local_dt

    def now_unix_ms(self) -> int:
        return self._unix_ms

    def now_mono_ns(self) -> int:
        return self._mono_ns

    def now_local(self) -> datetime:
        return self._local_dt

    def now_utc(self) -> datetime:
        return datetime.fromtimestamp(self._unix_ms / 1000, tz=timezone.utc)


def _make_snapshot(snapshot_id: int, ts_unix_ms: int, ready: bool, reasons: list[str]) -> SnapshotDTO:
    """Helper to create a minimal snapshot for testing."""
    return SnapshotDTO(
        schema_version="snapshot.v1",
        run_id="test-run-123",
        snapshot_id=snapshot_id,
        ts_unix_ms=ts_unix_ms,
        ts_mono_ns=ts_unix_ms * 1_000_000,
        ready=ready,
        ready_reasons=reasons,
    )


def test_j6_triggercard_schema_version():
    """Test that TriggerCard has schema_version == 'triggercard.v1'."""
    card = TriggerCard(
        schema_version="triggercard.v1",
        run_id="test-run",
        ts_unix_ms=1000,
        snapshot_id=1,
        ready=True,
        ready_reasons=[],
    )

    assert card.schema_version == "triggercard.v1"
    assert card.to_dict()["schema_version"] == "triggercard.v1"


def test_j6_triggercard_to_dict():
    """Test TriggerCard serialization to dict."""
    card = TriggerCard(
        schema_version="triggercard.v1",
        run_id="test-run-456",
        ts_unix_ms=1234567890,
        snapshot_id=42,
        ready=False,
        ready_reasons=["ARM_OFF", "INTENT_FLAT"],
    )

    d = card.to_dict()

    assert d["schema_version"] == "triggercard.v1"
    assert d["run_id"] == "test-run-456"
    assert d["ts_unix_ms"] == 1234567890
    assert d["snapshot_id"] == 42
    assert d["ready"] is False
    assert d["ready_reasons"] == ["ARM_OFF", "INTENT_FLAT"]


def test_j6_jsonl_append_only():
    """Test that logger writes JSONL append-only (one line per emit)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1000,  # High rate to emit every tick
        )

        # Create snapshots
        snapshot1 = _make_snapshot(1, 1000, True, [])
        snapshot2 = _make_snapshot(2, 2000, False, ["ARM_OFF"])

        # Emit two cards (use proper nanosecond scale)
        logger.tick(1_000_000_000, snapshot1)  # 1 second in ns
        logger.tick(2_000_000_000, snapshot2)  # 2 seconds in ns
        logger.close()

        # Read JSONL file
        files = list(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 1

        with open(files[0], "r") as f:
            lines = f.readlines()

        # Verify 2 lines
        assert len(lines) == 2

        # Parse each line
        card1 = json.loads(lines[0])
        card2 = json.loads(lines[1])

        assert card1["schema_version"] == "triggercard.v1"
        assert card1["snapshot_id"] == 1
        assert card1["ready"] is True

        assert card2["schema_version"] == "triggercard.v1"
        assert card2["snapshot_id"] == 2
        assert card2["ready"] is False
        assert card2["ready_reasons"] == ["ARM_OFF"]


def test_j6_crash_tolerance_truncated_last_line():
    """
    Test crash tolerance: file remains parseable except possibly last line.

    Simulates a crash by manually appending a partial JSON line.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1000,
        )

        # Write 3 complete cards
        for i in range(1, 4):
            snapshot = _make_snapshot(i, i * 1000, True, [])
            logger.tick(i * 1_000_000_000, snapshot)  # Proper nanosecond scale

        logger.close()

        # Get file path
        files = list(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 1
        filepath = files[0]

        # Simulate crash: append partial JSON
        with open(filepath, "a") as f:
            f.write('{"schema_version":"triggercard.v1","run_id":"test')  # Incomplete

        # Parse file (tolerant parser)
        valid_cards = []
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    card = json.loads(line)
                    valid_cards.append(card)
                except json.JSONDecodeError:
                    # Last truncated line - skip
                    break

        # Should successfully parse first 3 complete lines
        assert len(valid_cards) == 3
        assert valid_cards[0]["snapshot_id"] == 1
        assert valid_cards[1]["snapshot_id"] == 2
        assert valid_cards[2]["snapshot_id"] == 3


def test_j6_fixed_cadence_1hz():
    """Test fixed 1 Hz cadence (emit once per second regardless of tick rate)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1.0,  # 1 Hz = emit every 1 second
        )

        snapshot = _make_snapshot(1, 1000, True, [])

        # Tick many times within 1 second - should only emit once
        for i in range(10):
            mono_ns = i * 50_000_000  # 50ms intervals (0, 50ms, 100ms, ..., 450ms)
            logger.tick(mono_ns, snapshot)

        # Tick at 1 second - should emit second time
        logger.tick(1_000_000_000, snapshot)

        # Tick at 1.5 seconds - should NOT emit yet
        logger.tick(1_500_000_000, snapshot)

        # Tick at 2 seconds - should emit third time
        logger.tick(2_000_000_000, snapshot)

        logger.close()

        # Read file
        files = list(Path(tmpdir).glob("*.jsonl"))
        with open(files[0], "r") as f:
            lines = f.readlines()

        # Should have exactly 3 emissions (at 0s, 1s, 2s)
        assert len(lines) == 3


def test_j6_cadence_decoupled_from_loop_speed():
    """Test that cadence is independent of engine loop speed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=2.0,  # 2 Hz = emit every 500ms
        )

        snapshot = _make_snapshot(1, 1000, True, [])

        # Simulate fast engine loop (10 Hz = 100ms per cycle)
        # Over 1.5 seconds, engine runs 15 cycles
        # But logger should only emit 3 times (at 0s, 0.5s, 1.0s)
        emit_count = 0
        for cycle in range(15):
            mono_ns = cycle * 100_000_000  # 100ms per cycle
            logger.tick(mono_ns, snapshot)

        logger.close()

        # Read emissions
        files = list(Path(tmpdir).glob("*.jsonl"))
        with open(files[0], "r") as f:
            lines = f.readlines()

        # Should have 3-4 emissions depending on boundary (0ms, 500ms, 1000ms, possibly 1400ms)
        # With 2 Hz and last tick at 1400ms, we expect 3 emissions (0, 500, 1000)
        assert len(lines) == 3


def test_j6_file_rotation_by_date():
    """Test file rotation when local date changes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Day 1: 2024-01-15
        clock1 = FrozenClock(
            unix_ms=1705334400000,  # 2024-01-15 12:00:00 UTC
            mono_ns=1_000_000_000,
            local_dt=datetime(2024, 1, 15, 12, 0, 0),
        )

        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1000,  # High rate to emit every tick
            clock=clock1,
        )

        snapshot1 = _make_snapshot(1, 1000, True, [])
        logger.tick(1_000_000_000, snapshot1)

        # Day 2: 2024-01-16 (simulate date change)
        clock2 = FrozenClock(
            unix_ms=1705420800000,  # 2024-01-16 12:00:00 UTC
            mono_ns=2_000_000_000,
            local_dt=datetime(2024, 1, 16, 12, 0, 0),
        )
        logger.clock = clock2

        snapshot2 = _make_snapshot(2, 2000, False, ["ARM_OFF"])
        logger.tick(2_000_000_000, snapshot2)

        logger.close()

        # Should have 2 files (one per date)
        files = sorted(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 2

        # Verify filenames contain correct dates
        assert "2024-01-15" in files[0].name
        assert "2024-01-16" in files[1].name

        # Verify run_id in filenames
        assert "test-run" in files[0].name
        assert "test-run" in files[1].name

        # Verify content in each file
        with open(files[0], "r") as f:
            lines1 = f.readlines()
        assert len(lines1) == 1
        card1 = json.loads(lines1[0])
        assert card1["snapshot_id"] == 1

        with open(files[1], "r") as f:
            lines2 = f.readlines()
        assert len(lines2) == 1
        card2 = json.loads(lines2[0])
        assert card2["snapshot_id"] == 2


def test_j6_snapshot_reference():
    """Test that each TriggerCard references the latest snapshot_id."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1000,
        )

        # Emit cards with increasing snapshot_ids
        for i in range(1, 6):
            snapshot = _make_snapshot(i, i * 1000, True, [])
            logger.tick(i * 1_000_000_000, snapshot)  # Proper nanosecond scale

        logger.close()

        # Read and verify
        files = list(Path(tmpdir).glob("*.jsonl"))
        with open(files[0], "r") as f:
            lines = f.readlines()

        assert len(lines) == 5

        for i, line in enumerate(lines, start=1):
            card = json.loads(line)
            assert card["snapshot_id"] == i


def test_j6_no_snapshot_skips_emit():
    """Test that logger skips emission when snapshot is None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1000,
        )

        # Tick with None snapshot (before engine publishes first snapshot)
        logger.tick(1_000_000_000, None)
        logger.tick(2_000_000_000, None)

        # Now tick with valid snapshot
        snapshot = _make_snapshot(1, 3000, True, [])
        logger.tick(3_000_000_000, snapshot)

        logger.close()

        # Should only have 1 emission (skipped first 2 with None)
        files = list(Path(tmpdir).glob("*.jsonl"))
        with open(files[0], "r") as f:
            lines = f.readlines()

        assert len(lines) == 1
        card = json.loads(lines[0])
        assert card["snapshot_id"] == 1


def test_j6_ready_reasons_preserved():
    """Test that ready_reasons are correctly copied to TriggerCard."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1000,
        )

        # Snapshot with multiple reason codes
        snapshot = _make_snapshot(
            1,
            1000,
            False,
            ["ARM_OFF", "INTENT_FLAT", "OUTSIDE_OPERATING_WINDOW"],
        )
        logger.tick(1_000_000_000, snapshot)

        logger.close()

        # Verify
        files = list(Path(tmpdir).glob("*.jsonl"))
        with open(files[0], "r") as f:
            card = json.loads(f.readline())

        assert card["ready"] is False
        assert card["ready_reasons"] == ["ARM_OFF", "INTENT_FLAT", "OUTSIDE_OPERATING_WINDOW"]


def test_j6_engine_integration():
    """
    Test TriggerCard logger integration with engine.

    Validates:
    - Logger receives tick() calls from engine
    - Cadence control works with real engine
    - Files are created with correct naming
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        datahub = DataHub()
        logger = TriggerCardLogger(
            run_id="engine-test-run",
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
            time.sleep(0.6)  # Run for 600ms

        finally:
            engine.stop()

        # Logger should have emitted ~3 cards (at 0ms, 200ms, 400ms)
        files = list(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 1

        with open(files[0], "r") as f:
            lines = f.readlines()

        # Should have 2-4 emissions (depending on timing)
        assert 2 <= len(lines) <= 4

        # Verify all cards are valid JSON with correct schema
        for line in lines:
            card = json.loads(line)
            assert card["schema_version"] == "triggercard.v1"
            assert card["run_id"] == "engine-test-run"
            assert card["snapshot_id"] > 0


def test_j6_filename_format():
    """Test that filename follows format: triggercards_{date}_{run_id}.jsonl."""
    with tempfile.TemporaryDirectory() as tmpdir:
        clock = FrozenClock(
            unix_ms=1705334400000,
            mono_ns=1_000_000_000,
            local_dt=datetime(2024, 1, 15, 12, 0, 0),
        )

        logger = TriggerCardLogger(
            run_id="my-run-xyz",
            log_dir=tmpdir,
            cadence_hz=1000,
            clock=clock,
        )

        snapshot = _make_snapshot(1, 1000, True, [])
        logger.tick(1_000_000_000, snapshot)
        logger.close()

        files = list(Path(tmpdir).glob("*.jsonl"))
        assert len(files) == 1

        filename = files[0].name
        assert filename == "triggercards_2024-01-15_my-run-xyz.jsonl"


def test_j6_empty_ready_reasons():
    """Test that empty ready_reasons serializes as empty list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = TriggerCardLogger(
            run_id="test-run",
            log_dir=tmpdir,
            cadence_hz=1000,
        )

        # Snapshot with ready=True and empty reasons
        snapshot = _make_snapshot(1, 1000, True, [])
        logger.tick(1_000_000_000, snapshot)

        logger.close()

        files = list(Path(tmpdir).glob("*.jsonl"))
        with open(files[0], "r") as f:
            card = json.loads(f.readline())

        assert card["ready"] is True
        assert card["ready_reasons"] == []
