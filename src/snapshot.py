"""
SnapshotDTO - Atomic snapshot schema (snapshot.v1)
V1a J2: Added liveness, session, feed state, and quote staleness
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class InstrumentDTO:
    """Instrument identity and contract info."""
    symbol: str = "MNQ"
    contract_key: str = "MNQ.202603"
    con_id: Optional[int] = None
    tick_size: float = 0.25


@dataclass(frozen=True)
class FeedDTO:
    """Feed connection and market data mode."""
    connected: bool = False
    md_mode: str = "NONE"  # REALTIME | DELAYED | FROZEN | NONE
    degraded: bool = False
    status_reason_codes: list[str] = field(default_factory=list)
    last_status_change_mono_ns: Optional[int] = None


@dataclass(frozen=True)
class QuoteDTO:
    """L1 quote data with staleness."""
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    ts_recv_unix_ms: Optional[int] = None
    ts_recv_mono_ns: Optional[int] = None
    ts_exch_unix_ms: Optional[int] = None
    staleness_ms: Optional[int] = None
    spread_ticks: Optional[int] = None


@dataclass(frozen=True)
class SessionDTO:
    """Session date and window state."""
    in_operating_window: bool = False
    is_break_window: bool = False
    session_date_iso: str = ""


@dataclass(frozen=True)
class ControlsDTO:
    """User controls (Intent/ARM) and command tracking."""
    intent: str = "FLAT"  # LONG | SHORT | BOTH | FLAT
    arm: bool = False
    last_cmd_id: int = 0
    last_cmd_ts_unix_ms: Optional[int] = None


@dataclass(frozen=True)
class LoopHealthDTO:
    """Engine loop health metrics."""
    cycle_ms: int = 0
    cycle_overrun: bool = False
    engine_degraded: bool = False
    last_cycle_start_mono_ns: int = 0


@dataclass(frozen=True)
class GatesDTO:
    """Hard Gates output."""
    allowed: bool = False
    reason_codes: list[str] = field(default_factory=list)
    gate_metrics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SnapshotDTO:
    """
    Immutable snapshot published atomically by the engine loop.
    Schema version: snapshot.v1

    V1a J2: Complete schema with liveness, session, and staleness tracking.
    """
    # Schema metadata
    schema_version: str = "snapshot.v1"
    app_version: str = ""
    config_hash: str = ""

    # Run identity
    run_id: str = ""
    run_start_ts_unix_ms: int = 0
    snapshot_id: int = 0
    cycle_count: int = 0
    ts_unix_ms: int = 0
    ts_mono_ns: int = 0

    # Nested DTOs (structured per spec)
    instrument: InstrumentDTO = field(default_factory=InstrumentDTO)
    feed: FeedDTO = field(default_factory=FeedDTO)
    quote: QuoteDTO = field(default_factory=QuoteDTO)
    session: SessionDTO = field(default_factory=SessionDTO)
    controls: ControlsDTO = field(default_factory=ControlsDTO)
    loop: LoopHealthDTO = field(default_factory=LoopHealthDTO)
    gates: GatesDTO = field(default_factory=GatesDTO)

    # Liveness tracking (J2 requirement)
    last_any_event_mono_ns: Optional[int] = None
    last_quote_event_mono_ns: Optional[int] = None
    quotes_received_count: int = 0

    # Ready mapping (V1a: ready == allowed)
    ready: bool = False
    ready_reasons: list[str] = field(default_factory=list)

    # Reserved for future extensions
    extras: dict = field(default_factory=dict)
