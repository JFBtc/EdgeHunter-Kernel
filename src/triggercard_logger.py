"""
TriggerCards Logger - V1a J6

JSONL append-only logger with:
- Fixed cadence (1 Hz default) decoupled from engine loop
- Crash-tolerant (parseable except possibly last truncated line)
- Rotation by local date + run_id
- Schema version: triggercard.v1
"""
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.clock import ClockProtocol, SystemClock
from src.snapshot import SnapshotDTO


@dataclass
class TriggerCard:
    """
    TriggerCard DTO - minimal snapshot reference for logging.

    Schema version: triggercard.v1
    """
    schema_version: str = "triggercard.v1"
    run_id: str = ""
    ts_unix_ms: int = 0
    snapshot_id: int = 0
    ready: bool = False
    ready_reasons: list[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "ts_unix_ms": self.ts_unix_ms,
            "snapshot_id": self.snapshot_id,
            "ready": self.ready,
            "ready_reasons": self.ready_reasons or [],
        }


class TriggerCardLogger:
    """
    JSONL append-only logger for TriggerCards.

    Features:
    - Fixed cadence (1 Hz default) independent of engine loop speed
    - Crash-tolerant: file remains parseable except possibly last line
    - Rotation by local date + run_id
    - No background threads (tick-based cadence control)

    Usage:
        logger = TriggerCardLogger(run_id="abc123", log_dir="./logs")
        # Each engine cycle:
        logger.tick(now_mono_ns, latest_snapshot)
    """

    def __init__(
        self,
        run_id: str,
        log_dir: str = "./logs/triggercards",
        cadence_hz: float = 1.0,
        clock: Optional[ClockProtocol] = None,
    ):
        """
        Initialize TriggerCard logger.

        Args:
            run_id: Unique run identifier
            log_dir: Directory for log files
            cadence_hz: Emission rate in Hz (default 1.0)
            clock: Clock for time/date (default SystemClock)
        """
        self.run_id = run_id
        self.log_dir = Path(log_dir)
        self.cadence_interval_ns = int(1_000_000_000 / cadence_hz)  # Convert Hz to nanoseconds
        self.clock = clock or SystemClock()

        # Cadence control
        self._last_emit_mono_ns: Optional[int] = None

        # File rotation state
        self._current_file: Optional[object] = None  # File handle
        self._current_date: Optional[str] = None  # YYYY-MM-DD

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def tick(self, now_mono_ns: int, snapshot: Optional[SnapshotDTO]) -> None:
        """
        Called each engine cycle. Emits TriggerCard if cadence interval elapsed.

        Args:
            now_mono_ns: Current monotonic time in nanoseconds
            snapshot: Latest published snapshot (or None if no snapshot yet)
        """
        # Check if we should emit (cadence control)
        if not self._should_emit(now_mono_ns):
            return

        # Skip if no snapshot available yet
        if snapshot is None:
            return

        # Check/rotate file if date changed
        self._check_rotation()

        # Create TriggerCard from snapshot
        card = TriggerCard(
            schema_version="triggercard.v1",
            run_id=self.run_id,
            ts_unix_ms=snapshot.ts_unix_ms,
            snapshot_id=snapshot.snapshot_id,
            ready=snapshot.ready,
            ready_reasons=snapshot.ready_reasons.copy() if snapshot.ready_reasons else [],
        )

        # Write to JSONL (one line, flushed immediately)
        self._write_card(card)

        # Update last emit time
        self._last_emit_mono_ns = now_mono_ns

    def _should_emit(self, now_mono_ns: int) -> bool:
        """Check if enough time elapsed since last emit."""
        if self._last_emit_mono_ns is None:
            return True  # First emit

        elapsed_ns = now_mono_ns - self._last_emit_mono_ns
        return elapsed_ns >= self.cadence_interval_ns

    def _check_rotation(self) -> None:
        """Check if date changed and rotate file if needed."""
        local_date = self._get_local_date()

        if local_date != self._current_date:
            # Close current file if open
            if self._current_file is not None:
                self._current_file.close()
                self._current_file = None

            # Open new file for new date
            self._current_date = local_date
            filepath = self._get_filepath(local_date)
            self._current_file = open(filepath, "a", encoding="utf-8")

    def _get_local_date(self) -> str:
        """Get current local date as YYYY-MM-DD string."""
        now_local = self.clock.now_local()
        return now_local.strftime("%Y-%m-%d")

    def _get_filepath(self, local_date: str) -> Path:
        """Get filepath for given date and run_id."""
        filename = f"triggercards_{local_date}_{self.run_id}.jsonl"
        return self.log_dir / filename

    def _write_card(self, card: TriggerCard) -> None:
        """Write TriggerCard to JSONL file (one line, flushed)."""
        if self._current_file is None:
            raise RuntimeError("File not opened (call _check_rotation first)")

        # Serialize to JSON (single line)
        json_line = json.dumps(card.to_dict(), separators=(',', ':'))

        # Write + newline
        self._current_file.write(json_line)
        self._current_file.write('\n')

        # Flush immediately for crash tolerance
        self._current_file.flush()
        os.fsync(self._current_file.fileno())

    def close(self) -> None:
        """Close current file if open."""
        if self._current_file is not None:
            self._current_file.close()
            self._current_file = None

    def __del__(self):
        """Ensure file is closed on cleanup."""
        self.close()
