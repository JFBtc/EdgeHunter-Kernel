# V1a J7 - Soak Test Deliverables & Reporting - COMPLETE

## Overview

V1a J7 adds final soak test deliverables to prove long-run stability of the V1a "Silent Observer" milestone.

## Deliverables

### 1. Metrics Collection in EngineLoop

Added minimal metrics tracking to [src/engine.py](src/engine.py):

- **uptime_s**: Computed from run_start_ts_unix_ms and run_end_ts_unix_ms
- **reconnect_count**: Tracks transitions from feed_connected=False → True
- **staleness_events_count**: Counts cycles where "STALE_DATA" appears in reason_codes
- **max_cycle_time_ms**: Tracks maximum cycle elapsed time across entire run

### 2. Shutdown Summary Report

Implemented `_print_soak_summary()` method in [src/engine.py](src/engine.py):349-389.

Called automatically on `engine.stop()`.

Example output:

```
================================================================================
V1a J7 SOAK TEST SUMMARY REPORT
================================================================================
run_id: b9ee4a9b-1cd3-4742-8889-9bb87fa96f8e
run_start_ts_unix_ms: 1767969232390
run_end_ts_unix_ms: 1767969235404
uptime_s: 3.01
reconnect_count: 0
staleness_events_count: 30
max_cycle_time_ms: 0
logger_enabled: false
================================================================================
SHUTDOWN COMPLETE
================================================================================
```

### 3. TriggerCards JSONL Validator

Created [src/triggercard_validator.py](src/triggercard_validator.py) with:

- `validate_triggercard_file(filepath)`: Validates JSONL file
- `validate_and_report(filepath)`: Prints validation report to stdout
- Tolerates truncated last line (crash tolerance)
- Validates `schema_version == "triggercard.v1"`
- Validates all required fields present

Usage:

```bash
python -m src.triggercard_validator logs/triggercards_2024-01-15_run-123.jsonl
```

**Tests**: [tests/test_j7_triggercard_validator.py](tests/test_j7_triggercard_validator.py) (10 tests)

### 4. Short Soak-like Integration Tests

Created [tests/test_j7_soak_integration.py](tests/test_j7_soak_integration.py) with 9 tests (5-20 second duration):

- `test_j7_mini_soak_no_crash`: Basic 5s stability test
- `test_j7_mini_soak_with_logger`: 2.5s with TriggerCard logger enabled
- `test_j7_mini_soak_metrics_tracking`: Verify metrics collection
- `test_j7_mini_soak_snapshot_invariants_preserved`: J4 invariants under load
- `test_j7_mini_soak_monotonic_snapshot_ids`: Verify no ID corruption
- `test_j7_mini_soak_logger_cadence_decoupled`: Cadence independence
- `test_j7_mini_soak_clean_shutdown`: Shutdown correctness
- `test_j7_mini_soak_no_logger`: Run without logger

### 5. Manual Soak Run Protocol

Created [soak_run.ps1](soak_run.ps1) PowerShell script for 4-hour soak tests:

**Usage:**

```powershell
# 4 hour soak with MOCK feed (default)
.\soak_run.ps1

# 1 hour soak
.\soak_run.ps1 -Duration 3600

# 4 hour soak with real IBKR feed
.\soak_run.ps1 -FeedType IBKR
```

**Features:**
- Environment variable configuration (MAX_RUNTIME_S, FEED_TYPE, ENABLE_TRIGGERCARD_LOGGER)
- Automatic logs directory creation
- Post-run JSONL validation
- Colored status output
- Duration tracking and reporting

**Updated [src/main.py](src/main.py)** to support environment variables:
- `ENABLE_TRIGGERCARD_LOGGER`: Enable/disable logger
- `TRIGGERCARD_LOG_DIR`: Log directory path
- `TRIGGERCARD_CADENCE_HZ`: Logger cadence (Hz)

## Testing

All 137 tests pass:

```bash
pytest -q
```

**Test breakdown:**
- J3 (CommandQueue): 13 tests
- J4 (Snapshot Contract): 9 tests
- J5 (Hard Gates): 22 tests
- J6 (TriggerCard Logger): 13 tests
- J7 (Soak Test): 19 tests (10 validator + 9 integration)
- Other: 61 tests

## Files Modified

### New Files:
- [src/triggercard_validator.py](src/triggercard_validator.py) - JSONL validator
- [tests/test_j7_triggercard_validator.py](tests/test_j7_triggercard_validator.py) - Validator tests
- [tests/test_j7_soak_integration.py](tests/test_j7_soak_integration.py) - Integration tests
- [soak_run.ps1](soak_run.ps1) - Soak run protocol

### Modified Files:
- [src/engine.py](src/engine.py) - Added metrics collection and shutdown summary
- [src/main.py](src/main.py) - Added TriggerCard logger environment variable support

## Metrics Tracked

| Metric | Description | Location |
|--------|-------------|----------|
| `uptime_s` | Total runtime in seconds | Computed from start/end timestamps |
| `reconnect_count` | Feed reconnections (disconnected → connected) | Tracked in `_drain_inbound_events()` |
| `staleness_events_count` | Cycles with STALE_DATA gate failure | Tracked in `_run_cycle_once()` |
| `max_cycle_time_ms` | Maximum cycle elapsed time | Tracked in `_run_cycle_once()` |

## V1a Milestone Status

✅ **J1**: Atomic Snapshot Publication (Copy-on-Write DataHub)
✅ **J2**: Liveness Events (Feed + Quote ingestion)
✅ **J3**: CommandQueue (Intent/ARM with cycle boundary application)
✅ **J4**: SnapshotDTO v1 Contract + Invariants
✅ **J5**: Hard Gates (Multi-reason, conservative spread logic)
✅ **J6**: TriggerCards Logger (JSONL, crash-tolerant, fixed cadence)
✅ **J7**: Soak Test Deliverables (Metrics, reporting, validation)

## Next Steps

**Run a 4-hour soak test:**

```powershell
.\soak_run.ps1 -Duration 14400
```

**Post-soak validation:**

1. Review shutdown summary report in console
2. Validate TriggerCards JSONL:
   ```bash
   python -m src.triggercard_validator logs/triggercards_*.jsonl
   ```
3. Review metrics:
   - Uptime should be ~14400s (4 hours)
   - Check reconnect_count (should be low)
   - Check staleness_events_count (should be reasonable)
   - Check max_cycle_time_ms (should be < overrun_threshold_ms)

**V1a Milestone is COMPLETE!** 🎉

All components delivered:
- Silent Observer (read-only, no orders)
- Atomic snapshot publication at 10 Hz
- Feed ingestion (liveness + quotes)
- Hard gates with multi-reason logic
- Command queue for UI control
- Crash-tolerant TriggerCard logging
- Soak test infrastructure and metrics
