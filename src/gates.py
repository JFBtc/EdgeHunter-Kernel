"""
Hard Gates evaluator for V1a (Silent Observer).
Deterministic order and stable reason codes per Core Kernel Spec.
"""
from dataclasses import dataclass
from typing import Optional


# Thresholds (conservative defaults)
STALE_THRESHOLD_MS = 5000  # 5 seconds
FEED_HEARTBEAT_TIMEOUT_MS = 10000  # 10 seconds
MAX_SPREAD_TICKS = 4  # Conservative for MNQ/MES

# Reason codes (stable strings per V1a spec)
REASON_ARM_OFF = "ARM_OFF"
REASON_INTENT_FLAT = "INTENT_FLAT"
REASON_OUTSIDE_OPERATING_WINDOW = "OUTSIDE_OPERATING_WINDOW"
REASON_SESSION_BREAK = "SESSION_BREAK"
REASON_FEED_DISCONNECTED = "FEED_DISCONNECTED"
REASON_MD_NOT_REALTIME = "MD_NOT_REALTIME"
REASON_NO_CONTRACT = "NO_CONTRACT"
REASON_STALE_DATA = "STALE_DATA"
REASON_SPREAD_UNAVAILABLE = "SPREAD_UNAVAILABLE"
REASON_SPREAD_WIDE = "SPREAD_WIDE"
REASON_ENGINE_DEGRADED = "ENGINE_DEGRADED"


@dataclass(frozen=True)
class GateInputs:
    """Inputs for Hard Gates evaluation."""
    arm: bool
    intent: str
    in_operating_window: bool
    is_break_window: bool
    feed_connected: bool
    md_mode: str
    con_id: Optional[int]
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float]
    quote_staleness_ms: Optional[int]
    last_quote_event_mono_ns: Optional[int]
    ts_mono_ns: int
    spread_ticks: Optional[int]
    engine_degraded: bool
    stale_threshold_ms: int = STALE_THRESHOLD_MS
    feed_heartbeat_timeout_ms: int = FEED_HEARTBEAT_TIMEOUT_MS
    max_spread_ticks: int = MAX_SPREAD_TICKS


def evaluate_hard_gates(inputs: GateInputs) -> tuple[bool, list[str], dict]:
    """
    Evaluate all Hard Gates per V1a spec.

    Args:
        inputs: Gate inputs from current snapshot

    Returns:
        Tuple of (allowed, reason_codes, gate_metrics)
        - allowed: True only if ALL gates pass
        - reason_codes: Ordered list of failing gate reasons
        - gate_metrics: Metrics for each gate check
    """
    reasons: list[str] = []
    metrics: dict = {}

    # Gate 1: ARM_OFF
    if not inputs.arm:
        reasons.append(REASON_ARM_OFF)
    metrics["arm"] = inputs.arm

    # Gate 2: INTENT_FLAT
    if inputs.intent == "FLAT":
        reasons.append(REASON_INTENT_FLAT)
    metrics["intent"] = inputs.intent

    # Gate 3: OUTSIDE_OPERATING_WINDOW
    if not inputs.in_operating_window:
        reasons.append(REASON_OUTSIDE_OPERATING_WINDOW)
    metrics["in_operating_window"] = inputs.in_operating_window

    # Gate 4: SESSION_BREAK
    if inputs.is_break_window:
        reasons.append(REASON_SESSION_BREAK)
    metrics["is_break_window"] = inputs.is_break_window

    # Gate 5: FEED_DISCONNECTED
    if not inputs.feed_connected:
        reasons.append(REASON_FEED_DISCONNECTED)
    metrics["connected"] = inputs.feed_connected

    # Gate 6: MD_NOT_REALTIME
    if inputs.md_mode != "REALTIME":
        reasons.append(REASON_MD_NOT_REALTIME)
    metrics["md_mode"] = inputs.md_mode

    # Gate 7: NO_CONTRACT
    if inputs.con_id is None:
        reasons.append(REASON_NO_CONTRACT)
    metrics["con_id"] = inputs.con_id

    # Gate 8: STALE_DATA
    # Check multiple conditions per spec:
    # - Quote missing (bid/ask/last all None)
    # - quote.staleness_ms > threshold
    # - (now_mono_ns - last_quote_event_mono_ns) > heartbeat timeout
    is_stale = _check_stale_data(inputs)
    if is_stale:
        reasons.append(REASON_STALE_DATA)
    metrics["staleness_ms"] = inputs.quote_staleness_ms
    metrics["last_quote_event_mono_ns"] = inputs.last_quote_event_mono_ns

    # Gate 9: SPREAD_UNAVAILABLE
    if inputs.bid is None or inputs.ask is None:
        reasons.append(REASON_SPREAD_UNAVAILABLE)
    elif inputs.spread_ticks is None or inputs.spread_ticks <= 0:
        reasons.append(REASON_SPREAD_UNAVAILABLE)
    metrics["spread_ticks"] = inputs.spread_ticks

    # Gate 10: SPREAD_WIDE
    # Only check if spread is available
    if (inputs.spread_ticks is not None and
        inputs.spread_ticks > 0 and
        inputs.spread_ticks > inputs.max_spread_ticks):
        reasons.append(REASON_SPREAD_WIDE)

    # Gate 11: ENGINE_DEGRADED
    if inputs.engine_degraded:
        reasons.append(REASON_ENGINE_DEGRADED)
    metrics["engine_degraded"] = inputs.engine_degraded

    # Compute allowed: true only if NO gates failed
    allowed = len(reasons) == 0

    return allowed, reasons, metrics


def _check_stale_data(inputs: GateInputs) -> bool:
    """
    Check if quote data is stale per V1a spec.

    Conditions for STALE_DATA:
    1. Quote missing (bid/ask/last all None)
    2. quote.staleness_ms > STALE_THRESHOLD_MS
    3. (now - last_quote_event_mono_ns) > FEED_HEARTBEAT_TIMEOUT_MS

    Args:
        inputs: Gate inputs

    Returns:
        True if data is stale
    """
    # Condition 1: Quote missing
    if (inputs.bid is None and
        inputs.ask is None and
        inputs.last is None):
        return True

    # Condition 2: Quote staleness exceeds threshold
    if (inputs.quote_staleness_ms is not None and
        inputs.quote_staleness_ms > inputs.stale_threshold_ms):
        return True

    # Condition 3: No quote events for too long (heartbeat timeout)
    if inputs.last_quote_event_mono_ns is not None:
        age_ns = inputs.ts_mono_ns - inputs.last_quote_event_mono_ns
        age_ms = age_ns // 1_000_000
        if age_ms > inputs.feed_heartbeat_timeout_ms:
            return True

    return False
