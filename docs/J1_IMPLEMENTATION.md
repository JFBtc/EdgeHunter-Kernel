# V1a Milestone J1 - IBKR Adapter MVP

## Implementation Summary

**Milestone**: J1 - IBKR Adapter MVP (connect/qualify/L1/md_mode)
**Status**: ✅ Complete
**Branch**: `agent/cloudcode-v1a`

## Acceptance Criteria (All Met)

- ✅ Safe connect/disconnect with exponential backoff + storm control
- ✅ Qualify explicit-expiry contract (`contract_key` → `conId`) - single instrument
- ✅ L1 subscription is idempotent (no hot-loop resubscribe)
- ✅ `md_mode` exposed as: REALTIME | DELAYED | FROZEN | NONE
- ✅ IBKR error 326 (clientId collision) fails fast with non-zero exit
- ✅ Events normalized and pushed to inbound queue (adapter never mutates shared state)

## Components Implemented

### 1. Event Schemas ([src/events.py](../src/events.py))
- `MarketDataMode` enum: REALTIME | DELAYED | FROZEN | NONE
- `StatusEvent`: Connection/md_mode changes
- `QuoteEvent`: L1 market data (bid/ask/last + sizes)
- `AdapterErrorEvent`: Optional error surfacing

All events are frozen dataclasses (immutable).

### 2. Inbound Queue ([src/event_queue.py](../src/event_queue.py))
- Thread-safe bounded queue (`maxsize=1000` default)
- Adapter pushes events (non-blocking)
- Engine drains events at cycle start (with optional `max_events` anti-starvation)
- Queue overflow handling (raises `queue.Full` for adapter to log)

### 3. IBKR Adapter ([src/ibkr_adapter.py](../src/ibkr_adapter.py))

**Connection Management:**
- Exponential backoff: 1s → 60s max
- Storm control: max 5 reconnect attempts per 60s window
- `readonly=True` flag (Silent Observer requirement)

**Contract Qualification:**
- Explicit-expiry parsing (e.g., `MNQ.202603`)
- Single instrument per run (V1a constraint)
- Validates format: `SYMBOL.YYYYMM`
- Stores `contract_key` → `conId` mapping

**L1 Subscription:**
- Idempotent subscription manager:
  - `_desired_subscriptions`: target state
  - `_active_subscriptions`: current state
  - Re-apply on reconnect (rate-limited to 1s intervals)
  - Never resubscribes in hot loop

**md_mode Mapping:**
- Tracks IBKR connection state + ticker state
- Maps to canonical enum values per spec
- Emits `StatusEvent` on md_mode changes

**Error Handling:**
- Error 326 (clientId collision): FATAL
  - Logs critical error
  - Emits `StatusEvent` for audit trail
  - Exits with `sys.exit(1)` (fail-fast requirement)
- Other errors: logged and optionally emitted as `AdapterErrorEvent`

**Event Normalization:**
- Callbacks push normalized events to queue only
- Never mutates shared engine/UI state (architecture invariant)
- Handles NaN checks for quote fields
- Monotonic + wall-clock timestamps on all events

**Import-time Safety:**
- Gracefully handles missing `ib_insync` (allows pytest collection)
- Raises `ImportError` at adapter instantiation if dependency missing

### 4. Adapter Runner ([src/adapter_runner.py](../src/adapter_runner.py))
- Minimal plumbing for J1: runs adapter event loop in background thread
- ~100 Hz poll rate for responsive callback handling
- Separate from engine loop (non-blocking architecture)

### 5. Tests ([tests/test_j1_adapter.py](../tests/test_j1_adapter.py))
- Event queue push/drain mechanics
- Bounded queue overflow handling
- md_mode enum mapping
- Explicit-expiry config validation
- Event immutability (frozen dataclasses)
- Quote event schema validation
- Reconnect storm control configuration

**Test Results**: 8/8 J1 tests passing

## Architecture Compliance

✅ **Single-writer invariant**: Adapter pushes events to queue only; engine will drain (J3)
✅ **No order placement**: No execution surface exists (J0 guardrail)
✅ **Single instrument**: Config enforces one `contract_key` per run
✅ **Explicit expiry**: No front-month resolver (V1a constraint)
✅ **Immutable events**: All events are frozen dataclasses
✅ **Import-time safety**: No sys.exit() in import path (pytest collection safe)

## Integration Points

**Current (J1 scope):**
- Adapter → InboundQueue (event flow validated)
- AdapterRunner thread (proves event loop works)

**Future milestones:**
- J2: Engine drains queue, tracks liveness timestamps
- J3: Engine becomes single writer, processes events per cycle
- J4: Events populate SnapshotDTO fields (quote data, md_mode, staleness)
- J5: Hard Gates use event-derived state (STALE_DATA, MD_NOT_REALTIME, etc.)

## Manual Validation

**Demo script**: `examples/j1_adapter_demo.py`

Requirements:
- TWS or IB Gateway running on localhost:7497 (paper trading)
- Valid contract (MNQ March 2026 or adjust `contract_key`)
- Unique `client_id`

Run:
```powershell
python -m examples.j1_adapter_demo
```

Expected output:
- ✓ Connected successfully
- ✓ Contract qualified: MNQ.202603 → conId=XXXXX
- ✓ L1 subscription active
- Stream of `[STATUS]` and `[QUOTE]` events for 30 seconds
- ✓ Clean shutdown

**clientId collision test**: Run demo twice with same `client_id`:
- First instance: runs normally
- Second instance: FATAL error, exits with code 1

## Known Limitations (Out of J1 Scope)

- Engine does not yet drain/process events (J3)
- No liveness tracking (`last_quote_event_mono_ns`) - J2
- No staleness detection - J2
- No gates using feed state - J5
- No TriggerLogger - J6

## Dependencies Added

- `ib_insync>=0.9.86` (IBKR client library)

## Files Created

**New files:**
- `src/events.py` - Event schemas
- `src/event_queue.py` - Inbound queue
- `src/ibkr_adapter.py` - IBKR adapter
- `src/adapter_runner.py` - Adapter thread runner
- `tests/test_j1_adapter.py` - J1 unit tests
- `examples/j1_adapter_demo.py` - Manual validation demo
- `examples/__init__.py` - Examples package marker
- `docs/J1_IMPLEMENTATION.md` - This document

**Modified files:**
- `pyproject.toml` - Added ib_insync dependency

**Unchanged (per J1 scope):**
- `src/engine.py` - No changes (event processing is J3)
- `src/snapshot.py` - No changes (quote fields still placeholders)
- `src/datahub.py` - No changes
- `src/ui.py` - No changes
- `src/main.py` - No changes (integration is future work)

## Next Milestone (J2)

**Objective**: Time + Liveness + Session Windows

Requirements:
- Staleness uses monotonic time only
- Track `last_any_event_mono_ns`, `last_quote_event_mono_ns`
- Operating window + break window (17:00-18:00 ET)
- Session date calculation (rolls at 17:00 ET)

**Prerequisite**: J1 complete (✅)
