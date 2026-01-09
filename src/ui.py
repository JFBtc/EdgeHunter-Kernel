"""
CLI UI - Minimal read-only display
Displays snapshot status in a single line
"""
import time
import sys
from typing import Optional

from src.command_queue import ArmCommand, CommandQueue, IntentCommand
from src.datahub import DataHub
from src.snapshot import SnapshotDTO


class MinimalCLI:
    """
    Minimal CLI that reads and displays snapshots.

    V1a-J3: Added command input via CommandQueue (Intent/ARM).
    UI writes ONLY to CommandQueue; no direct state mutation.
    """

    def __init__(
        self,
        datahub: DataHub,
        display_interval_ms: int = 500,
        command_queue: Optional[CommandQueue] = None,
    ):
        self.datahub = datahub
        self.display_interval_ms = display_interval_ms
        self.command_queue = command_queue
        self._running = False
        self._cmd_id_counter = 0

    def run(self, duration_seconds: Optional[float] = None) -> None:
        """
        Run the CLI display loop.

        Args:
            duration_seconds: How long to run in seconds (None = run until interrupted)
                             Uses monotonic time for accurate duration measurement.
        """
        self._running = True
        start_time_mono = time.perf_counter()

        print("EdgeHunter Core Kernel V1a.1 - Slice 1")
        print("=" * 80)
        if self.command_queue:
            print("Commands: i=Intent(LONG), f=Intent(FLAT), a=ARM(True), d=ARM(False)")
        print("Running... Press Ctrl+C to stop")
        print()

        try:
            while self._running:
                # Check duration limit using monotonic time
                if duration_seconds and (time.perf_counter() - start_time_mono) >= duration_seconds:
                    break

                snapshot = self.datahub.get_latest()
                self._display_snapshot(snapshot)

                time.sleep(self.display_interval_ms / 1000.0)

        except KeyboardInterrupt:
            print("\n\nShutdown requested...")
        finally:
            self._running = False

    def _display_snapshot(self, snapshot: Optional[SnapshotDTO]) -> None:
        """Display snapshot status in a single line."""
        if snapshot is None:
            print("\r[WAITING] No snapshot published yet" + " " * 40, end="", flush=True)
            return

        # Format reason codes (J2: nested in gates)
        reasons = ",".join(snapshot.gates.reason_codes) if snapshot.gates.reason_codes else "NONE"
        if len(reasons) > 30:
            reasons = reasons[:27] + "..."

        session_phase = snapshot.session.session_phase
        staleness = (
            f"{snapshot.quote.staleness_ms}ms"
            if snapshot.quote.staleness_ms is not None
            else "NA"
        )
        feed_state = "DEGRADED" if snapshot.feed.degraded else "OK"

        # Single-line status display (J2: nested fields)
        status_line = (
            f"[{snapshot.snapshot_id:05d}] "
            f"allowed={str(snapshot.gates.allowed):5s} | "
            f"intent={snapshot.controls.intent:5s} | "
            f"arm={str(snapshot.controls.arm):5s} | "
            f"cycle={snapshot.loop.cycle_ms:3d}ms | "
            f"session={session_phase:9s} | "
            f"stale={staleness:>6s} | "
            f"feed={feed_state:8s} | "
            f"reasons={reasons}"
        )

        # Pad to clear previous line content
        status_line = status_line.ljust(120)

        print(f"\r{status_line}", end="", flush=True)

    def stop(self) -> None:
        """Stop the CLI display loop."""
        self._running = False

    def send_intent_command(self, intent: str) -> None:
        """
        Send Intent command via CommandQueue (V1a-J3).

        Args:
            intent: LONG | SHORT | BOTH | FLAT
        """
        if not self.command_queue:
            return
        self._cmd_id_counter += 1
        cmd = IntentCommand(
            cmd_id=self._cmd_id_counter,
            ts_unix_ms=int(time.time() * 1000),
            intent=intent,
        )
        try:
            self.command_queue.push(cmd)
        except Exception:
            pass  # Queue full, skip silently

    def send_arm_command(self, arm: bool) -> None:
        """
        Send ARM command via CommandQueue (V1a-J3).

        Args:
            arm: True to arm, False to disarm
        """
        if not self.command_queue:
            return
        self._cmd_id_counter += 1
        cmd = ArmCommand(
            cmd_id=self._cmd_id_counter,
            ts_unix_ms=int(time.time() * 1000),
            arm=arm,
        )
        try:
            self.command_queue.push(cmd)
        except Exception:
            pass  # Queue full, skip silently
