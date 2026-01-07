"""
IBKR Adapter MVP (V1a J1).
Connect/reconnect with backoff, qualify explicit-expiry contract, subscribe to L1,
map md_mode, and fail fast on clientId collisions.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from queue import Queue
from typing import Deque, Optional

logger = logging.getLogger(__name__)

MD_REALTIME = "REALTIME"
MD_DELAYED = "DELAYED"
MD_FROZEN = "FROZEN"
MD_NONE = "NONE"

_TICK_BID = 1
_TICK_ASK = 2
_TICK_LAST = 4
_TICK_BID_SIZE = 0
_TICK_ASK_SIZE = 3
_TICK_LAST_SIZE = 5


try:  # pragma: no cover - optional runtime dependency
    from ibapi.client import EClient  # type: ignore
    from ibapi.contract import Contract  # type: ignore
except Exception:  # pragma: no cover - keep tests independent of ibapi
    EClient = None

    class Contract:  # type: ignore
        def __init__(self) -> None:
            self.symbol = ""
            self.secType = ""
            self.exchange = ""
            self.currency = ""
            self.lastTradeDateOrContractMonth = ""
            self.conId = 0


@dataclass(frozen=True)
class StatusEvent:
    ts_unix_ms: int
    connected: bool
    md_mode: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuoteEvent:
    ts_unix_ms: int
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    last_size: Optional[int] = None


@dataclass(frozen=True)
class AdapterErrorEvent:
    ts_unix_ms: int
    error_code: str
    message: str


class InboundQueue:
    def __init__(self, maxsize: int = 0) -> None:
        self._queue: Queue[object] = Queue(maxsize=maxsize)

    def put(self, event: object) -> None:
        self._queue.put(event)

    def get(self, timeout: Optional[float] = None) -> object:
        return self._queue.get(timeout=timeout)

    def empty(self) -> bool:
        return self._queue.empty()


def map_md_mode(market_data_type: Optional[int]) -> str:
    mapping = {
        1: MD_REALTIME,
        2: MD_FROZEN,
        3: MD_DELAYED,
        4: MD_FROZEN,  # delayed-frozen maps to frozen (conservative)
    }
    return mapping.get(market_data_type, MD_NONE)


def parse_contract_key(contract_key: str) -> tuple[str, str]:
    if not re.fullmatch(r"[A-Z0-9]+\.[0-9]{6}", contract_key):
        raise ValueError("contract_key must be explicit expiry like MNQ.202603")
    symbol, expiry = contract_key.split(".", 1)
    return symbol, expiry


def build_contract(contract_key: str, exchange: str, currency: str) -> Contract:
    symbol, expiry = parse_contract_key(contract_key)
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "FUT"
    contract.exchange = exchange
    contract.currency = currency
    contract.lastTradeDateOrContractMonth = expiry
    return contract


class ReconnectPolicy:
    def __init__(
        self,
        base_delay_s: float = 1.0,
        max_delay_s: float = 60.0,
        max_attempts_per_minute: int = 5,
    ) -> None:
        self._base_delay_s = base_delay_s
        self._max_delay_s = max_delay_s
        self._max_attempts_per_minute = max_attempts_per_minute
        self._attempt_times: Deque[float] = deque()
        self._failures = 0

    def _prune(self, now_mono: float) -> None:
        while self._attempt_times and now_mono - self._attempt_times[0] > 60.0:
            self._attempt_times.popleft()

    def can_attempt(self, now_mono: float) -> bool:
        self._prune(now_mono)
        return len(self._attempt_times) < self._max_attempts_per_minute

    def cooldown_remaining(self, now_mono: float) -> float:
        self._prune(now_mono)
        if len(self._attempt_times) < self._max_attempts_per_minute:
            return 0.0
        oldest = self._attempt_times[0]
        return max(0.0, 60.0 - (now_mono - oldest))

    def record_failure(self, now_mono: float) -> float:
        self._attempt_times.append(now_mono)
        self._failures += 1
        delay = self._base_delay_s * (2 ** (self._failures - 1))
        return min(self._max_delay_s, delay)

    def record_success(self) -> None:
        self._failures = 0
        self._attempt_times.clear()


class SubscriptionManager:
    def __init__(self, client: object, min_reapply_interval_s: float = 5.0) -> None:
        self._client = client
        self._min_reapply_interval_s = min_reapply_interval_s
        self._connection_epoch = 0
        self._last_applied_epoch: Optional[int] = None
        self._last_apply_mono: Optional[float] = None
        self._pending = False

    def mark_connected(self) -> None:
        self._connection_epoch += 1
        self._pending = True

    def mark_disconnected(self) -> None:
        self._pending = True

    def mark_pending(self) -> None:
        self._pending = True

    def maybe_apply(
        self,
        contract: Contract,
        req_id: int,
        now_mono: float,
    ) -> bool:
        if not self._pending:
            return False
        if self._last_applied_epoch == self._connection_epoch:
            self._pending = False
            return False
        if (
            self._last_apply_mono is not None
            and now_mono - self._last_apply_mono < self._min_reapply_interval_s
        ):
            return False
        self._client.reqMktData(req_id, contract, "", False, False, [])
        self._last_applied_epoch = self._connection_epoch
        self._last_apply_mono = now_mono
        self._pending = False
        return True


class IBKRAdapter:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: int,
        contract_key: str,
        inbound_queue: InboundQueue,
        exchange: str = "CME",
        currency: str = "USD",
        client: Optional[object] = None,
        fatal_handler=None,
    ) -> None:
        self._host = host
        self._port = port
        self._client_id = client_id
        self._inbound_queue = inbound_queue
        self._contract = build_contract(contract_key, exchange, currency)
        self._contract_key = contract_key
        self._contract_req_id: Optional[int] = None
        self._con_id: Optional[int] = None
        self._fatal_handler = fatal_handler

        if client is None:
            if EClient is None:
                raise RuntimeError("ibapi is required for IBKRAdapter without a client")
            client = EClient(self)
        self._client = client

        self._md_mode = MD_NONE
        self._connected = False
        self._req_id = 1
        self._subscription_manager = SubscriptionManager(self._client)
        self._reconnect_policy = ReconnectPolicy()
        self._stop_event = threading.Event()
        self._connect_thread: Optional[threading.Thread] = None
        self._network_thread: Optional[threading.Thread] = None

    @property
    def md_mode(self) -> str:
        return self._md_mode

    @property
    def con_id(self) -> Optional[int]:
        return self._con_id

    def start(self) -> None:
        self._stop_event.clear()
        if hasattr(self._client, "run"):
            self._network_thread = threading.Thread(
                target=self._client.run, name="ibkr-network", daemon=True
            )
            self._network_thread.start()
        self._connect_thread = threading.Thread(
            target=self._connect_loop, name="ibkr-connect", daemon=True
        )
        self._connect_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self._client.disconnect()
        except Exception:
            pass
        if self._connect_thread:
            self._connect_thread.join(timeout=2.0)
        if self._network_thread:
            self._network_thread.join(timeout=2.0)

    def _connect_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._is_connected():
                if self._con_id is not None:
                    self._subscription_manager.maybe_apply(
                        self._contract, self._market_data_req_id(), time.monotonic()
                    )
                time.sleep(0.5)
                continue

            now_mono = time.monotonic()
            if not self._reconnect_policy.can_attempt(now_mono):
                time.sleep(self._reconnect_policy.cooldown_remaining(now_mono))
                continue

            if self._connect_once():
                self._reconnect_policy.record_success()
                self._on_connected()
            else:
                delay = self._reconnect_policy.record_failure(now_mono)
                time.sleep(delay)

    def _connect_once(self) -> bool:
        try:
            self._client.connect(self._host, self._port, self._client_id)
        except Exception as exc:
            logger.warning("IBKR connect failed: %s", exc)
            return False
        for _ in range(10):
            if self._is_connected():
                return True
            time.sleep(0.1)
        return False

    def _is_connected(self) -> bool:
        if hasattr(self._client, "isConnected"):
            try:
                return bool(self._client.isConnected())
            except Exception:
                return self._connected
        return self._connected

    def _on_connected(self) -> None:
        if self._connected:
            return
        self._connected = True
        self._emit_status(())
        self._request_contract_details_once()
        self._subscription_manager.mark_connected()

    def connectionClosed(self) -> None:  # IBKR callback
        self._connected = False
        self._md_mode = MD_NONE
        self._subscription_manager.mark_disconnected()
        self._emit_status(("DISCONNECTED",))

    def error(self, reqId, errorCode, errorString, *args) -> None:  # IBKR callback
        if errorCode == 326:
            logger.error("IBKR clientId collision (326): %s", errorString)
            self._emit_error(str(errorCode), errorString)
            self._fail_fast(1)
        else:
            self._emit_error(str(errorCode), errorString)

    def marketDataType(self, reqId, marketDataType) -> None:  # IBKR callback
        self._md_mode = map_md_mode(marketDataType)
        self._emit_status(())

    def contractDetails(self, reqId, contractDetails) -> None:  # IBKR callback
        if reqId != self._contract_req_id:
            return
        try:
            con_id = int(contractDetails.contract.conId)
        except Exception:
            con_id = None
        if con_id:
            self._con_id = con_id
            self._contract = contractDetails.contract
            self._subscription_manager.mark_pending()

    def contractDetailsEnd(self, reqId) -> None:  # IBKR callback
        if reqId != self._contract_req_id:
            return
        if self._con_id is None:
            self._emit_error(
                "NO_CONTRACT", f"Contract qualification failed: {self._contract_key}"
            )

    def tickPrice(self, reqId, tickType, price, attrib) -> None:  # IBKR callback
        if tickType == _TICK_BID:
            quote = QuoteEvent(ts_unix_ms=int(time.time() * 1000), bid=price)
        elif tickType == _TICK_ASK:
            quote = QuoteEvent(ts_unix_ms=int(time.time() * 1000), ask=price)
        elif tickType == _TICK_LAST:
            quote = QuoteEvent(ts_unix_ms=int(time.time() * 1000), last=price)
        else:
            return
        self._inbound_queue.put(quote)

    def tickSize(self, reqId, tickType, size) -> None:  # IBKR callback
        if tickType == _TICK_BID_SIZE:
            quote = QuoteEvent(ts_unix_ms=int(time.time() * 1000), bid_size=size)
        elif tickType == _TICK_ASK_SIZE:
            quote = QuoteEvent(ts_unix_ms=int(time.time() * 1000), ask_size=size)
        elif tickType == _TICK_LAST_SIZE:
            quote = QuoteEvent(ts_unix_ms=int(time.time() * 1000), last_size=size)
        else:
            return
        self._inbound_queue.put(quote)

    def _emit_status(self, reason_codes: tuple[str, ...]) -> None:
        event = StatusEvent(
            ts_unix_ms=int(time.time() * 1000),
            connected=self._connected,
            md_mode=self._md_mode,
            reason_codes=reason_codes,
        )
        self._inbound_queue.put(event)

    def _emit_error(self, code: str, message: str) -> None:
        event = AdapterErrorEvent(
            ts_unix_ms=int(time.time() * 1000),
            error_code=code,
            message=message,
        )
        self._inbound_queue.put(event)

    def _request_contract_details_once(self) -> None:
        if self._contract_req_id is not None:
            return
        self._contract_req_id = self._next_req_id()
        self._client.reqContractDetails(self._contract_req_id, self._contract)

    def _next_req_id(self) -> int:
        req_id = self._req_id
        self._req_id += 1
        return req_id

    def _market_data_req_id(self) -> int:
        return 1000

    def _fail_fast(self, code: int) -> None:
        self._stop_event.set()
        try:
            self._client.disconnect()
        except Exception:
            pass
        if self._fatal_handler is not None:
            self._fatal_handler(code)
        raise SystemExit(code)
