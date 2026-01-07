"""
IBKR Adapter - V1a J1 MVP

Responsibilities (J1 scope only):
- Connect/disconnect with exponential backoff + storm control
- Qualify explicit-expiry contract (contract_key → conId)
- L1 subscription (bid/ask/last + sizes)
- md_mode mapping (REALTIME|DELAYED|FROZEN|NONE)
- Idempotent subscription manager (never resubscribe in hot loop)
- Fail-fast on clientId collision (error 326)

Architecture invariant: Callbacks normalize events and push to queue only.
Never mutate shared state directly.
"""
import time
import logging
import sys
from typing import Optional, Dict
from dataclasses import dataclass

try:
    from ib_insync import IB, Contract, Ticker
    from ib_insync.contract import Future
    IB_INSYNC_AVAILABLE = True
except ImportError:
    # Allow pytest collection even if ib_insync not installed
    IB_INSYNC_AVAILABLE = False
    IB = None
    Contract = None
    Ticker = None
    Future = None

from src.events import StatusEvent, QuoteEvent, MarketDataMode
from src.event_queue import InboundQueue


logger = logging.getLogger(__name__)


@dataclass
class IBKRConfig:
    """IBKR connection configuration (V1a J1)."""
    client_id: int
    host: str = "127.0.0.1"
    port: int = 7497  # TWS paper trading default

    # Single instrument (V1a requirement)
    symbol: str = "MNQ"
    contract_key: str = "MNQ.202603"  # Explicit expiry required
    tick_size: float = 0.25

    # Reconnect storm control
    reconnect_backoff_base_s: float = 1.0
    reconnect_backoff_max_s: float = 60.0
    reconnect_max_per_minute: int = 5


class IBKRAdapter:
    """
    IBKR adapter implementing J1 MVP requirements.

    V1a constraints:
    - Single instrument per run (no multi-instrument)
    - Explicit expiry contract_key (no front-month resolver)
    - L1 only (no T&S, no depth beyond BBO)
    - No execution (Silent Observer)
    """

    def __init__(self, config: IBKRConfig, inbound_queue: InboundQueue):
        if not IB_INSYNC_AVAILABLE:
            raise ImportError(
                "ib_insync not available. Install with: pip install ib_insync"
            )

        self.config = config
        self.inbound_queue = inbound_queue

        # ib_insync client
        self.ib = IB()

        # Connection state
        self._connected = False
        self._md_mode = MarketDataMode.NONE

        # Contract qualification
        self._contract: Optional[Contract] = None
        self._con_id: Optional[int] = None

        # Subscription state (idempotent manager)
        self._desired_subscriptions: Dict[int, Contract] = {}  # con_id → Contract
        self._active_subscriptions: Dict[int, Ticker] = {}  # con_id → Ticker
        self._last_subscribe_time: float = 0.0

        # Reconnect storm control
        self._reconnect_attempts_window: list[float] = []
        self._reconnect_backoff_delay: float = config.reconnect_backoff_base_s

        # Register ib_insync callbacks
        self._register_callbacks()

    def _register_callbacks(self) -> None:
        """Register ib_insync event handlers (J1 requirement)."""
        self.ib.connectedEvent += self._on_connected
        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error
        self.ib.pendingTickersEvent += self._on_pending_tickers

    def connect(self) -> bool:
        """
        Connect to IBKR with storm control (J1 requirement).

        Returns:
            True if connected successfully

        Note: Blocks until connected or backoff timeout.
        """
        # Storm control: check reconnect rate
        now = time.time()
        self._reconnect_attempts_window = [
            t for t in self._reconnect_attempts_window
            if now - t < 60.0
        ]

        if len(self._reconnect_attempts_window) >= self.config.reconnect_max_per_minute:
            logger.warning(
                f"Reconnect storm detected: {len(self._reconnect_attempts_window)} "
                f"attempts in last 60s, backing off {self._reconnect_backoff_delay:.1f}s"
            )
            time.sleep(self._reconnect_backoff_delay)

            # Exponential backoff
            self._reconnect_backoff_delay = min(
                self._reconnect_backoff_delay * 2,
                self.config.reconnect_backoff_max_s
            )
        else:
            # Reset backoff on successful rate limiting
            self._reconnect_backoff_delay = self.config.reconnect_backoff_base_s

        self._reconnect_attempts_window.append(now)

        try:
            logger.info(
                f"Connecting to IBKR: {self.config.host}:{self.config.port} "
                f"clientId={self.config.client_id}"
            )

            self.ib.connect(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
                readonly=True,  # V1a Silent Observer
                timeout=10,
            )

            self._connected = True
            logger.info("IBKR connected successfully")
            return True

        except Exception as e:
            logger.error(f"IBKR connection failed: {e}")
            self._connected = False
            self._emit_status_event(connected=False, reason=str(e))
            return False

    def disconnect(self) -> None:
        """Disconnect from IBKR cleanly (J1 requirement)."""
        if self.ib.isConnected():
            logger.info("Disconnecting from IBKR")
            self.ib.disconnect()

        self._connected = False
        self._active_subscriptions.clear()
        self._emit_status_event(connected=False, reason="Requested disconnect")

    def qualify_contract(self) -> bool:
        """
        Qualify explicit-expiry contract (J1 requirement).

        V1a constraint: Single instrument, explicit expiry only.

        Returns:
            True if contract qualified successfully
        """
        if not self._connected:
            logger.error("Cannot qualify contract: not connected")
            return False

        try:
            # Parse explicit expiry from contract_key (e.g., "MNQ.202603")
            parts = self.config.contract_key.split(".")
            if len(parts) != 2:
                raise ValueError(
                    f"Invalid contract_key format: {self.config.contract_key}. "
                    f"Expected 'SYMBOL.YYYYMM' (explicit expiry)"
                )

            symbol, expiry_str = parts

            # Create futures contract with explicit expiry
            contract = Future(
                symbol=symbol,
                lastTradeDateOrContractMonth=expiry_str,
                exchange="CME",  # MNQ/MES trade on CME
                currency="USD",
            )

            logger.info(f"Qualifying contract: {symbol} expiry={expiry_str}")

            # Qualify with IBKR
            qualified = self.ib.qualifyContracts(contract)

            if not qualified:
                logger.error(f"Contract qualification failed: {self.config.contract_key}")
                return False

            self._contract = qualified[0]
            self._con_id = self._contract.conId

            logger.info(
                f"Contract qualified: {self.config.contract_key} → conId={self._con_id}"
            )

            # Mark as desired subscription (idempotent manager)
            self._desired_subscriptions[self._con_id] = self._contract

            return True

        except Exception as e:
            logger.error(f"Contract qualification error: {e}")
            return False

    def subscribe_market_data(self) -> bool:
        """
        Subscribe to L1 market data (J1 requirement).

        Idempotent: safe to call multiple times (subscription manager).

        Returns:
            True if subscription succeeded or already active
        """
        if not self._connected:
            logger.warning("Cannot subscribe: not connected")
            return False

        if not self._con_id or not self._contract:
            logger.warning("Cannot subscribe: contract not qualified")
            return False

        # Idempotent check: already subscribed?
        if self._con_id in self._active_subscriptions:
            logger.debug(f"Already subscribed to conId={self._con_id}")
            return True

        # Rate limit: prevent hot-loop resubscribe churn
        now = time.time()
        if now - self._last_subscribe_time < 1.0:
            logger.warning("Subscribe rate-limited (hot-loop protection)")
            return False

        try:
            logger.info(f"Subscribing to L1 market data: conId={self._con_id}")

            # Request L1 market data (BBO + last)
            ticker = self.ib.reqMktData(
                self._contract,
                genericTickList="",  # L1 only
                snapshot=False,
                regulatorySnapshot=False,
            )

            self._active_subscriptions[self._con_id] = ticker
            self._last_subscribe_time = now

            logger.info(f"L1 subscription active: conId={self._con_id}")
            return True

        except Exception as e:
            logger.error(f"L1 subscription error: {e}")
            return False

    def reapply_subscriptions(self) -> None:
        """
        Re-apply desired subscriptions after reconnect (J1 requirement).

        Idempotent subscription manager: maintains desired state,
        re-applies on reconnect (rate-limited).
        """
        if not self._connected:
            return

        logger.info("Re-applying subscriptions after reconnect")

        for con_id, contract in self._desired_subscriptions.items():
            if con_id not in self._active_subscriptions:
                try:
                    logger.info(f"Re-subscribing to conId={con_id}")
                    ticker = self.ib.reqMktData(contract, "", False, False)
                    self._active_subscriptions[con_id] = ticker
                except Exception as e:
                    logger.error(f"Re-subscribe failed for conId={con_id}: {e}")

    def _on_connected(self) -> None:
        """Callback: IBKR connected (ib_insync event)."""
        logger.info("IBKR connected callback")
        self._connected = True

        # Determine md_mode from connection state
        self._update_md_mode()

        self._emit_status_event(connected=True, reason="Connected")

        # Re-apply subscriptions (idempotent manager)
        self.reapply_subscriptions()

    def _on_disconnected(self) -> None:
        """Callback: IBKR disconnected (ib_insync event)."""
        logger.warning("IBKR disconnected callback")
        self._connected = False
        self._md_mode = MarketDataMode.NONE
        self._active_subscriptions.clear()

        self._emit_status_event(connected=False, reason="Disconnected")

    def _on_error(self, reqId: int, errorCode: int, errorString: str, contract: Optional[Contract]) -> None:
        """
        Callback: IBKR error (ib_insync event).

        J1 requirement: Fail-fast on clientId collision (error 326).
        """
        logger.error(f"IBKR error {errorCode}: {errorString} (reqId={reqId})")

        # FATAL: clientId collision (J1 requirement)
        if errorCode == 326:
            logger.critical(
                f"FATAL: clientId collision detected (error 326). "
                f"clientId={self.config.client_id} already in use. "
                f"Exiting immediately."
            )

            # Emit status event for audit trail
            self._emit_status_event(
                connected=False,
                reason=f"clientId collision (error 326)",
                error_code=326
            )

            # Fail-fast: exit with non-zero status
            sys.exit(1)

        # Other errors: log and emit for engine to handle
        # (not fatal, but may affect gates/status)

    def _on_pending_tickers(self, tickers: list) -> None:
        """
        Callback: Market data update (ib_insync event).

        Normalize and emit QuoteEvent to inbound queue (J1 requirement).
        """
        now_mono_ns = time.perf_counter_ns()
        now_unix_ms = int(time.time() * 1000)

        for ticker in tickers:
            # Update md_mode based on ticker state
            self._update_md_mode_from_ticker(ticker)

            # Emit normalized QuoteEvent
            if ticker.contract and ticker.contract.conId:
                quote_event = QuoteEvent(
                    ts_recv_mono_ns=now_mono_ns,
                    ts_recv_unix_ms=now_unix_ms,
                    con_id=ticker.contract.conId,
                    bid=ticker.bid if ticker.bid == ticker.bid else None,  # NaN check
                    ask=ticker.ask if ticker.ask == ticker.ask else None,
                    last=ticker.last if ticker.last == ticker.last else None,
                    bid_size=int(ticker.bidSize) if ticker.bidSize == ticker.bidSize else None,
                    ask_size=int(ticker.askSize) if ticker.askSize == ticker.askSize else None,
                    ts_exch_unix_ms=None,  # IBKR doesn't provide exchange timestamp for L1
                )

                try:
                    self.inbound_queue.push(quote_event)
                except Exception as e:
                    logger.error(f"Failed to push QuoteEvent: {e}")

    def _update_md_mode(self) -> None:
        """
        Update md_mode from IBKR connection state (J1 requirement).

        Maps IBKR state to: REALTIME | DELAYED | FROZEN | NONE
        """
        if not self._connected:
            self._md_mode = MarketDataMode.NONE
            return

        # ib_insync provides marketDataType: 1=LIVE, 2=FROZEN, 3=DELAYED, 4=DELAYED_FROZEN
        # Default to REALTIME if connected (will be updated by ticker events)
        self._md_mode = MarketDataMode.REALTIME

    def _update_md_mode_from_ticker(self, ticker: Ticker) -> None:
        """
        Update md_mode from ticker state (more accurate than connection state).

        J1 requirement: md_mode reflects actual data freshness.
        """
        prev_mode = self._md_mode

        # Check ticker halted/frozen state
        if hasattr(ticker, 'halted') and ticker.halted:
            self._md_mode = MarketDataMode.FROZEN
        # Check if we're receiving delayed data
        elif hasattr(ticker, 'delayed') and ticker.delayed:
            self._md_mode = MarketDataMode.DELAYED
        # Otherwise assume realtime if connected
        elif self._connected:
            self._md_mode = MarketDataMode.REALTIME
        else:
            self._md_mode = MarketDataMode.NONE

        # Emit status event if md_mode changed
        if self._md_mode != prev_mode:
            logger.info(f"md_mode changed: {prev_mode} → {self._md_mode}")
            self._emit_status_event(
                connected=self._connected,
                reason=f"md_mode changed to {self._md_mode.value}"
            )

    def _emit_status_event(self, connected: bool, reason: Optional[str] = None, error_code: Optional[int] = None) -> None:
        """
        Emit StatusEvent to inbound queue (J1 requirement).

        Architecture invariant: Adapter emits events only, never mutates shared state.
        """
        event = StatusEvent(
            ts_recv_mono_ns=time.perf_counter_ns(),
            ts_recv_unix_ms=int(time.time() * 1000),
            connected=connected,
            md_mode=self._md_mode,
            reason=reason,
            error_code=error_code,
        )

        try:
            self.inbound_queue.push(event)
        except Exception as e:
            logger.error(f"Failed to push StatusEvent: {e}")

    def run_event_loop_iteration(self) -> None:
        """
        Process one iteration of ib_insync event loop.

        Must be called periodically (e.g., from engine loop or dedicated thread).
        """
        if self.ib.isConnected():
            self.ib.waitOnUpdate(timeout=0.01)  # Non-blocking poll
