"""
CommandQueue: Bounded queue for UI→Engine commands (Intent/ARM).

V1a-J3: UI writes commands to queue; Engine drains at cycle boundary with
last-write-wins coalescing.
"""

import queue
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class IntentCommand:
    """Command to update Intent."""
    cmd_id: int
    ts_unix_ms: int
    intent: str  # LONG | SHORT | BOTH | FLAT


@dataclass(frozen=True)
class ArmCommand:
    """Command to update ARM."""
    cmd_id: int
    ts_unix_ms: int
    arm: bool


@dataclass(frozen=True)
class CoalescedBatch:
    """Coalesced command batch for a single cycle."""
    intent: Optional[str] = None
    arm: Optional[bool] = None
    last_cmd_id: int = 0
    last_cmd_ts_unix_ms: Optional[int] = None


class CommandQueue:
    """
    Bounded queue for UI→Engine commands (Intent/ARM).

    - Bounded capacity (default 100)
    - Thread-safe push from UI
    - Drain returns coalesced batch (last-write-wins for Intent/ARM)
    - Preserves last command identity (id + timestamp)
    """

    def __init__(self, maxsize: int = 100):
        """
        Create bounded command queue.

        Args:
            maxsize: Maximum queue capacity (default 100)
        """
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)

    def push(self, cmd: IntentCommand | ArmCommand) -> None:
        """
        Push command from UI (non-blocking).

        Args:
            cmd: IntentCommand or ArmCommand

        Raises:
            queue.Full: If queue is at capacity
        """
        self._queue.put_nowait(cmd)

    def drain(self) -> CoalescedBatch:
        """
        Drain all commands and coalesce with last-write-wins.

        Engine calls this at cycle boundary. For Intent and ARM, only the
        most recent value before the boundary is kept. Returns identity of
        the last applied command (id + timestamp).

        Returns:
            CoalescedBatch with last values and command tracking
        """
        intent: Optional[str] = None
        arm: Optional[bool] = None
        last_cmd_id: int = 0
        last_cmd_ts_unix_ms: Optional[int] = None

        commands = []
        while True:
            try:
                cmd = self._queue.get_nowait()
                commands.append(cmd)
            except queue.Empty:
                break

        # Coalesce: last-write-wins for each control type
        for cmd in commands:
            if isinstance(cmd, IntentCommand):
                intent = cmd.intent
                last_cmd_id = cmd.cmd_id
                last_cmd_ts_unix_ms = cmd.ts_unix_ms
            elif isinstance(cmd, ArmCommand):
                arm = cmd.arm
                last_cmd_id = cmd.cmd_id
                last_cmd_ts_unix_ms = cmd.ts_unix_ms

        return CoalescedBatch(
            intent=intent,
            arm=arm,
            last_cmd_id=last_cmd_id,
            last_cmd_ts_unix_ms=last_cmd_ts_unix_ms,
        )
