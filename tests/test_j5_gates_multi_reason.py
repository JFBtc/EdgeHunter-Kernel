"""
Tests for V1a J5 - Hard Gates Multi-Reason & Spread Logic

Validates:
- Multi-reason accumulation (ALL failing gates appear in reason_codes)
- Stable deterministic ordering per spec gate order
- Conservative spread logic: ceil((ask-bid)/tick_size)
- Invalid/missing bid/ask => SPREAD_UNAVAILABLE
- spread_points <= 0 => SPREAD_UNAVAILABLE
- Staleness conditions trigger STALE_DATA
- J4 invariants preserved: ready==allowed, ready_reasons==reason_codes
"""
import pytest
import time

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
    FEED_HEARTBEAT_TIMEOUT_MS,
    MAX_SPREAD_TICKS,
)
from src.datahub import DataHub
from src.engine import EngineLoop


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


def test_j5_multi_reason_two_gates_fail():
    """Test that TWO failing gates produce TWO reason codes."""
    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "arm": False,              # Gate 1 fails
            "intent": "FLAT",          # Gate 2 fails
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert len(reasons) == 2
    assert REASON_ARM_OFF in reasons
    assert REASON_INTENT_FLAT in reasons

    # Verify stable ordering
    assert reasons[0] == REASON_ARM_OFF
    assert reasons[1] == REASON_INTENT_FLAT


def test_j5_multi_reason_five_gates_fail():
    """Test that FIVE failing gates produce FIVE reason codes."""
    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "arm": False,                    # Gate 1 fails
            "in_operating_window": False,    # Gate 3 fails
            "feed_connected": False,         # Gate 5 fails
            "con_id": None,                  # Gate 7 fails
            "engine_degraded": True,         # Gate 11 fails
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert len(reasons) == 5
    assert REASON_ARM_OFF in reasons
    assert REASON_OUTSIDE_OPERATING_WINDOW in reasons
    assert REASON_FEED_DISCONNECTED in reasons
    assert REASON_NO_CONTRACT in reasons
    assert REASON_ENGINE_DEGRADED in reasons


def test_j5_multi_reason_all_gates_fail():
    """Test that ALL 11 gates failing produces all reason codes (except SPREAD_WIDE)."""
    inputs = GateInputs(
        arm=False,                      # Gate 1: ARM_OFF
        intent="FLAT",                  # Gate 2: INTENT_FLAT
        in_operating_window=False,      # Gate 3: OUTSIDE_OPERATING_WINDOW
        is_break_window=True,           # Gate 4: SESSION_BREAK
        feed_connected=False,           # Gate 5: FEED_DISCONNECTED
        md_mode="DELAYED",              # Gate 6: MD_NOT_REALTIME
        con_id=None,                    # Gate 7: NO_CONTRACT
        bid=None,                       # Gate 8: STALE_DATA (quote missing)
        ask=None,                       # Gate 9: SPREAD_UNAVAILABLE
        last=None,
        quote_staleness_ms=None,
        last_quote_event_mono_ns=None,
        ts_mono_ns=10000000000,
        spread_ticks=None,              # Gate 9: SPREAD_UNAVAILABLE
        engine_degraded=True,           # Gate 11: ENGINE_DEGRADED
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False

    # All gates fail except SPREAD_WIDE (can't be wide if unavailable)
    expected_reasons = [
        REASON_ARM_OFF,
        REASON_INTENT_FLAT,
        REASON_OUTSIDE_OPERATING_WINDOW,
        REASON_SESSION_BREAK,
        REASON_FEED_DISCONNECTED,
        REASON_MD_NOT_REALTIME,
        REASON_NO_CONTRACT,
        REASON_STALE_DATA,
        REASON_SPREAD_UNAVAILABLE,
        REASON_ENGINE_DEGRADED,
    ]

    assert len(reasons) == 10
    assert reasons == expected_reasons  # Verify exact stable order


def test_j5_stable_ordering_consistency():
    """Test that reason_codes order is consistent across multiple evaluations."""
    inputs = GateInputs(
        arm=False,
        intent="FLAT",
        in_operating_window=False,
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

    # Evaluate multiple times
    results = []
    for _ in range(10):
        allowed, reasons, metrics = evaluate_hard_gates(inputs)
        results.append(reasons)

    # All results should be identical (stable ordering)
    for i in range(1, len(results)):
        assert results[i] == results[0], "Reason codes ordering is not stable"

    # Verify expected order
    assert results[0] == [
        REASON_ARM_OFF,
        REASON_INTENT_FLAT,
        REASON_OUTSIDE_OPERATING_WINDOW,
    ]


def test_j5_spread_unavailable_missing_bid():
    """Test SPREAD_UNAVAILABLE when bid is None."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "bid": None})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_UNAVAILABLE in reasons


def test_j5_spread_unavailable_missing_ask():
    """Test SPREAD_UNAVAILABLE when ask is None."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "ask": None})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_UNAVAILABLE in reasons


def test_j5_spread_unavailable_both_missing():
    """Test SPREAD_UNAVAILABLE when both bid and ask are None."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "bid": None, "ask": None})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_UNAVAILABLE in reasons
    # Should also trigger STALE_DATA if last is None
    if inputs.last is None:
        assert REASON_STALE_DATA in reasons


def test_j5_spread_unavailable_zero_spread_ticks():
    """Test SPREAD_UNAVAILABLE when spread_ticks is 0 (invalid)."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "spread_ticks": 0})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_UNAVAILABLE in reasons


def test_j5_spread_unavailable_negative_spread_ticks():
    """Test SPREAD_UNAVAILABLE when spread_ticks is negative (crossed market)."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "spread_ticks": -1})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_UNAVAILABLE in reasons


def test_j5_spread_wide_triggers_at_threshold():
    """Test SPREAD_WIDE triggers when spread_ticks > MAX_SPREAD_TICKS."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "spread_ticks": MAX_SPREAD_TICKS + 1})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_SPREAD_WIDE in reasons
    assert REASON_SPREAD_UNAVAILABLE not in reasons  # Spread is available, just wide


def test_j5_spread_wide_exactly_at_threshold_passes():
    """Test spread exactly at MAX_SPREAD_TICKS passes (not wide)."""
    inputs = GateInputs(**{**_passing_inputs().__dict__, "spread_ticks": MAX_SPREAD_TICKS})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    # Should pass (not wide if exactly at threshold)
    assert REASON_SPREAD_WIDE not in reasons


def test_j5_spread_logic_conservative_ceil():
    """
    Test that spread_ticks calculation uses ceil (conservative).

    This is tested at the engine level since gates receive pre-computed spread_ticks.
    Here we verify the logic expectation: fractional ticks round UP.
    """
    # Example: bid=18500.0, ask=18500.50, tick_size=0.25
    # spread_points = 0.50
    # spread_ticks = ceil(0.50 / 0.25) = ceil(2.0) = 2

    # With tick_size=0.25 and spread=0.30:
    # spread_ticks = ceil(0.30 / 0.25) = ceil(1.2) = 2 (conservative)

    # Gates receive spread_ticks=2, should pass if threshold is >= 2
    inputs = GateInputs(**{**_passing_inputs().__dict__, "spread_ticks": 2})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    if MAX_SPREAD_TICKS >= 2:
        assert REASON_SPREAD_WIDE not in reasons
    else:
        assert REASON_SPREAD_WIDE in reasons


def test_j5_stale_data_quote_missing_all_none():
    """Test STALE_DATA when all quote fields (bid, ask, last) are None."""
    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "bid": None,
            "ask": None,
            "last": None,
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_STALE_DATA in reasons


def test_j5_stale_data_staleness_exceeds_threshold():
    """Test STALE_DATA when quote_staleness_ms > STALE_THRESHOLD_MS."""
    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "quote_staleness_ms": STALE_THRESHOLD_MS + 100,
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_STALE_DATA in reasons


def test_j5_stale_data_exactly_at_threshold_passes():
    """Test quote staleness exactly at threshold passes (not stale)."""
    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "quote_staleness_ms": STALE_THRESHOLD_MS,
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    # Exactly at threshold should NOT trigger (only > threshold)
    assert REASON_STALE_DATA not in reasons


def test_j5_stale_data_heartbeat_timeout():
    """Test STALE_DATA when no quote events for too long (heartbeat timeout)."""
    now_ns = 100_000_000_000  # 100 seconds in nanoseconds
    last_quote_ns = now_ns - (FEED_HEARTBEAT_TIMEOUT_MS + 1000) * 1_000_000

    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "ts_mono_ns": now_ns,
            "last_quote_event_mono_ns": last_quote_ns,
            "quote_staleness_ms": 100,  # Quote itself is not stale
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert REASON_STALE_DATA in reasons


def test_j5_stale_data_no_heartbeat_if_recent_quote():
    """Test that recent quotes prevent heartbeat timeout STALE_DATA."""
    now_ns = 100_000_000_000
    last_quote_ns = now_ns - 1_000_000_000  # 1 second ago (well within timeout)

    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "ts_mono_ns": now_ns,
            "last_quote_event_mono_ns": last_quote_ns,
            "quote_staleness_ms": 100,
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    # Should NOT be stale
    assert REASON_STALE_DATA not in reasons


def test_j5_engine_snapshot_invariants():
    """
    Test that engine-published snapshots maintain J4 invariants with gates.

    Validates:
    - ready == gates.allowed
    - ready_reasons == gates.reason_codes
    """
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=50)

    try:
        engine.start()
        time.sleep(0.3)

        # Collect snapshots
        for _ in range(20):
            snapshot = datahub.get_latest()
            if snapshot:
                # J4 Invariant 1: ready == gates.allowed
                assert snapshot.ready == snapshot.gates.allowed, (
                    f"Snapshot {snapshot.snapshot_id}: ready ({snapshot.ready}) != allowed ({snapshot.gates.allowed})"
                )

                # J4 Invariant 2: ready_reasons == gates.reason_codes
                assert snapshot.ready_reasons == snapshot.gates.reason_codes, (
                    f"Snapshot {snapshot.snapshot_id}: ready_reasons ({snapshot.ready_reasons}) != reason_codes ({snapshot.gates.reason_codes})"
                )

            time.sleep(0.03)

    finally:
        engine.stop()


def test_j5_no_precedence_all_failures_reported():
    """
    Test that there is NO precedence logic hiding failures.

    When multiple gates fail, ALL failures must be reported in reason_codes.
    This is a critical J5 requirement: no "winner-takes-all" or "first-failure-only".
    """
    # Fail first 3 gates
    inputs = GateInputs(
        arm=False,                      # Gate 1 fails
        intent="FLAT",                  # Gate 2 fails
        in_operating_window=False,      # Gate 3 fails
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

    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert len(reasons) == 3, "All 3 failing gates must be reported"
    assert REASON_ARM_OFF in reasons
    assert REASON_INTENT_FLAT in reasons
    assert REASON_OUTSIDE_OPERATING_WINDOW in reasons


def test_j5_spread_wide_does_not_hide_other_failures():
    """Test that SPREAD_WIDE co-exists with other failing gates."""
    inputs = GateInputs(
        **{
            **_passing_inputs().__dict__,
            "arm": False,                         # Gate 1 fails
            "spread_ticks": MAX_SPREAD_TICKS + 5,  # Gate 10 fails (wide)
        }
    )
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert len(reasons) == 2
    assert REASON_ARM_OFF in reasons
    assert REASON_SPREAD_WIDE in reasons


def test_j5_reason_codes_are_strings():
    """Test that all reason codes are strings (not enums or other types)."""
    inputs = GateInputs(
        arm=False,
        intent="FLAT",
        in_operating_window=False,
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

    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    for reason in reasons:
        assert isinstance(reason, str), f"Reason code must be string, got {type(reason)}"


def test_j5_allowed_true_only_if_no_reasons():
    """Test that allowed=True only when reason_codes is empty."""
    # All gates pass
    inputs = _passing_inputs()
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is True
    assert reasons == []

    # One gate fails
    inputs = GateInputs(**{**_passing_inputs().__dict__, "arm": False})
    allowed, reasons, metrics = evaluate_hard_gates(inputs)

    assert allowed is False
    assert len(reasons) > 0
