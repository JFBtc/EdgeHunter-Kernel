# V1a Milestone J3 - Hard Gates (Silent Observer)

## Summary

This milestone adds a deterministic Hard Gates evaluator that produces:
- `allowed: bool`
- `reason_codes: list[str]` in stable, ordered form

The engine computes gate inputs each cycle and publishes them in `SnapshotDTO.gates`.

## Gate Reasons (Ordered)

The evaluator applies gates in this fixed order:

1. `ARM_OFF` — `controls.arm == false`
2. `INTENT_FLAT` — `controls.intent == "FLAT"`
3. `SESSION_NOT_OPERATING` — session phase is not `OPERATING`
4. `NO_QUOTE` — bid/ask/last missing
5. `STALE_QUOTE` — quote age is `None` or `> STALE_THRESHOLD_MS`
6. `FEED_DEGRADED` — feed is degraded (disconnected or md_mode != REALTIME)
7. `SPREAD_TOO_WIDE` — spread_ticks exceeds `MAX_SPREAD_TICKS` (if available)

Reasons are always emitted in this order for deterministic output.

## Thresholds

- `STALE_THRESHOLD_MS = 2000`
- `MAX_SPREAD_TICKS = 8`

## Integration Notes

- Gates are computed in `src/gates.py` and consumed by the engine.
- The engine builds `SnapshotDTO.gates.allowed` and `SnapshotDTO.gates.reason_codes`
  and mirrors them into `ready` / `ready_reasons` (V1a invariant).
- UI shows `allowed`, `session`, `stale`, and `reasons` per cycle.

## Tests

- Unit tests validate each gate reason and verify deterministic ordering in
  `tests/test_j3_gates.py`.
