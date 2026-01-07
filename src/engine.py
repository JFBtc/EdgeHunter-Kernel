"""
Engine Loop - Single-writer kernel loop
Publishes atomic snapshots at fixed frequency (10 Hz default)
"""
import time
import threading
import uuid
from typing import Optional

from src.snapshot import SnapshotDTO
from src.datahub import DataHub


class EngineLoop:
    """
    Single-writer engine loop that publishes atomic snapshots.

    V1a.1 Slice 1: Minimal loop without feed, gates, or commands.
    Just publishes snapshots with monotonic IDs at fixed frequency.
    """

    def __init__(
        self,
        datahub: DataHub,
        cycle_target_ms: int = 100,  # 10 Hz
        overrun_threshold_ms: int = 500,
    ):
        self.datahub = datahub
        self.cycle_target_ms = cycle_target_ms
        self.overrun_threshold_ms = overrun_threshold_ms

        # Run identity
        self.run_id = str(uuid.uuid4())

        # State
        self._snapshot_id = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Controls (placeholders for Slice 1)
        self._intent = "FLAT"
        self._arm = False

    def start(self) -> None:
        """Start the engine loop in a background thread."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the engine loop gracefully."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run_loop(self) -> None:
        """
        Main engine loop: publish snapshot at fixed frequency.

        V1a.1 Slice 1: No events, no commands, no gates yet.
        Just publishes snapshots with monotonic IDs and loop health.
        """
        while self._running:
            cycle_start_ns = time.perf_counter_ns()
            cycle_start_ms = int(time.time() * 1000)

            # Increment snapshot ID (monotonic)
            self._snapshot_id += 1

            # Compute loop health
            cycle_ms = 0  # Will be computed after work
            engine_degraded = False

            # Build and publish snapshot (atomic)
            snapshot = SnapshotDTO(
                schema_version="snapshot.v1",
                run_id=self.run_id,
                snapshot_id=self._snapshot_id,
                ts_unix_ms=cycle_start_ms,
                intent=self._intent,
                arm=self._arm,
                allowed=False,  # V1a.1 Slice 1: no gates yet, always False
                reason_codes=["ARM_OFF", "INTENT_FLAT"],  # Placeholder
                cycle_ms=cycle_ms,
                engine_degraded=engine_degraded,
                bid=None,
                ask=None,
                last=None,
                spread_ticks=None,
                staleness_ms=None,
                extras={},
            )

            self.datahub.publish(snapshot)

            # Compute cycle time and sleep
            cycle_end_ns = time.perf_counter_ns()
            cycle_elapsed_ms = (cycle_end_ns - cycle_start_ns) // 1_000_000

            # Check for overrun
            if cycle_elapsed_ms > self.overrun_threshold_ms:
                engine_degraded = True

            # Sleep to maintain target frequency
            sleep_ms = max(0, self.cycle_target_ms - cycle_elapsed_ms)
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
