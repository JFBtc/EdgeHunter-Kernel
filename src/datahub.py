"""
DataHub - Atomic snapshot publisher
Provides thread-safe copy-on-write snapshot publication
"""
import threading
from typing import Optional

from src.snapshot import SnapshotDTO


class DataHub:
    """
    Thread-safe atomic snapshot publisher using copy-on-write semantics.

    Invariants:
    - Engine loop (single writer) publishes new snapshots
    - UI/readers (multiple readers) read the latest snapshot atomically
    - Readers never observe partial state or mutations
    """

    def __init__(self):
        self._snapshot: Optional[SnapshotDTO] = None
        self._lock = threading.Lock()

    def publish(self, snapshot: SnapshotDTO) -> None:
        """
        Publish a new snapshot atomically (single writer: engine loop only).

        Args:
            snapshot: Immutable SnapshotDTO to publish
        """
        with self._lock:
            self._snapshot = snapshot

    def get_latest(self) -> Optional[SnapshotDTO]:
        """
        Get the latest published snapshot (read-only, multiple readers allowed).

        Returns:
            Latest snapshot or None if no snapshot published yet
        """
        with self._lock:
            return self._snapshot
