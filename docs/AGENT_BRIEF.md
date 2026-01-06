# Agent Brief — EdgeHunter-Kernel (V1a)

## Goal (V1a)
Implement the **Core Kernel V1a** “Silent Observer”:
- stable live loop
- IBKR connectivity + L1 ingestion
- atomic Snapshot publication
- Hard Gates evaluation
- append-only TriggerCards (JSONL)
- UI read-only (may be minimal)

## Non-goals (must NOT be added)
- Any order placement/execution (no brackets/OCO/positions)
- Time & Sales ingestion / aggressor inference
- Strategy logic / entry signals (beyond gates YES/NO)
- Historical seeding/backtest/replay/ML
- Multi-instrument per run (single instrument only)

## Architectural invariants
- Adapter callbacks never mutate shared state; push normalized events into an inbound queue.
- Engine loop is the **single writer** that drains events and publishes an **atomic SnapshotDTO** (copy-on-write).
- UI reads snapshots only; UI never calls IBKR.
- UI commands go through a bounded CommandQueue; applied only at cycle boundaries.

## Required outputs
- `SnapshotDTO` schema: `snapshot.v1` (versioned)
- `TriggerCard` schema: `triggercard.v1` (versioned)
- Stable Hard Gate codes as defined in `docs/V1A_CHECKLIST.md`

## Acceptance (definition of done)
- Runs without crash and degrades safely (disconnects/stale/spread).
- Snapshot publication is atomic (no partial reads).
- TriggerCards are append-only JSONL and parseable after interruption (last line may be truncated).
- Hard Gates produce consistent `allowed` + `reason_codes[]` (multi-reason, no “winner”).
- No scope creep (Non-goals remain true).

## Delivery format
- One PR per agent branch against `main`.
- Keep commits small and descriptive.
- Include a minimal runbook in README (PowerShell commands) once code exists.
