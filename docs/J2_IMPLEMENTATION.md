# V1a Milestone J2 - Time + Liveness + Session Windows

## Implementation Summary

**Milestone**: J2 - Time + Liveness + Session Windows
**Status**: ✅ Complete
**Branch**: `agent/cloudcode-v1a` (J2 work committed here)

## Acceptance Criteria (All Met)

- ✅ Clock utility with timezone support (America/Montreal)
- ✅ Session date computation (rolls at 17:00 ET)
- ✅ Operating window detection (configurable, default 07:00-16:00 ET)
- ✅ Break window detection (17:00-18:00 ET)
- ✅ Liveness tracking fields (`last_any_event_mono_ns`, `last_quote_event_mono_ns`)
- ✅ Quote staleness computation using monotonic time
- ✅ Degrade states (feed.degraded, loop.engine_degraded)
- ✅ Nested DTO structure per spec
- ✅ Deterministic clock injection for testing
- ✅ DST-safe timezone handling

## Components Implemented

### 1. Clock & Session Manager ([src/clock.py](../src/clock.py))

**ClockProtocol**:
- Defines interface for real and mock clocks
- Methods: `now_unix_ms()`, `now_mono_ns()`, `now_local()`, `now_utc()`

**SystemClock**:
- Real system clock implementation
- Uses `time.time()` for wall-clock (UTC)
- Uses `time.perf_counter_ns()` for monotonic time
- Uses `datetime.now(ZoneInfo(...))` for timezone-aware time

**SessionManager**:
- Timezone: `America/Montreal` (same as America/Toronto per spec)
- **Session date logic**:
  - Rolls at 17:00 ET (break start)
  - Before 17:00 → session_date = current calendar date
  - At/after 17:00 → session_date = next calendar date
  - Example: Monday 16:59 ET → Monday, Monday 17:00 ET → Tuesday
- **Break window**: 17:00-18:00 ET (1-hour daily break)
- **Operating window**: Configurable (default 07:00-16:00 ET)
- **Session phase**: OPERATING | BREAK | CLOSED
- **DST handling**: Uses zoneinfo for automatic DST transitions

**Clock Injection**:
- `get_default_clock()` / `set_default_clock()` for testing
- `FrozenClock` test implementation for deterministic tests

### 2. Snapshot Schema Updates ([src/snapshot.py](../src/snapshot.py))

**Nested DTO Structure** (per V1a spec):
- `InstrumentDTO`: symbol, contract_key, con_id, tick_size
- `FeedDTO`: connected, md_mode, degraded, status_reason_codes, last_status_change_mono_ns
- `QuoteDTO`: bid/ask/last, sizes, timestamps, staleness_ms, spread_ticks
- `SessionDTO`: in_operating_window, is_break_window, session_date_iso
- `ControlsDTO`: intent, arm, last_cmd_id, last_cmd_ts_unix_ms
- `LoopHealthDTO`: cycle_ms, cycle_overrun, engine_degraded, last_cycle_start_mono_ns
- `GatesDTO`: allowed, reason_codes, gate_metrics

**Liveness Fields** (top-level in SnapshotDTO):
- `last_any_event_mono_ns`: Monotonic timestamp of last event (any type)
- `last_quote_event_mono_ns`: Monotonic timestamp of last QuoteEvent
- `quotes_received_count`: Total quotes received since run start

**Time Fields**:
- `ts_unix_ms`: Wall-clock publish time (UTC)
- `ts_mono_ns`: Monotonic publish time (for age calculations)
- `run_start_ts_unix_ms`: Process start time

**Metadata Fields**:
- `app_version`: Git SHA or version tag
- `config_hash`: Short hash of effective config
- `cycle_count`: Separate from snapshot_id (can diverge in future)

**Immutability**: All DTOs are frozen dataclasses

### 3. Engine Updates ([src/engine.py](../src/engine.py))

Updated to use nested DTO structure:
- Creates `ControlsDTO` for intent/ARM
- Creates `LoopHealthDTO` for cycle timing
- Creates `GatesDTO` for gate outputs
- Adds `ts_mono_ns` and `cycle_count` fields
- Populates `ready` and `ready_reasons` (V1a: ready == allowed)

### 4. UI Updates ([src/ui.py](../src/ui.py))

Updated to read nested fields:
- `snapshot.gates.allowed` (was `snapshot.allowed`)
- `snapshot.gates.reason_codes` (was `snapshot.reason_codes`)
- `snapshot.controls.intent` (was `snapshot.intent`)
- `snapshot.controls.arm` (was `snapshot.arm`)
- `snapshot.loop.cycle_ms` (was `snapshot.cycle_ms`)

### 5. Tests ([tests/test_j2_time_liveness.py](../tests/test_j2_time_liveness.py))

**22 J2 tests** covering:

**Clock & Time**:
- `test_system_clock_basic`: Real clock provides valid time
- `test_frozen_clock_deterministic`: FrozenClock returns fixed time

**Session Date**:
- `test_session_date_before_break`: Before 17:00 → current day
- `test_session_date_at_break_start`: At 17:00 → next day
- `test_session_date_after_break`: After 18:00 → next day (still rolled)
- `test_session_date_late_night`: Late night → next day
- `test_session_manager_dst_transition`: DST transitions handled correctly

**Windows**:
- `test_break_window_detection`: 17:00-18:00 ET detected correctly
- `test_operating_window_default`: Default 07:00-16:00 ET
- `test_operating_window_custom`: Custom window configuration

**Session Phase**:
- `test_session_phase_operating`: OPERATING phase
- `test_session_phase_break`: BREAK phase
- `test_session_phase_closed`: CLOSED phase

**Snapshot Schema**:
- `test_snapshot_dto_liveness_fields`: Liveness tracking fields
- `test_snapshot_dto_session_fields`: Session DTO fields
- `test_snapshot_dto_quote_staleness`: Quote staleness field
- `test_snapshot_dto_feed_degraded`: Feed degraded field
- `test_snapshot_dto_loop_health_fields`: Loop health DTO
- `test_snapshot_dto_nested_structure`: Nested DTO types
- `test_snapshot_dto_immutability`: All DTOs frozen

**Staleness Computation**:
- `test_liveness_age_computation`: Age = now_mono - last_event_mono
- `test_quote_staleness_computation`: Staleness from recv time

**Test Results**: 47/47 tests passing (25 J0+J1 + 22 J2)

## Architecture Compliance

✅ **Monotonic time for staleness**: All age/staleness calculations use `ts_mono_ns` fields
✅ **Session date rolls at 17:00 ET**: Per futures trading semantics
✅ **DST-safe timezone handling**: Uses Python zoneinfo for automatic DST
✅ **Deterministic testing**: FrozenClock allows injecting fixed time
✅ **Nested DTO structure**: Matches V1a spec exactly
✅ **Immutable snapshots**: All DTOs frozen
✅ **No forbidden scope**: Clock/session only, no execution/T&S/historical

## Session Semantics Explained

### 23-Hour Session with 1-Hour Break

**Timeline** (America/Montreal time):
```
Monday 18:00 ET ────────────────────────────────► Tuesday 17:00 ET
                     23-hour session
                   (session_date = Tuesday)

Tuesday 17:00-18:00 ET
   1-hour BREAK

Tuesday 18:00 ET ────────────────────────────────► Wednesday 17:00 ET
                     23-hour session
                   (session_date = Wednesday)
```

### Session Date Examples

| Wall-Clock Time (ET) | session_date | Explanation |
|---------------------|--------------|-------------|
| Monday 16:59        | Monday       | Before break, current day |
| Monday 17:00        | Tuesday      | Break started, next day |
| Monday 17:30        | Tuesday      | In break, next day |
| Monday 18:00        | Tuesday      | Session resumed, next day |
| Tuesday 02:00       | Tuesday      | Late night, same session_date |
| Tuesday 16:59       | Tuesday      | Before break, current day |
| Tuesday 17:00       | Wednesday    | Break started, next day |

### Operating Window vs Break Window

**Operating Window** (configurable):
- Default: 07:00-16:00 ET (9 hours)
- Stops at 16:00 (1 hour before break)
- V1a gates check: `OUTSIDE_OPERATING_WINDOW`

**Break Window** (fixed):
- Always: 17:00-18:00 ET (1 hour)
- V1a gates check: `SESSION_BREAK`

**Closed** (outside both windows):
- Example: 18:00-07:00 ET (overnight)
- V1a gates check: `OUTSIDE_OPERATING_WINDOW`

## Liveness Doctrine

### Two Timestamps Tracked

1. **last_any_event_mono_ns**:
   - Updated by **any** inbound event (StatusEvent, QuoteEvent, etc.)
   - Used to detect adapter aliveness

2. **last_quote_event_mono_ns**:
   - Updated **only** by QuoteEvent
   - Used for market data staleness gates

### Staleness Detection

**Quote staleness**:
```python
staleness_ms = (cycle_mono_ns - quote.ts_recv_mono_ns) // 1_000_000
```

**Feed heartbeat timeout**:
```python
age_ms = (now_mono_ns - last_quote_event_mono_ns) // 1_000_000
if age_ms > FEED_HEARTBEAT_TIMEOUT_MS:
    # STALE_DATA gate fails
```

**Why two timestamps?**
- Status storms (rapid StatusEvents) must not mask quote silence
- `last_any_event_mono_ns` proves adapter is alive
- `last_quote_event_mono_ns` proves market data is fresh

## Degrade States

### feed.degraded

**Feed-level degradation** (connection/md_mode issues):
- `connected == false` → degraded
- `md_mode != REALTIME` → degraded
- Populated by adapter based on connection state

### loop.engine_degraded

**Engine-level degradation** (loop overrun/stall):
- `cycle_ms > CYCLE_TARGET_MS * threshold` → degraded
- Populated by engine based on cycle timing
- Future: may include queue overflow, event starvation

## Integration Points

**Current (J2 scope)**:
- Clock utility ready for use
- SessionManager ready for use
- Snapshot schema complete (all J2 fields)
- Engine/UI updated for nested DTOs

**Future milestones**:
- J3: Engine drains inbound queue, populates liveness fields
- J4: Engine uses SessionManager to populate session DTO
- J4: Engine computes quote staleness_ms from monotonic time
- J5: Hard Gates use session windows (OUTSIDE_OPERATING_WINDOW, SESSION_BREAK)
- J5: Hard Gates use liveness fields (STALE_DATA, FEED_DISCONNECTED)
- J5: Hard Gates use degrade states (MD_NOT_REALTIME, ENGINE_DEGRADED)

## DST Handling

### Automatic DST Transitions

Python `zoneinfo` handles DST automatically:
- **Spring forward**: March 2026 (02:00 → 03:00)
- **Fall back**: November 2026 (02:00 → 01:00)

### Session Date During DST

Session date logic uses **local time hour** (ET):
```python
if now_local.hour >= 17:  # Always 17:00 ET, DST-adjusted
    session_date = tomorrow
```

No special DST handling needed - zoneinfo does it automatically.

### Test Coverage

`test_session_manager_dst_transition` validates:
- Day before DST (March 7, EST)
- Day of DST (March 8, EDT)
- Session date rolls correctly across transition

## Dependencies Added

- `tzdata>=2024.1`: Required for Windows timezone support (Linux/Mac use system tzdata)

## Files Created/Modified

### New Files:
- `src/clock.py`: Clock & SessionManager utility
- `tests/test_j2_time_liveness.py`: 22 J2 tests
- `docs/J2_IMPLEMENTATION.md`: This document

### Modified Files:
- `src/snapshot.py`: Replaced flat schema with nested DTOs, added liveness fields
- `src/engine.py`: Updated to use nested DTO construction
- `src/ui.py`: Updated to read nested DTO fields
- `tests/test_snapshot_atomic.py`: Updated for nested DTO structure
- `pyproject.toml`: Added `tzdata` dependency

### Unchanged:
- `src/ibkr_adapter.py`: No changes (J1 complete, event flow unchanged)
- `src/event_queue.py`: No changes
- `src/events.py`: No changes
- `src/datahub.py`: No changes
- `src/gates.py`: No changes (J5 will implement Hard Gates)
- `src/main.py`: No changes (integration is future work)

## Next Milestone (J3)

**Objective**: Event Processing + Liveness Tracking

Requirements:
- Engine drains inbound queue at cycle start
- Update `last_any_event_mono_ns` and `last_quote_event_mono_ns`
- Populate quote DTO from QuoteEvent
- Populate feed DTO from StatusEvent
- Increment `quotes_received_count`
- Compute quote `staleness_ms` from monotonic time

**Prerequisite**: J2 complete (✅)

## Test Summary

**Total tests**: 47
- J0 (Guardrails): 7 tests
- J1 (Adapter): 8 tests
- J1 (Snapshot atomic): 8 tests
- J1 (Snapshot monotonic): 2 tests
- J2 (Time + Liveness): 22 tests

**Status**: ✅ All passing

**Run J2 tests**:
```powershell
pytest tests/test_j2_time_liveness.py -v
```

**Run all tests**:
```powershell
pytest -q
```

## Manual Validation

**Clock utility**:
```python
from src.clock import SystemClock, SessionManager

clock = SystemClock()
session_mgr = SessionManager(clock=clock)

print(f"Local time: {clock.now_local()}")
print(f"Session date: {session_mgr.session_date_iso()}")
print(f"In operating window: {session_mgr.in_operating_window()}")
print(f"In break: {session_mgr.is_break_window()}")
print(f"Phase: {session_mgr.session_phase()}")
```

**Frozen clock (testing)**:
```python
from src.clock import set_default_clock, now_local
from tests.test_j2_time_liveness import FrozenClock
from datetime import datetime
from zoneinfo import ZoneInfo

# Freeze time at specific moment
frozen_dt = datetime(2026, 3, 16, 17, 30, 0, tzinfo=ZoneInfo("America/Montreal"))
set_default_clock(FrozenClock(frozen_dt))

print(now_local())  # Always returns frozen_dt
```

## Breaking Changes

**Snapshot schema** changed from flat to nested:
- **Before (J1)**: `snapshot.intent`, `snapshot.allowed`, `snapshot.cycle_ms`
- **After (J2)**: `snapshot.controls.intent`, `snapshot.gates.allowed`, `snapshot.loop.cycle_ms`

**Migration**: All code reading SnapshotDTO must use nested fields.

**Compatibility**: J0 and J1 tests updated to use new schema.

## Architecture Invariants Maintained

✅ **Single-writer**: Engine is only writer of SnapshotDTO
✅ **Atomic snapshots**: Nested DTOs constructed once, published atomically
✅ **Immutable events**: All DTOs frozen
✅ **No execution**: Clock/session only, no order placement
✅ **No forbidden scope**: No T&S, no historical seeding, no multi-instrument
✅ **Import-time safety**: No sys.exit() in import path

## Status

**V1a J2**: ✅ Complete
