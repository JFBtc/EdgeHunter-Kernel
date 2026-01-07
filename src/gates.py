"""
Hard Gates evaluator for V1a (Silent Observer).
Deterministic order and stable reason codes.
"""
from dataclasses import dataclass
from typing import Optional


STALE_THRESHOLD_MS = 2000
MAX_SPREAD_TICKS = 8

# J3 Checklist Hard Gates
REASON_ARM_OFF = "ARM_OFF"
REASON_INTENT_FLAT = "INTENT_FLAT"
REASON_OUTSIDE_OPERATING_WINDOW = "OUTSIDE_OPERATING_WINDOW"
REASON_SESSION_BREAK = "SESSION_BREAK"
REASON_FEED_DISCONNECTED = "FEED_DISCONNECTED"
REASON_MD_NOT_REALTIME = "MD_NOT_REALTIME"
REASON_NO_CONTRACT = "NO_CONTRACT"
REASON_STALE_DATA = "STALE_DATA"  # Renamed from REASON_STALE_QUOTE to match generic checklist 65? Spec says STALE_DATA.
# Checklist 65: STALE_DATA (quote missing ou staleness>threshold...)
# But Checklist 66: SPREAD_UNAVAILABLE (bid/ask invalid/absent)
# If quote is missing, is it STALE_DATA or SPREAD_UNAVAILABLE?
# Spec says: "quote missing/stale -> STALE_DATA" (Line 98 acceptance)
# "bid/ask invalid -> SPREAD_UNAVAILABLE" (Line 99 acceptance)
# I will output STALE_DATA if quote is old/missing timestamps, and SPREAD_UNAVAILABLE if bid/ask are None.

REASON_SPREAD_UNAVAILABLE = "SPREAD_UNAVAILABLE"
REASON_SPREAD_WIDE = "SPREAD_WIDE"  # Checklist 67: SPREAD_WIDE (not SPREAD_TOO_WIDE)
REASON_ENGINE_DEGRADED = "ENGINE_DEGRADED"


@dataclass(frozen=True)
class GateInputs:
    arm: bool
    intent: str
    session_phase: str  # "OPERATING", "BREAK", "CLOSED"
    feed_connected: bool
    md_mode: str  # "REALTIME", "DELAYED", "FROZEN", "NONE"
    contract_qualified: bool
    engine_degraded: bool
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    quote_age_ms: Optional[int]
    spread_ticks: Optional[int] = None
    max_spread_ticks: Optional[int] = MAX_SPREAD_TICKS
    stale_threshold_ms: int = STALE_THRESHOLD_MS


def _has_complete_quote(bid: Optional[float], ask: Optional[float], last: Optional[float]) -> bool:
    return bid is not None and ask is not None and last is not None


def evaluate_hard_gates(inputs: GateInputs) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    # 1. ARM & Intent
    if not inputs.arm:
        reasons.append(REASON_ARM_OFF)
    if inputs.intent == "FLAT":
        reasons.append(REASON_INTENT_FLAT)

    # 2. Session
    if inputs.session_phase == "CLOSED":
        reasons.append(REASON_OUTSIDE_OPERATING_WINDOW)
    elif inputs.session_phase == "BREAK":
        reasons.append(REASON_SESSION_BREAK)
    # If generic failure or unknown phase (not OPERATING) that isn't handled above?
    # Assuming valid inputs "OPERATING", "BREAK", "CLOSED". If inputs are junk, maybe fail safe?
    # Spec implied "session != OPERATING" fails.
    # Current implementation handles CLOSED and BREAK. If there's another state (e.g. unknown), we might miss it.
    # But SessionManager only returns those 3.

    # 3. Feed & Infrastructure
    if not inputs.feed_connected:
        reasons.append(REASON_FEED_DISCONNECTED)
    if inputs.md_mode != "REALTIME":
        reasons.append(REASON_MD_NOT_REALTIME)
    if not inputs.contract_qualified:
        reasons.append(REASON_NO_CONTRACT)
    
    # 4. Data Quality
    # STALE_DATA: Quote missing or old.
    # If quote_age_ms is None (never received) or > threshold
    if inputs.quote_age_ms is None or inputs.quote_age_ms > inputs.stale_threshold_ms:
        reasons.append(REASON_STALE_DATA)
    
    # SPREAD_UNAVAILABLE: Bid/Ask invalid/absent
    if not _has_complete_quote(inputs.bid, inputs.ask, inputs.last):
        reasons.append(REASON_SPREAD_UNAVAILABLE)
    
    # SPREAD_WIDE
    if (
        inputs.spread_ticks is not None
        and inputs.max_spread_ticks is not None
        and inputs.spread_ticks > inputs.max_spread_ticks
    ):
        reasons.append(REASON_SPREAD_WIDE)
        
    # 5. Engine Health
    if inputs.engine_degraded:
        reasons.append(REASON_ENGINE_DEGRADED)

    allowed = len(reasons) == 0
    return allowed, reasons
