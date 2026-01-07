"""
CLI UI - Minimal read-only display
Displays snapshot status in a single line
"""
import time
import sys
from typing import Optional

from src.datahub import DataHub
from src.snapshot import SnapshotDTO


class MinimalCLI:
    """
    Minimal CLI that reads and displays snapshots.

    V1a.1 Slice 1: Read-only, no commands yet.
    Displays snapshot status at fixed interval.
    """

    def __init__(self, datahub: DataHub, display_interval_ms: int = 500):
        self.datahub = datahub
        self.display_interval_ms = display_interval_ms
        self._running = False

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

        # Single-line status display (J2: nested fields)
        status_line = (
            f"[{snapshot.snapshot_id:05d}] "
            f"allowed={str(snapshot.gates.allowed):5s} | "
            f"intent={snapshot.controls.intent:5s} | "
            f"arm={str(snapshot.controls.arm):5s} | "
            f"cycle={snapshot.loop.cycle_ms:3d}ms | "
            f"reasons={reasons}"
        )

        # Pad to clear previous line content
        status_line = status_line.ljust(120)

        print(f"\r{status_line}", end="", flush=True)

    def stop(self) -> None:
        """Stop the CLI display loop."""
        self._running = False
