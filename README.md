# EdgeHunter-Kernel

Core Kernel V1a (Silent Observer): stable live loop + atomic Snapshot + Hard Gates + TriggerCards (append-only).
No execution, no strategy, no Time&Sales, no history, single-instrument per run.

---

## V1a.1 Slice 1 - Minimal Runnable Skeleton

This slice implements the foundational architecture:
- **SnapshotDTO**: Versioned schema (`snapshot.v1`) with atomic copy-on-write publication
- **Engine Loop**: Single-writer kernel running at 10 Hz with monotonic snapshot IDs
- **DataHub**: Thread-safe atomic snapshot publisher
- **Minimal CLI**: Read-only UI displaying snapshot status

**Current scope**: No feed, no gates logic, no TriggerLogger, no commands yet. Just the skeleton.

---

## Quick Start (Windows)

### 1. Create virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -e ".[dev]"
```

### 3. Run tests

```powershell
pytest -q
```

Expected output: All tests pass (6+ tests for monotonic IDs and atomic reads).

### 4. Run the program

```powershell
# Run for 30 seconds (default)
python -m src.main

# Run for custom duration (e.g., 60 seconds)
python -m src.main 60
```

Expected output:
- Snapshot status line updating every 500ms
- `snapshot_id` increasing monotonically (1, 2, 3, ...)
- `allowed=False` (no gates yet)
- `cycle_ms` showing loop timing
- Runs stable for 30-60 seconds without crash

---

## Architecture Invariants (V1a)

1. **Single-writer**: Engine loop is the only component that publishes snapshots
2. **Atomic publication**: Snapshots are immutable (frozen dataclass) and published atomically via copy-on-write
3. **Read-only UI**: UI reads snapshots only, never mutates state
4. **Monotonic IDs**: `snapshot_id` is strictly increasing per run

---

## Project Structure

```
EH_cloudcode/
├── src/
│   ├── __init__.py
│   ├── snapshot.py      # SnapshotDTO schema (snapshot.v1)
│   ├── datahub.py       # Atomic snapshot publisher
│   ├── engine.py        # Engine loop (10 Hz)
│   ├── ui.py            # Minimal CLI display
│   └── main.py          # Entrypoint
├── tests/
│   ├── __init__.py
│   ├── test_snapshot_monotonic.py  # Tests for monotonic IDs
│   └── test_snapshot_atomic.py     # Tests for atomic reads
├── docs/                # Specifications
├── pyproject.toml       # Project metadata
└── README.md            # This file
```

---

## Testing

All tests verify V1a.1 Slice 1 acceptance criteria:

```powershell
# Run all tests
pytest -q

# Run specific test file
pytest tests/test_snapshot_monotonic.py -v

# Run with verbose output
pytest -v
```

**Tests included**:
- `test_snapshot_id_monotonic_increasing`: Verifies snapshot_id increases monotonically
- `test_snapshot_id_starts_at_one`: First snapshot has ID 1
- `test_snapshot_id_continuous_sequence`: IDs form continuous sequence (1,2,3,...)
- `test_snapshot_atomic_complete_object`: Readers always see complete snapshots
- `test_snapshot_immutability`: Snapshots cannot be mutated
- `test_snapshot_concurrent_reads`: Concurrent readers see consistent state
- `test_snapshot_no_partial_updates`: No partial field updates observed

---

## Next Steps (Future Slices)

V1a.1 Slice 1 is complete when:
- [x] pytest passes
- [x] Program runs stable for 30-60 seconds
- [x] Atomic snapshot publication verified
- [x] Monotonic snapshot IDs verified

**Future work** (not in Slice 1):
- Feed integration (MOCK/IBKR)
- Hard Gates evaluation
- TriggerLogger (append-only JSONL)
- Command queue (Intent/ARM)
- Session/clock manager

---

## Troubleshooting

**Tests fail with import errors**:
```powershell
pip install -e ".[dev]"
```

**Python version error**:
Requires Python 3.10+. Check version:
```powershell
python --version
```

**Program doesn't start**:
Make sure virtual environment is activated:
```powershell
.\venv\Scripts\Activate.ps1
```
