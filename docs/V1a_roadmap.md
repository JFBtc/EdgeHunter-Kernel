Turn the V1a Spec + V1a Checklist into a step-by-step milestone roadmap so progress is easy to track, agents cannot drift, and reviews are mechanical.

Rules of engagement

1 prompt = 1 milestone (or a single BLOCKER fix).

No milestone skipping. If an agent touches something outside the milestone, it must be justified as “strictly required plumbing”.

Non-goals are always enforced: no execution, no T&S, no historical seeding, no multi-instrument per run, no contract roll/front-month resolver.

Evidence required before any new milestone prompt (State Pack)

Paste these 5 items before starting the next milestone:

Branch + HEAD commit hash

git diff --stat (must be empty or explained)

pytest -q result

60s smoke run output (MOCK or IB)

Any anomaly observed (staleness, spread, reconnect storm, UI lag, crash)

If State Pack is missing, the “next prompt” is not issued.

Milestones (V1a)
J0 — Scope Guardrails (always-on)

Objective: Ensure V1a boundaries cannot be violated accidentally.
Done when:

No order placement surface exists (no IB order calls, no order objects wired).

No T&S ingestion path exists.

Single-instrument-per-run is enforced at config/runtime.

Artifacts/Evidence:

Quick scan result: no order APIs referenced.

Repo run starts without any execution hooks.

J1 — IBKR Adapter MVP (connect/qualify/L1/md_mode)

Objective: Reliable connectivity and L1 feed plumbing without churn.
Done when:

Safe connect/disconnect with backoff/storm control.

Qualify explicit-expiry contract_key → conId (single instrument).

L1 subscription is idempotent (no hot-loop resubscribe).

md_mode exposed as: REALTIME | DELAYED | FROZEN | NONE.

IB error 326 (clientId collision) fails fast (safe exit non-zero).

Artifacts/Evidence:

Smoke run shows connect + qualify + L1 ticks arriving.

Reconnect test does not duplicate subscriptions.

J2 — Time + Liveness + Session Windows

Objective: Correct time semantics and session behavior.
Done when:

Staleness uses monotonic time only.

Track last_any_event_mono, last_quote_event_mono.

Operating window + break window (17:00–18:00 ET) are enforced as state, not UI hacks.

Artifacts/Evidence:

Simulated quote silence triggers staleness detection deterministically.

Break window flips gates appropriately.

J3 — Engine Loop + Single-Writer + CommandQueue

Objective: Deterministic cycle that is the only writer of state.
Done when:

Adapter pushes events → InboundQueue only.

Engine drains queue at cycle start; writes state once per cycle.

UI is render-only; commands (Intent/ARM) applied only at cycle boundary.

Overrun/latency produces ENGINE_DEGRADED.

Artifacts/Evidence:

No shared-state mutation from callbacks/UI.

Cycle timing metrics show bounded behavior.

J4 — SnapshotDTO v1 (Atomic Publication) + ready==allowed

Objective: Atomic snapshot contract, immutable-by-convention.
Done when:

Snapshot is published atomically (copy-on-write) with monotonic snapshot_id.

schema_version = snapshot.v1.

ready == allowed and ready_reasons == reason_codes.

UI never sees partial updates.

Artifacts/Evidence:

Snapshot JSON shape stable across cycles.

No partial fields during fast updates.

J5 — Hard Gates (Stable reason_codes) + Spread Logic

Objective: “Allowed” decision is correct, conservative, and explainable.
Done when:

Hard gates implemented with stable reason_codes (multi-reason).

spread_ticks = ceil((ask-bid)/tick_size) conservative.

Missing/invalid bid/ask → SPREAD_UNAVAILABLE.

Quote staleness → STALE_QUOTES.

Artifacts/Evidence:

Controlled scenarios produce expected reason_codes.

reason_codes don’t change format/order unexpectedly.

J6 — TriggerCards Logger (JSONL, append-only, fixed cadence)

Objective: Durable, audit-friendly logging independent of engine cadence.
Done when:

Append-only JSONL, crash-tolerant (last line may truncate).

Fixed cadence (e.g., 1 Hz) decoupled from loop.

Rotation by local date + run_id.

schema_version = triggercard.v1.

Artifacts/Evidence:

JSONL parses fully except possibly last truncated line after forced kill.

Rotation occurs as specified.

J7 — Final Soak Test (V1a done criteria)

Objective: Prove stability in realistic runtime.
Done when:

4h run in operating window (or agreed duration) without leaks/churn.

Clean shutdown.

Logs valid and gates responsive.

Artifacts/Evidence:

Summary report: uptime, reconnect count, staleness events, logger status, max cycle time.

Standard Agent Output (mandatory for every milestone)

Agents must include a final section:

Audit & Divergence Report

Spec gaps: what remains missing for the current milestone + any later milestones noticed but not touched

Repo divergences: any behavior violating V1a non-goals or invariants (even pre-existing)

Scope creep risks: what was explicitly rejected as out-of-scope
If blocked: write BLOCKER and the minimal prerequisite fix.

How to use this roadmap in practice

You pick the next milestone (normally the first not “Done”).

The prompt explicitly says: “Implement Jx only.”

Review becomes mechanical: verify acceptance criteria + evidence + divergence report.

Then move to Jx+1.