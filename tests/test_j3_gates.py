import pytest

from src.gates import (
    GateInputs,
    evaluate_hard_gates,
    REASON_ARM_OFF,
    REASON_INTENT_FLAT,
    REASON_SESSION_NOT_OPERATING,
    REASON_NO_QUOTE,
    REASON_STALE_QUOTE,
    REASON_FEED_DEGRADED,
    REASON_SPREAD_TOO_WIDE,
    STALE_THRESHOLD_MS,
)


def _base_inputs() -> GateInputs:
    return GateInputs(
        arm=True,
        intent="LONG",
        session_phase="OPERATING",
        bid=1.0,
        ask=2.0,
        last=1.5,
        quote_age_ms=100,
        feed_degraded=False,
        spread_ticks=2,
        max_spread_ticks=8,
    )


def test_gate_arm_off():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "arm": False})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_ARM_OFF in reasons


def test_gate_intent_flat():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "intent": "FLAT"})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_INTENT_FLAT in reasons


def test_gate_session_not_operating():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "session_phase": "BREAK"})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_SESSION_NOT_OPERATING in reasons


def test_gate_no_quote():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "bid": None})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_NO_QUOTE in reasons


def test_gate_stale_quote():
    inputs = _base_inputs().__class__(
        **{**_base_inputs().__dict__, "quote_age_ms": STALE_THRESHOLD_MS + 1}
    )
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_STALE_QUOTE in reasons


def test_gate_feed_degraded():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "feed_degraded": True})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_FEED_DEGRADED in reasons


def test_gate_spread_too_wide():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "spread_ticks": 20})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_SPREAD_TOO_WIDE in reasons


def test_gate_reason_ordering():
    inputs = GateInputs(
        arm=False,
        intent="FLAT",
        session_phase="CLOSED",
        bid=None,
        ask=None,
        last=None,
        quote_age_ms=None,
        feed_degraded=True,
        spread_ticks=20,
        max_spread_ticks=8,
    )
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert reasons == [
        REASON_ARM_OFF,
        REASON_INTENT_FLAT,
        REASON_SESSION_NOT_OPERATING,
        REASON_NO_QUOTE,
        REASON_STALE_QUOTE,
        REASON_FEED_DEGRADED,
        REASON_SPREAD_TOO_WIDE,
    ]
