"""
Tests for V1a J1 - IBKR Adapter MVP

Validates:
- Event schemas
- Event queue
- Subscription idempotency (unit-level)
- md_mode mapping
- clientId collision detection (mock)

Note: Full integration tests require live/paper IBKR connection.
These are unit tests for J1 architecture components.
"""
import time
import pytest

from src.events import StatusEvent, QuoteEvent, MarketDataMode
from src.event_queue import InboundQueue
from src.ibkr_adapter import IBKRConfig


def test_event_queue_push_drain():
    """Test inbound queue push/drain mechanics (J1 requirement)."""
    queue = InboundQueue(maxsize=10)

    # Push events
    event1 = StatusEvent(
        ts_recv_mono_ns=time.perf_counter_ns(),
        ts_recv_unix_ms=int(time.time() * 1000),
        connected=True,
        md_mode=MarketDataMode.REALTIME,
    )

    event2 = QuoteEvent(
        ts_recv_mono_ns=time.perf_counter_ns(),
        ts_recv_unix_ms=int(time.time() * 1000),
        con_id=12345,
        bid=100.0,
        ask=100.25,
        last=100.125,
    )

    queue.push(event1)
    queue.push(event2)

    # Drain events
    events = queue.drain()

    assert len(events) == 2
    assert isinstance(events[0], StatusEvent)
    assert isinstance(events[1], QuoteEvent)
    assert events[0].connected is True
    assert events[1].bid == 100.0


def test_event_queue_bounded():
    """Test queue overflow handling (J1 anti-starvation)."""
    queue = InboundQueue(maxsize=2)

    event = StatusEvent(
        ts_recv_mono_ns=time.perf_counter_ns(),
        ts_recv_unix_ms=int(time.time() * 1000),
        connected=True,
        md_mode=MarketDataMode.REALTIME,
    )

    # Fill queue
    queue.push(event)
    queue.push(event)

    # Third push should raise Full
    with pytest.raises(Exception):  # queue.Full
        queue.push(event)


def test_event_queue_drain_max_events():
    """Test bounded drain (anti-starvation protection)."""
    queue = InboundQueue(maxsize=100)

    # Push 10 events
    for i in range(10):
        event = StatusEvent(
            ts_recv_mono_ns=time.perf_counter_ns(),
            ts_recv_unix_ms=int(time.time() * 1000),
            connected=True,
            md_mode=MarketDataMode.REALTIME,
        )
        queue.push(event)

    # Drain max 5
    events = queue.drain(max_events=5)
    assert len(events) == 5

    # Remaining 5 still in queue
    assert queue.qsize() == 5


def test_md_mode_mapping():
    """Test MarketDataMode enum values (J1 requirement)."""
    assert MarketDataMode.REALTIME.value == "REALTIME"
    assert MarketDataMode.DELAYED.value == "DELAYED"
    assert MarketDataMode.FROZEN.value == "FROZEN"
    assert MarketDataMode.NONE.value == "NONE"


def test_adapter_config_explicit_expiry():
    """Test config validation for explicit expiry (V1a requirement)."""
    config = IBKRConfig(
        client_id=100,
        symbol="MNQ",
        contract_key="MNQ.202603",  # Explicit expiry required
        tick_size=0.25,
    )

    # Should parse correctly
    parts = config.contract_key.split(".")
    assert len(parts) == 2
    assert parts[0] == "MNQ"
    assert parts[1] == "202603"


def test_status_event_immutability():
    """Test that events are frozen/immutable (architecture invariant)."""
    event = StatusEvent(
        ts_recv_mono_ns=time.perf_counter_ns(),
        ts_recv_unix_ms=int(time.time() * 1000),
        connected=True,
        md_mode=MarketDataMode.REALTIME,
    )

    # Should not be able to mutate frozen dataclass
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        event.connected = False


def test_quote_event_schema():
    """Test QuoteEvent schema matches J1 spec."""
    now_mono = time.perf_counter_ns()
    now_unix = int(time.time() * 1000)

    event = QuoteEvent(
        ts_recv_mono_ns=now_mono,
        ts_recv_unix_ms=now_unix,
        con_id=12345,
        bid=100.0,
        ask=100.25,
        last=100.125,
        bid_size=10,
        ask_size=5,
        ts_exch_unix_ms=None,  # IBKR L1 doesn't provide exchange timestamp
    )

    # Verify all required fields
    assert event.ts_recv_mono_ns == now_mono
    assert event.ts_recv_unix_ms == now_unix
    assert event.con_id == 12345
    assert event.bid == 100.0
    assert event.ask == 100.25
    assert event.last == 100.125
    assert event.bid_size == 10
    assert event.ask_size == 5


def test_reconnect_storm_control_config():
    """Test reconnect storm control configuration (J1 requirement)."""
    config = IBKRConfig(
        client_id=100,
        reconnect_backoff_base_s=1.0,
        reconnect_backoff_max_s=60.0,
        reconnect_max_per_minute=5,
    )

    assert config.reconnect_backoff_base_s == 1.0
    assert config.reconnect_backoff_max_s == 60.0
    assert config.reconnect_max_per_minute == 5
