"""
Test contract presence and staleness tracking.

Validates:
- After adapter init, Snapshot contains contract fields so NO_CONTRACT doesn't trigger
- After at least one quote, Snapshot staleness is numeric (not NA)
- MOCK adapter establishes contract presence immediately
"""
import time
import pytest

from src.mock_adapter import MockL1Adapter
from src.adapter_runner import AdapterRunner
from src.event_queue import InboundQueue
from src.datahub import DataHub
from src.engine import EngineLoop


def test_mock_adapter_establishes_contract_immediately():
    """Test that MOCK adapter emits con_id immediately on connect."""
    inbound_queue = InboundQueue(maxsize=100)
    adapter = MockL1Adapter(inbound_queue, quote_rate_hz=10.0)

    # Connect - should emit initial QuoteEvent with con_id
    adapter.connect()

    # Drain events
    events = inbound_queue.drain()

    # Should have StatusEvent + initial QuoteEvent
    assert len(events) >= 2, "Should have StatusEvent and initial QuoteEvent"

    # Find QuoteEvent
    quote_events = [e for e in events if hasattr(e, 'con_id')]
    assert len(quote_events) >= 1, "Should have at least one QuoteEvent"

    # Verify con_id is set
    initial_quote = quote_events[0]
    assert initial_quote.con_id == 999999, "Mock con_id should be 999999"


def test_engine_stores_con_id_from_quote():
    """Test that engine stores con_id from QuoteEvent."""
    inbound_queue = InboundQueue(maxsize=100)
    datahub = DataHub()

    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        inbound_queue=inbound_queue,
    )

    # Create and connect mock adapter
    adapter = MockL1Adapter(inbound_queue, quote_rate_hz=10.0)
    adapter.connect()

    # Start engine and let it process events
    engine.start()
    time.sleep(0.3)  # Let engine run a few cycles
    engine.stop()

    # Get latest snapshot
    snapshot = datahub.get_latest()

    # Verify con_id is present in snapshot
    assert snapshot.instrument.con_id is not None, "Snapshot should contain con_id"
    assert snapshot.instrument.con_id == 999999, "Should be mock con_id"


def test_snapshot_no_contract_clears_after_connection():
    """Test that NO_CONTRACT reason clears once adapter establishes contract."""
    inbound_queue = InboundQueue(maxsize=100)
    datahub = DataHub()

    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        inbound_queue=inbound_queue,
    )

    # Start engine without adapter - should show NO_CONTRACT
    engine.start()
    time.sleep(0.2)

    snapshot_before = datahub.get_latest()
    assert "NO_CONTRACT" in snapshot_before.gates.reason_codes, \
        "Should have NO_CONTRACT before adapter connects"

    # Now connect adapter
    adapter = MockL1Adapter(inbound_queue, quote_rate_hz=10.0)
    adapter.connect()

    # Let engine process events
    time.sleep(0.3)
    engine.stop()

    snapshot_after = datahub.get_latest()

    # NO_CONTRACT should be gone
    assert "NO_CONTRACT" not in snapshot_after.gates.reason_codes, \
        "NO_CONTRACT should clear after adapter establishes contract"

    # con_id should be present
    assert snapshot_after.instrument.con_id == 999999


def test_staleness_becomes_numeric_after_quotes():
    """Test that staleness_ms becomes numeric (not None) after quotes arrive."""
    inbound_queue = InboundQueue(maxsize=100)
    datahub = DataHub()

    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        inbound_queue=inbound_queue,
    )

    # Create adapter with fast quote rate and connect
    adapter = MockL1Adapter(inbound_queue, quote_rate_hz=20.0)
    adapter.connect()  # Must connect before wrapping in runner
    runner = AdapterRunner(adapter)

    # Start adapter and engine
    runner.start()
    engine.start()

    # Let quotes flow
    time.sleep(0.5)

    engine.stop()
    runner.stop()

    snapshot = datahub.get_latest()

    # Staleness should be numeric
    assert snapshot.quote.staleness_ms is not None, \
        "staleness_ms should not be None after quotes arrive"
    assert isinstance(snapshot.quote.staleness_ms, int), \
        "staleness_ms should be integer"
    assert snapshot.quote.staleness_ms >= 0, \
        "staleness_ms should be non-negative"

    # Quote data should be present
    assert snapshot.quote.bid is not None, "Should have bid"
    assert snapshot.quote.ask is not None, "Should have ask"
    assert snapshot.quote.last is not None, "Should have last"

    # Quotes received count should be positive
    assert snapshot.quotes_received_count > 0, \
        "Should have received quotes"


def test_mock_adapter_with_runner_establishes_contract():
    """Test full integration: adapter runner + engine shows contract and quotes."""
    inbound_queue = InboundQueue(maxsize=100)
    datahub = DataHub()

    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        inbound_queue=inbound_queue,
    )

    # Create adapter via runner (matches production flow)
    adapter = MockL1Adapter(inbound_queue, quote_rate_hz=10.0)
    adapter.connect()
    runner = AdapterRunner(adapter)

    # Start everything
    runner.start()
    engine.start()

    # Let it run
    time.sleep(0.4)

    # Stop
    engine.stop()
    runner.stop()

    snapshot = datahub.get_latest()

    # Contract should be established
    assert snapshot.instrument.con_id == 999999
    assert "NO_CONTRACT" not in snapshot.gates.reason_codes

    # Quotes should be flowing
    assert snapshot.quotes_received_count > 0
    assert snapshot.quote.staleness_ms is not None
    assert snapshot.quote.bid is not None

    # Feed should be connected
    assert snapshot.feed.connected is True
    assert "FEED_DISCONNECTED" not in snapshot.gates.reason_codes


def test_contract_only_quote_does_not_update_staleness():
    """Test that contract-only QuoteEvent clears NO_CONTRACT but keeps staleness NA."""
    from src.events import QuoteEvent

    inbound_queue = InboundQueue(maxsize=100)
    datahub = DataHub()

    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        inbound_queue=inbound_queue,
    )

    # Emit contract-only QuoteEvent (no bid/ask/last)
    contract_only_quote = QuoteEvent(
        ts_recv_mono_ns=time.perf_counter_ns(),
        ts_recv_unix_ms=int(time.time() * 1000),
        con_id=123456,
        # No bid, ask, last - contract presence only
    )
    inbound_queue.push(contract_only_quote)

    # Start engine and let it process
    engine.start()
    time.sleep(0.3)
    engine.stop()

    snapshot = datahub.get_latest()

    # Contract should be present
    assert snapshot.instrument.con_id == 123456
    assert "NO_CONTRACT" not in snapshot.gates.reason_codes

    # Staleness should be None/NA (no real quote yet)
    assert snapshot.quote.staleness_ms is None, \
        "staleness_ms should be None with contract-only quote"

    # Quote fields should be None
    assert snapshot.quote.bid is None
    assert snapshot.quote.ask is None
    assert snapshot.quote.last is None

    # Quotes received count should be 0 (no real quotes)
    assert snapshot.quotes_received_count == 0


def test_real_quote_after_contract_only_updates_staleness():
    """Test that staleness updates only when real quote arrives."""
    from src.events import QuoteEvent

    inbound_queue = InboundQueue(maxsize=100)
    datahub = DataHub()

    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        inbound_queue=inbound_queue,
    )

    engine.start()

    # First: contract-only quote
    contract_only_quote = QuoteEvent(
        ts_recv_mono_ns=time.perf_counter_ns(),
        ts_recv_unix_ms=int(time.time() * 1000),
        con_id=123456,
    )
    inbound_queue.push(contract_only_quote)
    time.sleep(0.2)

    snapshot_after_contract = datahub.get_latest()
    assert snapshot_after_contract.instrument.con_id == 123456
    assert snapshot_after_contract.quote.staleness_ms is None, \
        "staleness should be None after contract-only quote"
    assert snapshot_after_contract.quotes_received_count == 0

    # Now: real quote with price data
    real_quote = QuoteEvent(
        ts_recv_mono_ns=time.perf_counter_ns(),
        ts_recv_unix_ms=int(time.time() * 1000),
        con_id=123456,
        bid=100.25,
        ask=100.50,
        last=100.25,
    )
    inbound_queue.push(real_quote)
    time.sleep(0.2)

    engine.stop()

    snapshot_after_real = datahub.get_latest()

    # Staleness should now be numeric
    assert snapshot_after_real.quote.staleness_ms is not None, \
        "staleness should be numeric after real quote"
    assert isinstance(snapshot_after_real.quote.staleness_ms, int)

    # Quote fields should be populated
    assert snapshot_after_real.quote.bid == 100.25
    assert snapshot_after_real.quote.ask == 100.50
    assert snapshot_after_real.quote.last == 100.25

    # Quotes received count should be 1
    assert snapshot_after_real.quotes_received_count == 1
