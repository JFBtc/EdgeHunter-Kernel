"""
Inbound event queue for adapter→engine communication (V1a J1)

Architecture invariant: Single-writer (engine) drains queue; adapter pushes only.
"""
import queue
from typing import Union
from src.events import StatusEvent, QuoteEvent, AdapterErrorEvent


# Union type for all inbound events
InboundEvent = Union[StatusEvent, QuoteEvent, AdapterErrorEvent]


class InboundQueue:
    """
    Thread-safe bounded queue for adapter→engine event flow.

    V1a J1: Adapter pushes normalized events; engine drains at cycle start.
    """

    def __init__(self, maxsize: int = 1000):
        """
        Args:
            maxsize: Maximum queue depth (prevents runaway growth)
        """
        self._queue: queue.Queue[InboundEvent] = queue.Queue(maxsize=maxsize)

    def push(self, event: InboundEvent) -> None:
        """
        Push event from adapter (non-blocking with bounded queue).

        Args:
            event: Normalized StatusEvent, QuoteEvent, or AdapterErrorEvent

        Raises:
            queue.Full: If queue is at capacity (adapter should log/handle)
        """
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # V1a J1: Adapter logs overflow; does not block callbacks
            # Engine will handle degradation based on queue metrics
            raise

    def drain(self, max_events: int = 0) -> list[InboundEvent]:
        """
        Drain events from queue (engine only).

        Args:
            max_events: Max events to drain (0 = drain all available)

        Returns:
            List of events (empty if queue empty)
        """
        events = []
        count = 0

        while True:
            # Stop if max_events reached (anti-starvation)
            if max_events > 0 and count >= max_events:
                break

            try:
                event = self._queue.get_nowait()
                events.append(event)
                count += 1
            except queue.Empty:
                break

        return events

    def qsize(self) -> int:
        """
        Approximate queue size (for monitoring/degradation detection).
        """
        return self._queue.qsize()
