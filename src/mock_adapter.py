"""
Mock L1 Adapter - Deterministic quote generator for testing

Responsibilities:
- Generate deterministic L1 quotes (bid/ask/last) at fixed rate
- Emit same event types as IBKRAdapter (StatusEvent, QuoteEvent)
- Thread-safe with clean start/stop lifecycle
- Compatible with AdapterRunner

V1a scope: Simple price oscillation, no complex market simulation
"""
import time
import math
import logging
from typing import Optional

from src.events import StatusEvent, QuoteEvent, MarketDataMode
from src.event_queue import InboundQueue


logger = logging.getLogger(__name__)


class MockL1Adapter:
    """
    Mock L1 market data adapter for testing.

    Generates deterministic bid/ask/last quotes with small oscillation.
    Compatible with AdapterRunner lifecycle (start/stop).
    """

    def __init__(
        self,
        inbound_queue: InboundQueue,
        base_price: float = 18500.0,
        tick_size: float = 0.25,
        spread_ticks: int = 1,
        quote_rate_hz: float = 10.0,
        price_drift_amplitude: float = 5.0,
        price_drift_period_s: float = 60.0,
    ):
        """
        Initialize mock adapter.

        Args:
            inbound_queue: Queue to push events to
            base_price: Base mid price (e.g., 18500.0 for MNQ)
            tick_size: Tick size (e.g., 0.25 for MNQ)
            spread_ticks: Spread in ticks (e.g., 1 = 0.25 spread)
            quote_rate_hz: Quote generation rate (Hz)
            price_drift_amplitude: Price oscillation amplitude (points)
            price_drift_period_s: Price oscillation period (seconds)
        """
        self.inbound_queue = inbound_queue
        self.base_price = base_price
        self.tick_size = tick_size
        self.spread_ticks = spread_ticks
        self.quote_rate_hz = quote_rate_hz
        self.price_drift_amplitude = price_drift_amplitude
        self.price_drift_period_s = price_drift_period_s

        # Derived parameters
        self.spread = spread_ticks * tick_size
        self.quote_interval_s = 1.0 / quote_rate_hz

        # State
        self._connected = False
        self._md_mode = MarketDataMode.NONE
        self._start_time: Optional[float] = None
        self._last_quote_time: Optional[float] = None

        logger.info(
            f"MockL1Adapter initialized: base={base_price}, spread={spread_ticks} ticks, "
            f"rate={quote_rate_hz} Hz"
        )

    def connect(self) -> bool:
        """
        Simulate connection (always succeeds for mock).

        Returns:
            True (always succeeds)
        """
        logger.info("Mock adapter: connecting")
        self._connected = True
        self._md_mode = MarketDataMode.REALTIME
        self._start_time = time.time()
        self._last_quote_time = self._start_time

        # Emit StatusEvent
        self._emit_status_event(connected=True, reason="Mock connected")

        # Emit initial QuoteEvent with con_id to establish contract presence
        # This clears NO_CONTRACT gate immediately
        initial_quote = QuoteEvent(
            ts_recv_mono_ns=time.perf_counter_ns(),
            ts_recv_unix_ms=int(self._start_time * 1000),
            con_id=999999,  # Mock contract ID
            # No bid/ask/last yet - will be filled by first generated quote
        )
        try:
            self.inbound_queue.push(initial_quote)
            logger.debug("Mock adapter: emitted initial QuoteEvent")
        except Exception as e:
            logger.error(f"Failed to push initial QuoteEvent: {e}")

        logger.info("Mock adapter: connected")
        return True

    def disconnect(self) -> None:
        """Disconnect (cleanup)."""
        logger.info("Mock adapter: disconnecting")
        self._connected = False
        self._md_mode = MarketDataMode.NONE

        # Emit StatusEvent
        self._emit_status_event(connected=False, reason="Mock disconnected")

    def run_event_loop_iteration(self) -> None:
        """
        Generate and emit one quote if interval elapsed.

        Called periodically by AdapterRunner (similar to IBKRAdapter).
        """
        if not self._connected:
            return

        now = time.time()

        # Check if quote interval elapsed
        if self._last_quote_time and (now - self._last_quote_time) < self.quote_interval_s:
            return

        # Generate quote
        self._generate_and_emit_quote(now)
        self._last_quote_time = now

    def _generate_and_emit_quote(self, now: float) -> None:
        """
        Generate deterministic quote with price oscillation.

        Args:
            now: Current timestamp (seconds)
        """
        # Time since start
        elapsed = now - self._start_time

        # Sinusoidal price drift
        drift_phase = (elapsed / self.price_drift_period_s) * 2 * math.pi
        drift = self.price_drift_amplitude * math.sin(drift_phase)

        # Mid price with drift
        mid_price = self.base_price + drift

        # Bid/ask with spread
        half_spread = self.spread / 2.0
        bid = mid_price - half_spread
        ask = mid_price + half_spread
        last = mid_price

        # Round to tick size
        bid = round(bid / self.tick_size) * self.tick_size
        ask = round(ask / self.tick_size) * self.tick_size
        last = round(last / self.tick_size) * self.tick_size

        # Timestamps
        now_mono_ns = time.perf_counter_ns()
        now_unix_ms = int(now * 1000)

        # Emit QuoteEvent
        quote_event = QuoteEvent(
            ts_recv_mono_ns=now_mono_ns,
            ts_recv_unix_ms=now_unix_ms,
            con_id=999999,  # Mock contract ID
            bid=bid,
            ask=ask,
            last=last,
            bid_size=10,  # Mock size
            ask_size=10,
            ts_exch_unix_ms=now_unix_ms,  # Mock exchange timestamp
        )

        try:
            self.inbound_queue.push(quote_event)
        except Exception as e:
            logger.error(f"Failed to push QuoteEvent: {e}")

    def _emit_status_event(self, connected: bool, reason: Optional[str] = None) -> None:
        """
        Emit StatusEvent to inbound queue.

        Args:
            connected: Connection status
            reason: Optional reason string
        """
        event = StatusEvent(
            ts_recv_mono_ns=time.perf_counter_ns(),
            ts_recv_unix_ms=int(time.time() * 1000),
            connected=connected,
            md_mode=self._md_mode,
            reason=reason,
        )

        try:
            self.inbound_queue.push(event)
        except Exception as e:
            logger.error(f"Failed to push StatusEvent: {e}")
