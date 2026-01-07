# V1a J0 - Scope Guardrails

## Overview

**V1a is a Silent Observer**: The system must **never** place orders, ingest Time & Sales, seed historical data, or run multiple instruments simultaneously. These constraints are enforced mechanically through automated tests and runtime validation.

## What Is Forbidden (V1a Non-Goals)

### 1. ❌ Execution / Order Placement
- No `placeOrder`, `cancelOrder`, `modifyOrder` calls
- No `Order` object construction for placement
- No bracket/OCO/parent-child order semantics
- No position tracking (`reqPositions`)

**Why**: V1a is a Silent Observer. It observes market conditions and evaluates "Would Trade" signals only. No actual trading occurs.

### 2. ❌ Time & Sales Ingestion
- No `reqTickByTickData` calls
- No `TickByTick` event processing
- No aggressor classification
- No tick-level trade analysis

**Why**: V1a operates on L1 quotes (bid/ask/last) only. T&S adds complexity without providing value for the Silent Observer milestone.

### 3. ❌ Historical Seeding
- No `reqHistoricalData` for computing features (ATR, VWAP, levels)
- No backtest/replay engines
- No historical data seeding for warmups

**Why**: V1a focuses on live data processing only. Historical seeding and backtesting are deferred to later milestones.

### 4. ❌ Multi-Instrument Per Run
- No lists of instruments in configuration
- No simultaneous MNQ + MES subscriptions
- Single instrument only: MNQ **OR** MES (not both)

**Why**: V1a simplifies logic by processing exactly one instrument per run. Multi-instrument coordination is out of scope.

### 5. ❌ Front-Month Resolver
- No automatic roll logic
- Explicit expiry required (e.g., `MNQ.202603`)
- Contract key must be `SYMBOL.YYYYMM` format

**Why**: V1a avoids roll complexity. Users must specify exact contract expiry.

## How Guardrails Are Enforced

### Automated Static Analysis ([tests/test_j0_guardrails.py](../tests/test_j0_guardrails.py))

**Forbidden Surface Scanner**: Scans all Python source files in `src/` for forbidden patterns:

```python
# Execution patterns
placeOrder, cancelOrder, Order(...), bracket, OCO, reqPositions

# Time & Sales patterns
reqTickByTickData, TickByTick, aggressor

# Historical seeding patterns
reqHistoricalData.*ATR, reqHistoricalData.*VWAP, backtest, replay

# Multi-instrument patterns
instruments: list, symbols: list, MNQ.*MES
```

**Exclusions**: Tests, docs, and examples are excluded from scanning (they may reference forbidden APIs for educational purposes).

**Test Behavior**:
- ✅ Pass: No forbidden patterns found in `src/`
- ❌ Fail: Forbidden pattern detected → clear error message with file path + line number

### Runtime Validation ([src/ibkr_adapter.py](../src/ibkr_adapter.py))

**IBKRConfig Validation**: `__post_init__` enforces:

1. **Single Instrument**: Rejects `list` or `tuple` for `symbol` or `contract_key`
   ```python
   # ❌ FAILS
   IBKRConfig(symbol=["MNQ", "MES"], ...)

   # ✅ PASSES
   IBKRConfig(symbol="MNQ", ...)
   ```

2. **Explicit Expiry**: Rejects `contract_key` without dot (e.g., `"MNQ"`)
   ```python
   # ❌ FAILS
   IBKRConfig(contract_key="MNQ", ...)

   # ✅ PASSES
   IBKRConfig(contract_key="MNQ.202603", ...)
   ```

**Error Messages**: Clear, actionable errors referencing "V1a J0 Guardrail"

## Running Guardrail Tests

```powershell
# Run all tests (includes guardrails)
pytest -q

# Run only guardrail tests
pytest tests/test_j0_guardrails.py -v

# Test specific guardrail
pytest tests/test_j0_guardrails.py::test_no_execution_surface -v
```

**Expected Output** (clean repo):
```
tests/test_j0_guardrails.py::test_no_execution_surface PASSED
tests/test_j0_guardrails.py::test_no_time_sales_surface PASSED
tests/test_j0_guardrails.py::test_no_historical_seeding_surface PASSED
tests/test_j0_guardrails.py::test_single_instrument_only PASSED
tests/test_j0_guardrails.py::test_ibkr_config_single_instrument_schema PASSED
tests/test_j0_guardrails.py::test_ibkr_config_rejects_multi_instrument_list PASSED
tests/test_j0_guardrails.py::test_ibkr_config_requires_explicit_expiry PASSED
```

## Extending Guardrails for V1b

When moving to V1b (which **will** add execution), follow these steps:

### 1. Update Forbidden Patterns
Edit `tests/test_j0_guardrails.py`:
- **Remove** patterns that are now allowed (e.g., `placeOrder` for V1b execution)
- **Keep** patterns that remain forbidden (e.g., multi-instrument if still out of scope)
- **Add** new patterns for V1b-specific violations

### 2. Add Version Guards
Use conditional logic or separate test files:
```python
# Example: Skip execution check for V1b+
@pytest.mark.skipif(VERSION >= "1b", reason="V1b allows execution")
def test_no_execution_surface():
    ...
```

### 3. Update Runtime Validation
Modify `IBKRConfig.__post_init__()` to relax constraints:
```python
def __post_init__(self):
    if self.version == "v1a":
        # V1a: Single instrument only
        if isinstance(self.symbol, (list, tuple)):
            raise ValueError("V1a: single instrument only")
    elif self.version == "v1b":
        # V1b: Allow multi-instrument
        pass
```

### 4. Document Breaking Changes
Update this file (`J0_GUARDRAILS.md`) with:
- What was forbidden in V1a
- What is now allowed in V1b
- New guardrails specific to V1b

## False Positive Mitigation

**Problem**: English words like "order" can cause false positives.

**Solution**: Use anchored patterns targeting API identifiers:
```python
# ❌ TOO BROAD (matches "in order to...")
r'order'

# ✅ ANCHORED (matches API calls only)
r'\bplaceOrder\b'
r'^\s*order\s*=\s*Order\('
```

**Exclusions**: Tests, docs, examples explicitly excluded via `EXCLUDE_PATTERNS`.

## CI Integration

Add to CI pipeline:
```yaml
- name: Run Guardrail Tests
  run: pytest tests/test_j0_guardrails.py -v
```

Guardrail failures should **block merges** to enforce V1a constraints.

## Summary

**Guardrails enforce**:
- ✅ No execution (V1a is Silent Observer)
- ✅ No T&S ingestion (L1 only)
- ✅ No historical seeding (live data only)
- ✅ Single instrument per run (MNQ or MES, not both)
- ✅ Explicit expiry (no front-month resolver)

**Enforcement mechanisms**:
- Static analysis (pytest scans source code)
- Runtime validation (config rejects invalid schemas)
- Clear error messages (actionable feedback)

**Tests**: 7 guardrail tests in `tests/test_j0_guardrails.py`

**Status**: ✅ V1a J0 Complete
