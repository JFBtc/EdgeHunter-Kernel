# Core Kernel — V1b Outline (Post-V1a)

**Project:** IBKR MNQ/MES (single instrument per run)  
**Status:** Planning document (V1b)  
**Prereq:** V1a is complete and tagged as a stable baseline.

---

## 0) Purpose

V1b exists to **make V1a easier to validate and extend safely** without expanding trading scope.

V1b focuses on:
1) **Deterministic testing without IBKR** (MOCK / replay harness)  
2) **Schema non-regression** (Snapshot + TriggerCard validation + golden tests)  
3) **Basic observability** (minimal metrics + run summary)

V1b still remains a **Silent Observer**: no execution, no strategy.

---

## 1) V1b Non-goals (explicit exclusions)

V1b must NOT add:
- Order placement / execution / brackets / position state
- Time & Sales ingestion or aggressor inference
- Historical seeding (ATR/VWAP/pivots), backtest framework, research pipeline
- Multi-instrument in one run (MNQ+MES together)
- Any H2/H3 strategy logic

---

## 2) “Seal V1a” policy (core freeze)

### 2.1 Freeze rule
Once V1a passes acceptance, **V1a is sealed**:
- Tag the repo: `v1a.0`
- Treat the V1a “core kernel” as **stable API**
- All new functionality goes into **plugins/modules** (or separate packages) that consume snapshots/events.

### 2.2 What is “core kernel”
Core kernel refers to the V1a responsibility set:
- IBKR connectivity adapter (events → inbound queue)
- Engine loop (single-writer) publishing atomic Snapshot
- Hard Gates evaluation
- TriggerCard append-only logging
- UI read-only rendering + command queue boundaries

### 2.3 Allowed changes after seal
Only:
- Bug fixes that preserve public schemas and invariants
- Reliability improvements that do not change meaning of fields/codes
- Performance fixes that do not change behavior (except timing improvements)

### 2.4 Change-control (recommended)
- Protect `main` (or `baseline/v1a`) branch.
- Require PR + review checklist for any changes under `/core` (or equivalent).
- If a schema must change: bump `schema_version` and provide migration notes + golden test updates.

---

## 3) Extension model (plugins) — V1b expectation

V1b assumes the project evolves via modules/plugins that:
- Subscribe to the latest published Snapshot (read-only)
- Optionally subscribe to a normalized event stream (read-only)
- Produce outputs into separate logs/artifacts or UI panels

### 3.1 Core-owned contracts (must remain stable)
- `SnapshotDTO` (`snapshot.v1`)  
- `TriggerCard` (`triggercard.v1`)  
- `HardGate codes` (stable string enum list)  
- Event envelope (if present): `event_type`, `source`, `mono_ts_ns`, `payload`

### 3.2 Reserved extensibility fields (recommended)
To avoid breaking schemas when adding V1c/V2 features:
- `SnapshotDTO.extras: dict` (default `{}`)  
- `TriggerCard.extras: dict` (default `{}`)

---

## 4) V1b Scope — Deliverables

### 4.1 MOCK feed harness (no IBKR required)
**Goal:** Allow the engine loop to run end-to-end with synthetic or replayed L1 events.

Minimum requirements:
- A feed adapter `MOCK` mode producing normalized quote events (bid/ask/last + timestamps)
- Adjustable characteristics:
  - update rate (Hz)
  - random jitter
  - scheduled “silence” windows (simulate staleness)
  - scheduled “spread widening” windows
  - disconnect/reconnect simulation (feed disconnected flag)
- Must integrate through the same inbound queue/event envelope as IBKR adapter.

Acceptance hints:
- The same run with the same seed should be reproducible.
- Gates should flip deterministically based on configured scenarios.

### 4.2 Replay mode (optional but high value)
**Goal:** Feed recorded events back into the loop for deterministic regression tests.

Minimum requirements:
- JSONL input events (normalized envelope)
- Playback speed control: realtime, faster-than-realtime
- Deterministic scheduling using monotonic timestamps derived from the event stream

### 4.3 Schema validation + golden tests
**Goal:** Prevent schema drift and regressions.

Minimum requirements:
- Validation for:
  - `snapshot.v1`
  - `triggercard.v1`
- Golden test files committed:
  - minimal valid snapshot example
  - minimal valid triggercard example
  - at least one example including common gates (ARM_OFF, STALE_DATA, SPREAD_WIDE)
- Tests should fail if:
  - required fields removed
  - types changed
  - hard gate codes renamed/removed
  - invariants violated (e.g., `allowed` vs reasons inconsistencies)

### 4.4 Observability (minimal)
**Goal:** Enable fast diagnosis of “why allowed=NO” and “why degraded”.

Minimum requirements:
- Counters:
  - reconnect_count
  - inbound_events_total
  - inbound_events_dropped (if bounded queue)
  - cycles_total
  - cycle_overrun_total
- Gauges:
  - last_quote_age_ms
  - current_spread_ticks
  - inbound_queue_depth
- End-of-run summary (stdout + file):
  - uptime
  - counts above
  - top reason_codes frequency

---

## 5) V1b Acceptance Criteria (definition of done)

A V1b implementation is accepted when:

### 5.1 Deterministic validation (MOCK)
- Engine runs ≥ 30 minutes in `MOCK` mode without crash.
- Gates switch correctly under scripted scenarios:
  - silence → `STALE_DATA`
  - spread widen → `SPREAD_WIDE`
  - disconnect → `FEED_DISCONNECTED`
- TriggerCards are written append-only and parseable.

### 5.2 Golden tests
- `pytest -q` passes locally from a clean environment.
- Golden schemas catch breaking changes.

### 5.3 No scope creep
- No execution, no strategies, no T&S added.

---

## 6) Implementation notes (guardrails)

- Prefer “additive” changes to V1a contracts:
  - add `extras` dicts, add new optional fields, never change meanings.
- Keep V1b changes isolated:
  - `feeds/mock_feed.py`, `tests/golden/`, `validation/`, `metrics/`
- Never route plugin logic back into core state mutation.

---

## 7) Recommended repo tags & milestones

- `v1a.0` — sealed V1a baseline  
- `v1b.0` — MOCK + golden tests + minimal metrics accepted  
- Next milestones (examples):
  - `v1c.0` — optional: event stream recorder + replay tooling hardened
  - `v2.0` — out of scope: T&S, execution, strategy engines (separate specs)

