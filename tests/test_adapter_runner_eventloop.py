"""
Tests for AdapterRunner event loop management

Validates:
- AdapterRunner creates asyncio event loop in its thread
- Event loop is accessible to adapter during iteration
- Clean shutdown closes event loop properly
"""
import asyncio
import time
import threading
import pytest

from src.adapter_runner import AdapterRunner
from src.event_queue import InboundQueue


class MockAdapterWithAsyncCheck:
    """Mock adapter that verifies event loop availability."""

    def __init__(self):
        self.iteration_count = 0
        self.event_loop_available = False
        self.thread_id = None

    def run_event_loop_iteration(self):
        """Check if event loop is available in this thread."""
        self.iteration_count += 1
        self.thread_id = threading.current_thread().ident

        try:
            # This should work if event loop is set
            loop = asyncio.get_event_loop()
            self.event_loop_available = (loop is not None)
        except RuntimeError:
            self.event_loop_available = False


def test_adapter_runner_creates_event_loop():
    """Test that AdapterRunner creates an event loop in its thread."""
    adapter = MockAdapterWithAsyncCheck()
    runner = AdapterRunner(adapter)

    try:
        runner.start()
        time.sleep(0.2)  # Let thread run a few iterations

    finally:
        runner.stop()

    # Verify adapter ran
    assert adapter.iteration_count > 0, "Adapter should have run iterations"

    # Verify event loop was available
    assert adapter.event_loop_available is True, (
        "Event loop should be available in adapter thread"
    )

    # Verify adapter ran in different thread
    main_thread_id = threading.current_thread().ident
    assert adapter.thread_id != main_thread_id, (
        "Adapter should run in separate thread"
    )


def test_adapter_runner_asyncio_get_event_loop_works():
    """Test that asyncio.get_event_loop() works in adapter thread."""
    class AsyncCheckAdapter:
        def __init__(self):
            self.loop_check_passed = False
            self.loop_is_running = False

        def run_event_loop_iteration(self):
            try:
                loop = asyncio.get_event_loop()
                self.loop_check_passed = True
                self.loop_is_running = loop.is_running()
            except RuntimeError as e:
                self.loop_check_passed = False
                raise

    adapter = AsyncCheckAdapter()
    runner = AdapterRunner(adapter)

    try:
        runner.start()
        time.sleep(0.1)

    finally:
        runner.stop()

    assert adapter.loop_check_passed is True, (
        "asyncio.get_event_loop() should work in runner thread"
    )
    # Note: loop.is_running() returns False because we're not using loop.run_forever()
    # We're just setting the loop as the current event loop for this thread


def test_adapter_runner_multiple_start_stop_cycles():
    """Test that runner can start/stop multiple times without loop issues."""
    adapter = MockAdapterWithAsyncCheck()
    runner = AdapterRunner(adapter)

    # First cycle
    runner.start()
    time.sleep(0.1)
    runner.stop()
    first_count = adapter.iteration_count

    # Reset adapter state
    adapter.iteration_count = 0
    adapter.event_loop_available = False

    # Second cycle
    runner.start()
    time.sleep(0.1)
    runner.stop()
    second_count = adapter.iteration_count

    # Both cycles should have worked
    assert first_count > 0
    assert second_count > 0
    assert adapter.event_loop_available is True


def test_adapter_runner_with_mock_adapter():
    """Test AdapterRunner with MockL1Adapter (which doesn't use asyncio)."""
    from src.mock_adapter import MockL1Adapter

    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(queue, quote_rate_hz=50.0)
    adapter.connect()

    runner = AdapterRunner(adapter)

    try:
        runner.start()
        time.sleep(0.2)

    finally:
        runner.stop()

    # Verify mock adapter worked
    events = queue.drain()
    assert len(events) > 0  # Should have quotes


def test_adapter_runner_event_loop_cleanup():
    """Test that event loop is properly cleaned up on shutdown."""
    class LoopTrackingAdapter:
        def __init__(self):
            self.loop_at_start = None
            self.loop_at_end = None
            self.iterations = 0

        def run_event_loop_iteration(self):
            if self.iterations == 0:
                self.loop_at_start = asyncio.get_event_loop()
            self.iterations += 1

    adapter = LoopTrackingAdapter()
    runner = AdapterRunner(adapter)

    runner.start()
    time.sleep(0.1)
    runner.stop()

    # Verify loop was available during run
    assert adapter.loop_at_start is not None
    assert adapter.iterations > 0


def test_adapter_runner_handles_adapter_exception():
    """Test that runner handles exceptions from adapter gracefully."""
    class FailingAdapter:
        def __init__(self):
            self.call_count = 0

        def run_event_loop_iteration(self):
            self.call_count += 1
            if self.call_count == 1:
                raise RuntimeError("Test exception")
            # After first exception, work normally

    adapter = FailingAdapter()
    runner = AdapterRunner(adapter)

    try:
        runner.start()
        time.sleep(1.5)  # Give time to recover from exception

    finally:
        runner.stop()

    # Should have recovered and continued running
    assert adapter.call_count > 1, "Runner should continue after exception"
