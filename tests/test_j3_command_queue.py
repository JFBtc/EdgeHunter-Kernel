"""
Tests for V1a J3 - CommandQueue (Intent/ARM)

Validates:
- Bounded queue mechanics
- Command push/drain
- Last-write-wins coalescing
- Cycle boundary application
- Command tracking (last_cmd_id, last_cmd_ts_unix_ms)
"""
import time
import queue
import pytest

from src.command_queue import ArmCommand, CommandQueue, CoalescedBatch, IntentCommand
from src.datahub import DataHub
from src.engine import EngineLoop


class FrozenClock:
    """Deterministic clock for testing."""

    def __init__(self, unix_ms: int, mono_ns: int):
        from datetime import datetime, timezone
        self._unix_ms = unix_ms
        self._mono_ns = mono_ns
        self._dt = datetime.fromtimestamp(unix_ms / 1000, tz=timezone.utc)

    def now_unix_ms(self) -> int:
        return self._unix_ms

    def now_mono_ns(self) -> int:
        return self._mono_ns

    def now_local(self):
        from datetime import datetime
        return datetime.now().astimezone()

    def now_utc(self):
        return self._dt


def test_command_queue_push_drain():
    """Test command queue push/drain mechanics."""
    cmd_queue = CommandQueue(maxsize=10)

    # Push Intent command
    cmd1 = IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG")
    cmd_queue.push(cmd1)

    # Push ARM command
    cmd2 = ArmCommand(cmd_id=2, ts_unix_ms=2000, arm=True)
    cmd_queue.push(cmd2)

    # Drain commands
    batch = cmd_queue.drain()

    assert batch.intent == "LONG"
    assert batch.arm is True
    assert batch.last_cmd_id == 2  # Last command ID
    assert batch.last_cmd_ts_unix_ms == 2000


def test_command_queue_bounded():
    """Test bounded queue overflow (J3 requirement)."""
    cmd_queue = CommandQueue(maxsize=2)

    cmd1 = IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG")
    cmd2 = IntentCommand(cmd_id=2, ts_unix_ms=2000, intent="SHORT")

    # Fill queue
    cmd_queue.push(cmd1)
    cmd_queue.push(cmd2)

    # Third push should raise Full
    cmd3 = IntentCommand(cmd_id=3, ts_unix_ms=3000, intent="FLAT")
    with pytest.raises(queue.Full):
        cmd_queue.push(cmd3)


def test_command_queue_coalescing_last_write_wins():
    """Test last-write-wins coalescing for Intent and ARM."""
    cmd_queue = CommandQueue(maxsize=100)

    # Push multiple Intent commands
    cmd_queue.push(IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG"))
    cmd_queue.push(IntentCommand(cmd_id=2, ts_unix_ms=2000, intent="SHORT"))
    cmd_queue.push(IntentCommand(cmd_id=3, ts_unix_ms=3000, intent="FLAT"))

    # Push multiple ARM commands
    cmd_queue.push(ArmCommand(cmd_id=4, ts_unix_ms=4000, arm=True))
    cmd_queue.push(ArmCommand(cmd_id=5, ts_unix_ms=5000, arm=False))

    # Drain and coalesce
    batch = cmd_queue.drain()

    # Only last values should be kept
    assert batch.intent == "FLAT"  # Last Intent
    assert batch.arm is False  # Last ARM
    assert batch.last_cmd_id == 5  # Last command overall
    assert batch.last_cmd_ts_unix_ms == 5000


def test_command_queue_coalescing_intent_only():
    """Test coalescing with only Intent commands."""
    cmd_queue = CommandQueue(maxsize=100)

    cmd_queue.push(IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG"))
    cmd_queue.push(IntentCommand(cmd_id=2, ts_unix_ms=2000, intent="SHORT"))

    batch = cmd_queue.drain()

    assert batch.intent == "SHORT"
    assert batch.arm is None  # No ARM commands
    assert batch.last_cmd_id == 2
    assert batch.last_cmd_ts_unix_ms == 2000


def test_command_queue_coalescing_arm_only():
    """Test coalescing with only ARM commands."""
    cmd_queue = CommandQueue(maxsize=100)

    cmd_queue.push(ArmCommand(cmd_id=1, ts_unix_ms=1000, arm=True))
    cmd_queue.push(ArmCommand(cmd_id=2, ts_unix_ms=2000, arm=False))

    batch = cmd_queue.drain()

    assert batch.intent is None  # No Intent commands
    assert batch.arm is False
    assert batch.last_cmd_id == 2
    assert batch.last_cmd_ts_unix_ms == 2000


def test_command_queue_empty_drain():
    """Test draining empty queue returns empty batch."""
    cmd_queue = CommandQueue(maxsize=100)

    batch = cmd_queue.drain()

    assert batch.intent is None
    assert batch.arm is None
    assert batch.last_cmd_id == 0
    assert batch.last_cmd_ts_unix_ms is None


def test_engine_applies_commands_at_boundary():
    """Test Engine applies commands ONLY at cycle boundary."""
    datahub = DataHub()
    cmd_queue = CommandQueue(maxsize=100)
    clock = FrozenClock(unix_ms=1000000, mono_ns=1000000000)
    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        command_queue=cmd_queue,
        clock=clock,
    )

    # Enqueue commands BEFORE engine starts
    cmd_queue.push(IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG"))
    cmd_queue.push(ArmCommand(cmd_id=2, ts_unix_ms=2000, arm=True))

    # Commands should NOT be applied yet
    assert engine._intent == "FLAT"  # Default
    assert engine._arm is False  # Default
    assert engine._last_cmd_id == 0

    # Run one cycle manually
    engine._run_cycle_once()

    # Commands should NOW be applied (at boundary)
    assert engine._intent == "LONG"
    assert engine._arm is True
    assert engine._last_cmd_id == 2
    assert engine._last_cmd_ts_unix_ms == 2000

    # Verify snapshot reflects applied commands
    snapshot = datahub.get_latest()
    assert snapshot is not None
    assert snapshot.controls.intent == "LONG"
    assert snapshot.controls.arm is True
    assert snapshot.controls.last_cmd_id == 2
    assert snapshot.controls.last_cmd_ts_unix_ms == 2000


def test_engine_coalesces_commands_at_boundary():
    """Test Engine coalesces multiple commands with last-write-wins."""
    datahub = DataHub()
    cmd_queue = CommandQueue(maxsize=100)
    clock = FrozenClock(unix_ms=1000000, mono_ns=1000000000)
    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        command_queue=cmd_queue,
        clock=clock,
    )

    # Enqueue multiple commands in same cycle window
    cmd_queue.push(IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG"))
    cmd_queue.push(IntentCommand(cmd_id=2, ts_unix_ms=2000, intent="SHORT"))
    cmd_queue.push(IntentCommand(cmd_id=3, ts_unix_ms=3000, intent="FLAT"))
    cmd_queue.push(ArmCommand(cmd_id=4, ts_unix_ms=4000, arm=True))
    cmd_queue.push(ArmCommand(cmd_id=5, ts_unix_ms=5000, arm=False))

    # Run one cycle
    engine._run_cycle_once()

    # Only last values should be applied
    assert engine._intent == "FLAT"
    assert engine._arm is False
    assert engine._last_cmd_id == 5
    assert engine._last_cmd_ts_unix_ms == 5000

    # Verify snapshot
    snapshot = datahub.get_latest()
    assert snapshot.controls.intent == "FLAT"
    assert snapshot.controls.arm is False
    assert snapshot.controls.last_cmd_id == 5
    assert snapshot.controls.last_cmd_ts_unix_ms == 5000


def test_engine_no_commands_preserves_state():
    """Test Engine preserves state when no commands are enqueued."""
    datahub = DataHub()
    cmd_queue = CommandQueue(maxsize=100)
    clock = FrozenClock(unix_ms=1000000, mono_ns=1000000000)
    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        command_queue=cmd_queue,
        clock=clock,
    )

    # Set initial state via first cycle
    cmd_queue.push(IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG"))
    cmd_queue.push(ArmCommand(cmd_id=2, ts_unix_ms=2000, arm=True))
    engine._run_cycle_once()

    assert engine._intent == "LONG"
    assert engine._arm is True
    assert engine._last_cmd_id == 2

    # Run second cycle with NO new commands
    engine._run_cycle_once()

    # State should be preserved
    assert engine._intent == "LONG"
    assert engine._arm is True
    assert engine._last_cmd_id == 2  # Unchanged


def test_engine_no_command_queue_preserves_defaults():
    """Test Engine works without CommandQueue (backward compatibility)."""
    datahub = DataHub()
    clock = FrozenClock(unix_ms=1000000, mono_ns=1000000000)
    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        command_queue=None,  # No command queue
        clock=clock,
    )

    # Run cycle
    engine._run_cycle_once()

    # Defaults should be preserved
    assert engine._intent == "FLAT"
    assert engine._arm is False
    assert engine._last_cmd_id == 0
    assert engine._last_cmd_ts_unix_ms is None

    # Verify snapshot
    snapshot = datahub.get_latest()
    assert snapshot.controls.intent == "FLAT"
    assert snapshot.controls.arm is False
    assert snapshot.controls.last_cmd_id == 0
    assert snapshot.controls.last_cmd_ts_unix_ms is None


def test_command_frozen():
    """Test commands are immutable (frozen dataclasses)."""
    cmd = IntentCommand(cmd_id=1, ts_unix_ms=1000, intent="LONG")

    with pytest.raises(Exception):  # FrozenInstanceError
        cmd.intent = "SHORT"  # type: ignore


def test_coalesced_batch_frozen():
    """Test CoalescedBatch is immutable."""
    batch = CoalescedBatch(intent="LONG", arm=True, last_cmd_id=1, last_cmd_ts_unix_ms=1000)

    with pytest.raises(Exception):  # FrozenInstanceError
        batch.intent = "SHORT"  # type: ignore
