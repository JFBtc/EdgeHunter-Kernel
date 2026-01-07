"""
Hard Gates evaluator for V1a (Silent Observer).
Deterministic order and stable reason codes.
"""
from dataclasses import dataclass
from typing import Optional


STALE_THRESHOLD_MS = 2000
MAX_SPREAD_TICKS = 8

REASON_ARM_OFF = "ARM_OFF"
REASON_INTENT_FLAT = "INTENT_FLAT"
REASON_SESSION_NOT_OPERATING = "SESSION_NOT_OPERATING"
REASON_NO_QUOTE = "NO_QUOTE"
REASON_STALE_QUOTE = "STALE_QUOTE"
REASON_FEED_DEGRADED = "FEED_DEGRADED"
REASON_SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"


@dataclass(frozen=True)
class GateInputs:
    arm: bool
    intent: str
    session_phase: str
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    quote_age_ms: Optional[int]
    feed_degraded: bool
    stale_threshold_ms: int = STALE_THRESHOLD_MS
    spread_ticks: Optional[int] = None
    max_spread_ticks: Optional[int] = MAX_SPREAD_TICKS


def _has_complete_quote(bid: Optional[float], ask: Optional[float], last: Optional[float]) -> bool:
    return bid is not None and ask is not None and last is not None


def evaluate_hard_gates(inputs: GateInputs) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if not inputs.arm:
        reasons.append(REASON_ARM_OFF)
    if inputs.intent == "FLAT":
        reasons.append(REASON_INTENT_FLAT)
    if inputs.session_phase != "OPERATING":
        reasons.append(REASON_SESSION_NOT_OPERATING)
    if not _has_complete_quote(inputs.bid, inputs.ask, inputs.last):
        reasons.append(REASON_NO_QUOTE)
    if inputs.quote_age_ms is None or inputs.quote_age_ms > inputs.stale_threshold_ms:
        reasons.append(REASON_STALE_QUOTE)
    if inputs.feed_degraded:
        reasons.append(REASON_FEED_DEGRADED)
    if (
        inputs.spread_ticks is not None
        and inputs.max_spread_ticks is not None
        and inputs.spread_ticks > inputs.max_spread_ticks
    ):
        reasons.append(REASON_SPREAD_TOO_WIDE)

    allowed = len(reasons) == 0
    return allowed, reasons
