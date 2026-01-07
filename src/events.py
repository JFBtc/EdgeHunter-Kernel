"""
Event schemas for adapter→engine communication (V1a J1)

Architecture invariant: Adapter callbacks normalize events and push to queue.
Adapter never mutates shared engine/UI state directly.
"""
from dataclasses import dataclass
from typing import Optional
from enum import Enum


class MarketDataMode(str, Enum):
    """
    Market data mode mapping from IBKR state.

    V1a J1 requirement: exact values per spec.
    """
    REALTIME = "REALTIME"
    DELAYED = "DELAYED"
    FROZEN = "FROZEN"
    NONE = "NONE"


@dataclass(frozen=True)
class StatusEvent:
    """
    Connection/feed status change event.

    Emitted on:
    - Connect/disconnect
    - md_mode changes
    - Adapter-level errors/warnings
    """
    ts_recv_mono_ns: int  # Monotonic receipt time
    ts_recv_unix_ms: int  # Wall clock receipt time

    connected: bool
    md_mode: MarketDataMode

    # Optional reason/error context
    reason: Optional[str] = None
    error_code: Optional[int] = None


@dataclass(frozen=True)
class QuoteEvent:
    """
    L1 market data update event (bid/ask/last).

    V1a J1: L1 only, no depth/T&S.
    """
    ts_recv_mono_ns: int  # Monotonic receipt time (for staleness)
    ts_recv_unix_ms: int  # Wall clock receipt time

    # Contract identity
    con_id: int

    # L1 quote fields (nullable if not available)
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None

    bid_size: Optional[int] = None
    ask_size: Optional[int] = None

    # Exchange timestamp if available from IBKR
    ts_exch_unix_ms: Optional[int] = None


@dataclass(frozen=True)
class AdapterErrorEvent:
    """
    Optional: surfaced IBKR errors (non-fatal warnings or context).

    Fatal errors (e.g., clientId collision) trigger immediate shutdown,
    not event emission.
    """
    ts_recv_mono_ns: int
    ts_recv_unix_ms: int

    error_code: int
    error_msg: str

    # Context for debugging
    request_id: Optional[int] = None
