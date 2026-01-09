"""
Tests for MockL1Adapter - Deterministic quote generation

Validates:
- Mock adapter generates L1 quotes (bid/ask/last)
- Events use same schema as IBKR adapter
- Quotes arrive at expected rate
- Clean lifecycle (start/stop)
- Integration with engine: FEED_DISCONNECTED and STALE_DATA clear
"""
import time
import pytest

from src.mock_adapter import MockL1Adapter
from src.event_queue import InboundQueue
from src.events import StatusEvent, QuoteEvent, MarketDataMode
from src.datahub import DataHub
from src.engine import EngineLoop
from src.adapter_runner import AdapterRunner


def test_mock_adapter_init():
    """Test MockL1Adapter initialization."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(queue, base_price=18500.0, tick_size=0.25)

    assert adapter.base_price == 18500.0
    assert adapter.tick_size == 0.25
    assert not adapter._connected


def test_mock_adapter_connect():
    """Test MockL1Adapter connect emits StatusEvent."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(queue)

    result = adapter.connect()

    assert result is True
    assert adapter._connected is True
    assert adapter._md_mode == MarketDataMode.REALTIME

    # Check StatusEvent and initial QuoteEvent were emitted
    events = queue.drain()
    assert len(events) == 2, "Should emit StatusEvent and initial QuoteEvent"

    # First event should be StatusEvent
    assert isinstance(events[0], StatusEvent)
    assert events[0].connected is True
    assert events[0].md_mode == MarketDataMode.REALTIME

    # Second event should be initial QuoteEvent with con_id
    assert isinstance(events[1], QuoteEvent)
    assert events[1].con_id == 999999  # Mock contract ID


def test_mock_adapter_disconnect():
    """Test MockL1Adapter disconnect emits StatusEvent."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(queue)
    adapter.connect()

    # Drain connect event
    queue.drain()

    # Disconnect
    adapter.disconnect()

    assert adapter._connected is False
    assert adapter._md_mode == MarketDataMode.NONE

    # Check StatusEvent was emitted
    events = queue.drain()
    assert len(events) == 1
    assert isinstance(events[0], StatusEvent)
    assert events[0].connected is False


def test_mock_adapter_generates_quotes():
    """Test MockL1Adapter generates QuoteEvents."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(
        queue,
        base_price=18500.0,
        tick_size=0.25,
        spread_ticks=1,
        quote_rate_hz=100.0,  # High rate for fast test
    )

    adapter.connect()
    queue.drain()  # Drain StatusEvent

    # Run iterations until we get a quote
    for _ in range(10):
        adapter.run_event_loop_iteration()
        time.sleep(0.01)

    # Check QuoteEvents were emitted
    events = queue.drain()
    assert len(events) > 0

    # Find first QuoteEvent
    quote_events = [e for e in events if isinstance(e, QuoteEvent)]
    assert len(quote_events) > 0

    quote = quote_events[0]
    assert quote.bid is not None
    assert quote.ask is not None
    assert quote.last is not None
    assert quote.ask > quote.bid  # Spread is positive
    assert quote.bid_size is not None
    assert quote.ask_size is not None


def test_mock_adapter_quote_spread():
    """Test MockL1Adapter generates correct spread."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(
        queue,
        base_price=18500.0,
        tick_size=0.25,
        spread_ticks=2,  # 2 ticks = 0.50 spread
        quote_rate_hz=100.0,
    )

    adapter.connect()
    queue.drain()

    # Generate quote
    for _ in range(10):
        adapter.run_event_loop_iteration()
        time.sleep(0.01)

    events = queue.drain()
    quote_events = [e for e in events if isinstance(e, QuoteEvent)]
    assert len(quote_events) > 0

    quote = quote_events[0]
    spread = quote.ask - quote.bid

    # Spread should be ~0.50 (2 ticks * 0.25)
    assert 0.45 <= spread <= 0.55


def test_mock_adapter_deterministic_prices():
    """Test MockL1Adapter generates deterministic prices around base."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(
        queue,
        base_price=18500.0,
        tick_size=0.25,
        quote_rate_hz=100.0,
        price_drift_amplitude=5.0,  # +/- 5 points
    )

    adapter.connect()
    queue.drain()

    # Generate quotes
    for _ in range(50):
        adapter.run_event_loop_iteration()
        time.sleep(0.01)

    events = queue.drain()
    quote_events = [e for e in events if isinstance(e, QuoteEvent)]
    assert len(quote_events) > 0

    # Check all quotes are near base price
    for quote in quote_events:
        mid = (quote.bid + quote.ask) / 2.0
        # Should be within drift amplitude
        assert 18490.0 <= mid <= 18510.0


def test_mock_adapter_with_adapter_runner():
    """Test MockL1Adapter with AdapterRunner lifecycle."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(queue, quote_rate_hz=20.0)  # 20 Hz
    adapter.connect()
    queue.drain()  # Drain connect event

    runner = AdapterRunner(adapter)

    try:
        runner.start()
        time.sleep(0.3)  # Run for 300ms

    finally:
        runner.stop()

    # Check quotes were generated
    events = queue.drain()
    quote_events = [e for e in events if isinstance(e, QuoteEvent)]

    # At 20 Hz over 300ms, expect ~6 quotes
    assert 3 <= len(quote_events) <= 10


def test_mock_adapter_integration_with_engine():
    """
    Integration test: MockL1Adapter with EngineLoop.

    Validates that FEED_DISCONNECTED and STALE_DATA clear once quotes arrive.
    """
    queue = InboundQueue(maxsize=1000)
    adapter = MockL1Adapter(queue, quote_rate_hz=10.0)  # 10 Hz
    adapter.connect()

    runner = AdapterRunner(adapter)
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=100, inbound_queue=queue)

    try:
        # Start adapter first
        runner.start()
        time.sleep(0.2)  # Let quotes accumulate

        # Start engine
        engine.start()
        time.sleep(1.0)  # Run for 1 second

        # Collect snapshots
        snapshots = []
        for _ in range(20):
            snapshot = datahub.get_latest()
            if snapshot:
                snapshots.append(snapshot)
            time.sleep(0.05)

    finally:
        engine.stop()
        runner.stop()

    # Verify we collected snapshots
    assert len(snapshots) >= 5, f"Expected at least 5 snapshots, got {len(snapshots)}"

    # Check that feed status improves
    # First snapshot may have FEED_DISCONNECTED (before events processed)
    # Later snapshots should have feed connected

    feed_connected_count = sum(1 for s in snapshots if s.feed.connected)
    assert feed_connected_count > 0, "Feed should be connected in some snapshots"

    # Check for quotes received
    quotes_received = [s.quotes_received_count for s in snapshots if s.quotes_received_count > 0]
    assert len(quotes_received) > 0, "Should have received quotes"

    # Check that STALE_DATA clears eventually
    # Find snapshots with quotes
    snapshots_with_quotes = [s for s in snapshots if s.quotes_received_count > 0]
    if snapshots_with_quotes:
        # Later snapshots should not have STALE_DATA persistently
        later_snapshots = snapshots_with_quotes[-5:]  # Last 5 with quotes
        stale_count = sum(1 for s in later_snapshots if "STALE_DATA" in s.gates.reason_codes)

        # Allow some staleness but not persistent
        assert stale_count < len(later_snapshots), (
            "STALE_DATA should not be persistent once quotes flowing"
        )


def test_mock_adapter_quotes_update_timestamps():
    """Test that mock quotes have fresh timestamps."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(queue, quote_rate_hz=50.0)
    adapter.connect()
    queue.drain()

    start_time = time.perf_counter_ns()

    # Generate quotes
    for _ in range(10):
        adapter.run_event_loop_iteration()
        time.sleep(0.02)

    events = queue.drain()
    quote_events = [e for e in events if isinstance(e, QuoteEvent)]

    assert len(quote_events) > 0

    # Check timestamps are recent
    for quote in quote_events:
        assert quote.ts_recv_mono_ns >= start_time
        assert quote.ts_recv_unix_ms > 0


def test_mock_adapter_respects_quote_rate():
    """Test MockL1Adapter respects configured quote rate."""
    queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(queue, quote_rate_hz=5.0)  # 5 Hz = 200ms interval
    adapter.connect()
    queue.drain()

    # Pump adapter at high rate, should only emit every 200ms
    start = time.time()
    while (time.time() - start) < 0.6:  # 600ms
        adapter.run_event_loop_iteration()
        time.sleep(0.01)

    events = queue.drain()
    quote_events = [e for e in events if isinstance(e, QuoteEvent)]

    # At 5 Hz over 600ms, expect ~3 quotes
    assert 2 <= len(quote_events) <= 5
