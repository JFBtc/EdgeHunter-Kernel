# V1a Milestone J3 - Hard Gates (Silent Observer)

## Summary

This milestone adds a deterministic Hard Gates evaluator per Core Kernel Spec that produces:
- `allowed: bool` (true only if ALL gates pass)
- `reason_codes: list[str]` in stable, deterministic order
- `gate_metrics: dict` with stable keys for audit/logging

The engine computes gate inputs each cycle and publishes them in `SnapshotDTO.gates`.

## Gate Reasons (Ordered per Spec)

The evaluator applies all 11 gates from the V1a spec in this fixed order:

1. `ARM_OFF` — `controls.arm == false`
2. `INTENT_FLAT` — `controls.intent == "FLAT"`
3. `OUTSIDE_OPERATING_WINDOW` — not in operating window
4. `SESSION_BREAK` — in 17:00–18:00 break window
5. `FEED_DISCONNECTED` — `feed.connected == false`
6. `MD_NOT_REALTIME` — `feed.md_mode != "REALTIME"`
7. `NO_CONTRACT` — instrument not qualified (`con_id is null`)
8. `STALE_DATA` — quote missing OR staleness exceeds threshold OR heartbeat timeout
9. `SPREAD_UNAVAILABLE` — bid/ask invalid/unavailable
10. `SPREAD_WIDE` — `spread_ticks > MAX_SPREAD_TICKS` (if spread available)
11. `ENGINE_DEGRADED` — loop stall/overrun threshold exceeded

All failing gates are reported (no short-circuit). Reasons are always emitted in this order for deterministic output.

## Thresholds (Conservative Defaults)

- `STALE_THRESHOLD_MS = 5000` (5 seconds)
- `FEED_HEARTBEAT_TIMEOUT_MS = 10000` (10 seconds)
- `MAX_SPREAD_TICKS = 4` (conservative for MNQ/MES)

These match typical production values for 10 Hz engine loop.

## Integration Notes

- Gates are computed in `src/gates.py` via `evaluate_hard_gates(inputs)` function
- Engine builds `GateInputs` from current snapshot state
- Returns `(allowed, reason_codes, gate_metrics)` tuple
- Engine populates `SnapshotDTO.gates` with results
- Mirrors into `ready` / `ready_reasons` (V1a invariant: `ready == allowed`)
- UI shows `allowed`, `session`, `stale`, `feed`, and `reasons` per cycle

## Architecture Compliance

✅ **Silent Observer**: No order placement or execution logic
✅ **Deterministic**: Same inputs → same ordered reasons
✅ **Stable strings**: Reason codes are constants per spec
✅ **Single source**: Gates read only from snapshot fields
✅ **All gates evaluated**: No short-circuit (all failures reported)
✅ **gate_metrics**: Always populated for audit trail

## Tests

- Unit tests validate each gate reason and verify deterministic ordering in `tests/test_j3_gates.py`
- 17 comprehensive tests covering all gates and ordering
- Non-flaky (deterministic inputs, no real time dependencies)
