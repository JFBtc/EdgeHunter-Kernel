import pytest
from src.gates import (
    GateInputs,
    evaluate_hard_gates,
    REASON_ARM_OFF,
    REASON_INTENT_FLAT,
    REASON_OUTSIDE_OPERATING_WINDOW,
    REASON_SESSION_BREAK,
    REASON_FEED_DISCONNECTED,
    REASON_MD_NOT_REALTIME,
    REASON_NO_CONTRACT,
    REASON_STALE_DATA,
    REASON_SPREAD_UNAVAILABLE,
    REASON_SPREAD_WIDE,
    REASON_ENGINE_DEGRADED,
    STALE_THRESHOLD_MS,
    MAX_SPREAD_TICKS,
)


def _base_inputs() -> GateInputs:
    return GateInputs(
        arm=True,
        intent="LONG",
        session_phase="OPERATING",
        feed_connected=True,
        md_mode="REALTIME",
        contract_qualified=True,
        engine_degraded=False,
        bid=1.0,
        ask=2.0,
        last=1.5,
        quote_age_ms=100,
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


def test_gate_outside_operating_window():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "session_phase": "CLOSED"})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_OUTSIDE_OPERATING_WINDOW in reasons


def test_gate_session_break():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "session_phase": "BREAK"})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_SESSION_BREAK in reasons


def test_gate_feed_disconnected():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "feed_connected": False})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_FEED_DISCONNECTED in reasons


def test_gate_md_not_realtime():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "md_mode": "DELAYED"})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_MD_NOT_REALTIME in reasons


def test_gate_no_contract():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "contract_qualified": False})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_NO_CONTRACT in reasons


def test_gate_spread_unavailable():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "bid": None})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_SPREAD_UNAVAILABLE in reasons


def test_gate_stale_data():
    inputs = _base_inputs().__class__(
        **{**_base_inputs().__dict__, "quote_age_ms": STALE_THRESHOLD_MS + 1}
    )
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_STALE_DATA in reasons


def test_gate_spread_wide():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "spread_ticks": 20})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_SPREAD_WIDE in reasons


def test_gate_engine_degraded():
    inputs = _base_inputs().__class__(**{**_base_inputs().__dict__, "engine_degraded": True})
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    assert REASON_ENGINE_DEGRADED in reasons


def test_gate_reason_ordering():
    """Verify reasons are deterministic and ordered as per doctrine."""
    inputs = GateInputs(
        arm=False,
        intent="FLAT",
        session_phase="CLOSED",
        feed_connected=False,
        md_mode="NONE",
        contract_qualified=False,
        engine_degraded=True,
        bid=None,
        ask=None,
        last=None,
        quote_age_ms=STALE_THRESHOLD_MS + 100,
        spread_ticks=20,
        max_spread_ticks=8,
    )
    allowed, reasons = evaluate_hard_gates(inputs)
    assert allowed is False
    
    # Expected order:
    # 1. ARM
    # 2. INTENT
    # 3. SESSION (CLOSED -> OUTSIDE_OPERATING_WINDOW)
    # 4. FEED (DISCONNECTED + MD + NO_CONTRACT)
    # 5. DATA (STALE + SPREAD_UNAVAILABLE [implied by None bid] + SPREAD_WIDE [implied by spread_ticks? no, if unavailable?])
    
    # Wait, check evaluate_hard_gates logic:
    # _has_complete_quote(None, None, None) -> False -> SPREAD_UNAVAILABLE.
    # spread_ticks=20 -> SPREAD_WIDE? 
    # Logic: if spread_ticks is not None... SPREAD_WIDE.
    # So both SPREAD_UNAVAILABLE and SPREAD_WIDE can appear if inputs allow.
    
    expected = [
        REASON_ARM_OFF,
        REASON_INTENT_FLAT,
        REASON_OUTSIDE_OPERATING_WINDOW,
        REASON_FEED_DISCONNECTED,
        REASON_MD_NOT_REALTIME,
        REASON_NO_CONTRACT,
        REASON_STALE_DATA,
        REASON_SPREAD_UNAVAILABLE,
        REASON_SPREAD_WIDE,
        REASON_ENGINE_DEGRADED,
    ]
    
    assert reasons == expected
