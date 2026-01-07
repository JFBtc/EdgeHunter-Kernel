"""
Tests for V1a J3 - Hard Gates

Validates:
- Each gate reason triggers correctly
- Deterministic ordering of reasons
- Gate metrics computation
- allowed logic (true only if ALL gates pass)
- Non-flaky tests using deterministic inputs
"""
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
)


def _passing_inputs() -> GateInputs:
    """Create inputs that pass all gates."""
    return GateInputs(
        arm=True,
        intent="LONG",
        in_operating_window=True,
        is_break_window=False,
        feed_connected=True,
        md_mode="REALTIME",
        con_id=12345,
        bid=18500.0,
        ask=18500.25,
        last=18500.0,
        quote_staleness_ms=100,
        last_quote_event_mono_ns=9990000000,
        ts_mono_ns=10000000000,
        spread_ticks=1,
        engine_degraded=False,
    )


def test_all_gates_pass():
    """Test that passing inputs return allowed=True with no reasons."""
    inputs = _passing_inputs()
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is True
    assert reasons == []
    assert len(metrics) > 0


def test_gate_arm_off():
    """Test ARM_OFF gate triggers when arm=False."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "arm": False})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_ARM_OFF in reasons
    assert metrics["arm"] is False


def test_gate_intent_flat():
    """Test INTENT_FLAT gate triggers when intent=FLAT."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "intent": "FLAT"})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_INTENT_FLAT in reasons
    assert metrics["intent"] == "FLAT"


def test_gate_outside_operating_window():
    """Test OUTSIDE_OPERATING_WINDOW gate triggers."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "in_operating_window": False})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_OUTSIDE_OPERATING_WINDOW in reasons
    assert metrics["in_operating_window"] is False


def test_gate_session_break():
    """Test SESSION_BREAK gate triggers during break window."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "is_break_window": True})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SESSION_BREAK in reasons
    assert metrics["is_break_window"] is True


def test_gate_feed_disconnected():
    """Test FEED_DISCONNECTED gate triggers when not connected."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "feed_connected": False})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_FEED_DISCONNECTED in reasons
    assert metrics["connected"] is False


def test_gate_md_not_realtime():
    """Test MD_NOT_REALTIME gate triggers when md_mode != REALTIME."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "md_mode": "DELAYED"})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_MD_NOT_REALTIME in reasons
    assert metrics["md_mode"] == "DELAYED"


def test_gate_no_contract():
    """Test NO_CONTRACT gate triggers when con_id is None."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "con_id": None})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_NO_CONTRACT in reasons
    assert metrics["con_id"] is None


def test_gate_stale_data_quote_missing():
    """Test STALE_DATA gate triggers when quote is missing."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "bid": None, "ask": None, "last": None})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_STALE_DATA in reasons


def test_gate_stale_data_staleness_exceeds_threshold():
    """Test STALE_DATA gate triggers when staleness exceeds threshold."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "quote_staleness_ms": STALE_THRESHOLD_MS + 1})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_STALE_DATA in reasons


def test_gate_spread_unavailable_missing_bid():
    """Test SPREAD_UNAVAILABLE gate triggers when bid is missing."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "bid": None})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_UNAVAILABLE in reasons


def test_gate_spread_wide():
    """Test SPREAD_WIDE gate triggers when spread exceeds threshold."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "spread_ticks": 10})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_WIDE in reasons


def test_gate_engine_degraded():
    """Test ENGINE_DEGRADED gate triggers when engine is degraded."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "engine_degraded": True})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_ENGINE_DEGRADED in reasons
    assert metrics["engine_degraded"] is True


def test_deterministic_ordering():
    """Test that multiple failing gates are ordered deterministically."""
    inputs = GateInputs(
        arm=False,
        intent="FLAT",
        in_operating_window=False,
        is_break_window=True,
        feed_connected=False,
        md_mode="DELAYED",
        con_id=None,
        bid=None,
        ask=None,
        last=None,
        quote_staleness_ms=None,
        last_quote_event_mono_ns=None,
        ts_mono_ns=10000000000,
        spread_ticks=None,
        engine_degraded=True,
    )

    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    expected_order = [
        REASON_ARM_OFF,
        REASON_INTENT_FLAT,
        REASON_OUTSIDE_OPERATING_WINDOW,
        REASON_SESSION_BREAK,
        REASON_FEED_DISCONNECTED,
        REASON_MD_NOT_REALTIME,
        REASON_NO_CONTRACT,
        REASON_STALE_DATA,
        REASON_SPREAD_UNAVAILABLE,
        # SPREAD_WIDE not present (spread unavailable)
        REASON_ENGINE_DEGRADED,
    ]
    assert reasons == expected_order


def test_gate_metrics_always_populated():
    """Test that gate_metrics are always populated."""
    inputs = _passing_inputs()
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    # Verify metrics exist for all gates
    assert "arm" in metrics
    assert "intent" in metrics
    assert "in_operating_window" in metrics
    assert "is_break_window" in metrics
    assert "connected" in metrics
    assert "md_mode" in metrics
    assert "con_id" in metrics
    assert "staleness_ms" in metrics
    assert "last_quote_event_mono_ns" in metrics
    assert "spread_ticks" in metrics
    assert "engine_degraded" in metrics
