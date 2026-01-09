"""
Adapter runner thread - Minimal plumbing for J1

Runs IBKR adapter event loop in background thread.
V1a J1: Separate from engine loop to avoid blocking engine cycles.

Future milestone (J3): Engine will drain inbound queue and process events.
For now (J1): Just proves adapter→queue flow works.
"""
import asyncio
import threading
import time
import logging
from typing import Optional

from src.ibkr_adapter import IBKRAdapter


logger = logging.getLogger(__name__)


class AdapterRunner:
    """
    Background thread runner for IBKR adapter event loop.

    V1a J1 scope: Minimal plumbing to run adapter independently.
    Architecture: Adapter runs in own thread, pushes events to queue.
    """

    def __init__(self, adapter: IBKRAdapter):
        self.adapter = adapter
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start adapter event loop in background thread."""
        if self._running:
            return

        logger.info("Starting adapter runner thread")
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop adapter event loop."""
        logger.info("Stopping adapter runner thread")
        self._running = False

        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run_loop(self) -> None:
        """
        Adapter event loop: process ib_insync events.

        Runs at ~100 Hz to ensure responsive callback handling.

        Creates an asyncio event loop for this thread (required for ib_insync).
        """
        # Create and set event loop for this thread
        # (Required for ib_insync.IB.waitOnUpdate() to work)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            while self._running:
                try:
                    # Process one iteration of ib_insync event loop
                    self.adapter.run_event_loop_iteration()

                    # Small sleep to avoid busy-wait (10ms = 100 Hz)
                    time.sleep(0.01)

                except Exception as e:
                    logger.error(f"Adapter event loop error: {e}", exc_info=True)
                    time.sleep(1.0)  # Back off on errors

        finally:
            # Clean up event loop on thread shutdown
            try:
                # Cancel all pending tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()

                # Run loop briefly to process cancellations
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

                # Close the loop
                loop.close()
                logger.debug("Adapter runner event loop closed")
            except Exception as e:
                logger.error(f"Error closing event loop: {e}")
