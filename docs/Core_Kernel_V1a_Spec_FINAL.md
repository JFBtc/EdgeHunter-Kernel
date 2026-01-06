# Core Kernel Spec — V1a (Silent Observer)
**IBKR Futures (MNQ *or* MES) — Single-instrument per run — L1-only — No execution — No strategy — No historical seeding**

---

## 0) Objective
Build a **refactor-cheap** kernel that proves the system can run a stable live loop in real IBKR conditions:

1. Connect / reconnect safely (including “zombie” and reset-like behaviors)
2. Subscribe once (idempotent) to **L1 quotes** for exactly **one** instrument
3. Ingest inbound events via an internal queue (callbacks never mutate shared state)
4. Produce an **atomic SnapshotDTO** once per engine cycle (copy-on-write)
5. Run **Hard Gates** that output `allowed` + stable `reason_codes`
6. Write **append-only TriggerCards** to disk at a **fixed cadence** (default 1 Hz), crash-tolerant
7. Drive a **render-only UI** + a bounded command channel (Intent/ARM)

V1a is a **Silent Observer**: it can display “Would Trade” signals, but **must never place orders**.

---

## 1) Non-goals (explicit exclusions)
V1a must NOT include:
- Any order placement, order tracking, OCO/brackets, position sync/reconciliation
- Time & Sales ingestion / aggressor classification
- Historical seeding (ATR/VWAP/levels), backtesting, replay, ML (XGBoost, etc.)
- Multi-instrument logic (no MNQ+MES in V1a)
- “Front-month resolver” / roll logic (see Contract policy below)

---

## 2) High-level architecture (single-writer kernel)
**Producer/Consumer model (no shared writes across threads):**
- **Adapter (IBKR)** receives callbacks and pushes normalized events into an **InboundQueue**.
- **Engine loop** drains the queue at cycle start, updates internal state, then **publishes a new SnapshotDTO**.
- **UI** reads only the **last published SnapshotDTO** (never partially updated).
- **UI** writes commands to a **bounded CommandQueue**; Engine applies them at **cycle boundary** only.

Key invariants:
- Adapter does **not** touch SnapshotDTO.
- UI never calls IBKR.
- Engine is the **only writer** of SnapshotDTO.

---

## 3) Modules and responsibilities (V1a)

### A) IBKR Adapter (single point of contact)
**Purpose:** connect to IBKR, manage subscriptions, normalize inbound events.

Must provide:
- Connect / disconnect with exponential backoff + storm control
- Contract qualification for one instrument (`contract_key` → conId)
- L1 market data subscription (bid/ask/last + sizes if available)
- Mapping of IBKR market data mode to `md_mode`:
  - `REALTIME | DELAYED | FROZEN | NONE`
- Idempotent subscription manager:
  - Maintain `desired_subscriptions`
  - Apply once on connect
  - Re-apply on reconnect (rate-limited)
  - **Never resubscribe in the hot loop**
- Heartbeat/watchdog inputs:
  - Emit status changes (connected/disconnected + md_mode changes)
  - Ensure inbound queue is populated only by actual events

Adapter outputs **normalized events** only:
- `StatusEvent`
- `QuoteEvent` (L1)
- (Optional) `AdapterErrorEvent` (for surfaced IBKR errors)

**Fail-fast:** detect clientId collision (IBKR error 326 “clientId already in use”), log and exit non-zero.

---

### B) Session & Clock Manager
**Purpose:** provide canonical time semantics.

Must provide:
- Timezone: **America/Toronto**
- Session date concept (rolls at 17:00 ET if you want “futures session date”)
- Break detection: **17:00–18:00 ET**
- Operating window (configurable): default **07:00–16:00 ET**
- Helper functions for:
  - `now_unix_ms()`
  - `now_mono_ns()` (monotonic)
  - `in_operating_window()`
  - `is_break_window()`

---

### C) Engine Loop (single deterministic loop)
**Purpose:** drain inbound queue, build SnapshotDTO, run gates, publish snapshot, log triggercard.

Cycle rules:
- Drain **all** inbound events at cycle start (bounded drain if needed to prevent starvation)
- Apply UI commands **only at cycle boundary**
- Publish one atomic SnapshotDTO per cycle (copy-on-write)
- Compute cycle timing with monotonic clock
- Enforce sleep rule:
  - `sleep_ms = max(0, CYCLE_TARGET_MS - cycle_compute_ms)`

---

### D) DataHub (Snapshot publisher)
**Purpose:** publish the latest SnapshotDTO atomically.

Rules:
- UI reads the **last published** snapshot only
- Snapshot objects are immutable (or treated as immutable by convention)
- Snapshot ids are monotonic per run

---

### E) GatesEngine (Hard Gates only)
**Purpose:** compute a single boolean `allowed` and stable `reason_codes[]`.

Gates are **hard**: if any gate fails → `allowed=false`.

---

### F) TriggerLogger (append-only)
**Purpose:** write TriggerCards to disk for offline analysis.

Rules:
- **Cadence is decoupled from engine loop**. Default: **1 Hz fixed**.
- Each TriggerCard references the **latest published SnapshotDTO at log time**.
- Crash-tolerant JSONL:
  - Append-only; flush periodically
  - Last line may be truncated on kill; must be detectable/ignorable in parsing
- Rotation rule (minimal, deterministic):
  - Filename includes local date + run_id
  - Rotate on local date change (or on restart)

---

### G) UI (render-only) + Commands
**Purpose:** display state and let user set Intent/ARM.

Rules:
- UI reads SnapshotDTO only
- UI writes commands to CommandQueue only (no direct mutation of SnapshotDTO)

CommandQueue semantics:
- Bounded queue (default size 100)
- Coalescing per cycle (last-write-wins):
  - Keep only the latest Intent and latest ARM seen before cycle boundary
- Engine increments `last_cmd_id` per applied command batch and writes `last_cmd_ts_unix_ms`

---

## 4) Contract policy (instrument identity)
V1a is strict and simple:

- **Single instrument per run**: MNQ *or* MES (not both).
- `contract_key` must be **explicit expiry** (no “front” resolver in V1a):
  - Example: `MNQ.202603` (or equivalent explicit month code form)
- If contract qualification fails:
  - Set `allowed=false` with `NO_CONTRACT`
  - Continue running in observer mode (safe), unless you choose fatal mode later.

Snapshot must expose:
- `instrument.symbol`
- `instrument.contract_key`
- `instrument.con_id` (nullable if unqualified)
- `instrument.tick_size` (required for spread_ticks)

---

## 5) Time semantics (mandatory)
All staleness/age calculations use **monotonic time**.

Store:
- `ts_recv_unix_ms`: wall clock receipt time (for audit only)
- `ts_recv_mono_ns`: monotonic receipt time (for age computations)
- `ts_exch_unix_ms`: optional, only if available from IBKR paths (nullable)

---

## 6) Liveness doctrine (quote vs any-event)
Maintain both:
- `last_any_event_mono_ns`
- `last_quote_event_mono_ns`

Heartbeat logic uses **quote liveness** for market data:
- If no `QuoteEvent` for `FEED_HEARTBEAT_TIMEOUT_MS` ⇒ treat as **stale** (even if connected=true)

Status storms must not mask quote silence.

---

## 7) Spread units and computation
V1a uses **spread in ticks** to keep it instrument-safe.

Definitions:
- `spread_points = ask - bid`
- `spread_ticks = ceil(spread_points / tick_size)` (conservative)

Invalid handling:
- If bid/ask missing, NaN, or `spread_points <= 0` ⇒ `SPREAD_UNAVAILABLE` gate fails.

---

## 8) Hard Gates (V1a)
### Inputs
Read only from the latest SnapshotDTO fields (no recomputation elsewhere).

### Output
- `allowed: bool`
- `reason_codes: list[str]` (stable identifiers)
- `gate_metrics: dict` (stable keys)

### Gate list (V1a)
1. `ARM_OFF` — if `controls.arm == false`
2. `INTENT_FLAT` — if `controls.intent == FLAT`
3. `OUTSIDE_OPERATING_WINDOW` — if not in operating window
4. `SESSION_BREAK` — if in 17:00–18:00 ET break window
5. `FEED_DISCONNECTED` — if `feed.connected == false`
6. `MD_NOT_REALTIME` — if `feed.md_mode != REALTIME`
7. `NO_CONTRACT` — if instrument not qualified (`con_id is null`)
8. `STALE_DATA` — if:
   - quote missing, OR
   - `quote.staleness_ms > STALE_THRESHOLD_MS`, OR
   - `now_mono_ns - last_quote_event_mono_ns > FEED_HEARTBEAT_TIMEOUT_MS`
9. `SPREAD_UNAVAILABLE` — bid/ask invalid/unavailable
10. `SPREAD_WIDE` — if `spread_ticks > MAX_SPREAD_TICKS`
11. `ENGINE_DEGRADED` — if loop stall/overrun threshold exceeded

Reason-code precedence doctrine:
- All failing gates are listed (no “winner”), but ensure consistency:
  - Disconnected implies data will be stale; still include both if both fail.
  - `STALE_DATA` should trigger on quote silence even when connected=true.

---

## 9) Ready vs allowed (V1a rule)
To avoid dual truth in V1a:
- `ready == allowed`
- `ready_reasons == reason_codes`

(V1b may later redefine `ready` to include warmups/features readiness, but that is explicitly **not** in V1a.)

---

## 10) Data Contracts (versioned)

### 10.1 SnapshotDTO (schema: `snapshot.v1`)
Snapshot is published once per engine cycle.

**Identity / run**
- `schema_version: "snapshot.v1"`
- `app_version: str` (e.g., git sha/tag)
- `config_hash: str` (short hash of effective config)
- `run_id: str` (UUID per process start)
- `run_start_ts_unix_ms: int`
- `snapshot_id: int` (monotonic)
- `cycle_count: int` (monotonic, same as snapshot_id or separate, but strictly increasing)
- `ts_unix_ms: int` (publish time)
- `ts_mono_ns: int` (publish time)

**Instrument**
- `instrument.symbol: str`  (MNQ or MES)
- `instrument.contract_key: str` (explicit expiry)
- `instrument.con_id: int | null`
- `instrument.tick_size: float`

**Feed**
- `feed.connected: bool`
- `feed.md_mode: "REALTIME"|"DELAYED"|"FROZEN"|"NONE"`
- `feed.degraded: bool`  (feed-level only)
- `feed.status_reason_codes: list[str]`
- `feed.last_status_change_mono_ns: int | null`

**Events / liveness**
- `last_any_event_mono_ns: int | null`
- `last_quote_event_mono_ns: int | null`
- `quotes_received_count: int` (since run start)

**Quote (nullable)**
- `quote.bid: float | null`
- `quote.ask: float | null`
- `quote.last: float | null`
- `quote.bid_size: int | null`
- `quote.ask_size: int | null`
- `quote.ts_recv_unix_ms: int | null`
- `quote.ts_recv_mono_ns: int | null`
- `quote.ts_exch_unix_ms: int | null`
- `quote.staleness_ms: int | null`
- `quote.spread_ticks: int | null`

**Session**
- `session.in_operating_window: bool`
- `session.is_break_window: bool`
- `session.session_date_iso: str`

**Controls**
- `controls.intent: "LONG"|"SHORT"|"BOTH"|"FLAT"`
- `controls.arm: bool`
- `controls.last_cmd_id: int`
- `controls.last_cmd_ts_unix_ms: int | null`

**Loop health**
- `loop.cycle_ms: int`
- `loop.cycle_overrun: bool`
- `loop.engine_degraded: bool` (engine-level only)
- `loop.last_cycle_start_mono_ns: int`

**Gates output**
- `gates.allowed: bool`
- `gates.reason_codes: list[str]`
- `gates.gate_metrics: dict`

**Ready mapping (V1a)**
- `ready: bool`
- `ready_reasons: list[str]`

---

### 10.2 TriggerCard (schema: `triggercard.v1`)
TriggerCard is logged at a fixed cadence (default 1 Hz) and references the latest Snapshot.

Fields:
- `schema_version: "triggercard.v1"`
- `app_version: str`
- `config_hash: str`
- `run_id: str`
- `seq: int` (monotonic per run)
- `snapshot_id: int`
- `log_ts_unix_ms: int`
- `log_ts_mono_ns: int`

Controls:
- `intent: str`
- `arm: bool`

Gates:
- `allowed: bool`
- `reason_codes: list[str]`

Gate metrics (stable keys):
- `staleness_ms: int | null`
- `spread_ticks: int | null`
- `md_mode: str`
- `connected: bool`
- `in_operating_window: bool`
- `is_break_window: bool`
- `engine_degraded: bool`
- `cycle_ms: int`

Action (reserved; V1a always inert):
- `action_taken: "NONE"`
- `action_id: str | null`

---

## 11) Configuration (V1a defaults)
Minimum required config fields (versioned schema, strict validation):

- `client_id` (unique) — **required**
- `host`, `port` — required (TWS/Gateway)
- `instrument.symbol` — `MNQ` or `MES`
- `instrument.contract_key` — explicit expiry only (V1a)
- `instrument.tick_size` — required (e.g., MNQ=0.25, MES=0.25)

Timing:
- `CYCLE_TARGET_MS = 100`
- `CYCLE_OVERRUN_THRESHOLD_MS = 500`
- `FEED_HEARTBEAT_TIMEOUT_MS = 5000`
- `STALE_THRESHOLD_MS = 2000`

Gates:
- `MAX_SPREAD_TICKS = 8` (example default; instrument-specific tuning later)
- Operating window: `07:00–16:00 ET`
- Break window: `17:00–18:00 ET`

Logging:
- `LOG_CADENCE_HZ = 1`
- `LOG_FLUSH_INTERVAL_RECORDS = 10`
- `LOG_DIR = storage/runs/{run_id}/`
- Filename: `triggercard_{YYYYMMDD}_{run_id}.jsonl`

Reconnect storm control (minimal):
- Backoff: 1s, 2s, 4s… cap 60s
- Max reconnect attempts per minute: 5 (then cooldown)

---

## 12) Startup self-test (recommended V1a)
Before entering the main loop:
- Validate config schema and required fields (fatal if invalid)
- Disk write test to log directory (fatal if fails)
- Log startup metadata (app_version, config_hash, client_id, contract_key)
- Attempt contract qualification:
  - If fails: continue in observer mode with `NO_CONTRACT` gate

---

## 13) Shutdown sequence (V1a)
On shutdown signal:
1. Stop engine loop
2. Flush logger buffers
3. Ask Adapter to unsubscribe (optional) and disconnect cleanly
4. Write final “run_end” marker record (optional)
5. Exit 0

---

## 14) “Done” criteria (V1a, measurable)
1. Runs ≥4 hours in operating window without crash (clean shutdown works).
2. Snapshot publishes atomically; `snapshot_id` monotonic; UI never sees partial state.
3. If `arm=false` ⇒ `allowed=false` with `ARM_OFF`.
4. If `md_mode != REALTIME` ⇒ `allowed=false` with `MD_NOT_REALTIME` within one log interval.
5. If quote missing or stale ⇒ `allowed=false` with `STALE_DATA`.
6. If bid/ask missing/invalid ⇒ `allowed=false` with `SPREAD_UNAVAILABLE`.
7. If spread > threshold ⇒ `allowed=false` with `SPREAD_WIDE`.
8. If outside operating window ⇒ `allowed=false` with `OUTSIDE_OPERATING_WINDOW`.
9. TriggerCard JSONL is append-only and parseable after forced kill (last line may be truncated and detectable).
10. UI commands are applied only at cycle boundary and reflected via `last_cmd_id/ts`.

---

## 15) V1b attachment note (future, non-binding)
V1b can add:
- HistoricalSeeder, T&S aggregator, FeatureRegistry (warmups/confidence)
- Execution State Machine + reconciliation
without breaking V1a contracts, as long as schema versions are bumped on breaking changes.
