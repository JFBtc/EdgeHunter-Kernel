"""
Tests for V1a J0 - Scope Guardrails

Validates that V1a non-goals cannot accidentally be violated:
- No execution (order placement/tracking)
- No Time & Sales ingestion
- No historical seeding (reqHistoricalData for features)
- Single instrument per run only

Scans source code for forbidden patterns that would indicate drift
into prohibited areas.
"""
import os
import re
from pathlib import Path
import pytest


# Forbidden patterns for execution
EXECUTION_PATTERNS = [
    # IB order placement APIs
    r'\bplaceOrder\b',
    r'\breqIds\b.*\border\b',
    r'\bcancelOrder\b',
    r'\bmodifyOrder\b',
    # Order object usage (but allow in comments/docs)
    r'^\s*order\s*=\s*Order\(',  # assignment
    r'\bOrder\(.*limitPrice',
    r'\bOrder\(.*orderType',
    # Bracket/OCO semantics
    r'\bbracket.*order\b',
    r'\bOCO\b',
    r'\bparentId\b.*\border\b',
    # Position tracking
    r'\breqPositions\b',
    r'\bposition.*tracking\b',
]

# Forbidden patterns for Time & Sales
TIME_SALES_PATTERNS = [
    r'\breqTickByTickData\b',
    r'\bTickByTickData\b',
    r'\btick.*aggressor\b',
    r'\btime.*sales.*ingestion\b',
    # Note: T&S in comments is allowed (e.g., "no T&S")
]

# Forbidden patterns for historical seeding
HISTORICAL_PATTERNS = [
    # Historical data for feature computation (not just qualification)
    r'\breqHistoricalData\b.*\bATR\b',
    r'\breqHistoricalData\b.*\bVWAP\b',
    r'\breqHistoricalData\b.*\bseeding\b',
    r'\bhistorical.*feature\b',
    r'\bbacktest\b',
    r'\breplay.*engine\b',
]

# Forbidden patterns for multi-instrument
MULTI_INSTRUMENT_PATTERNS = [
    # Config accepting multiple instruments
    r'instruments\s*:\s*list',
    r'symbols\s*:\s*list',
    r'List\[.*instrument',
    # Both MNQ and MES together (in context suggesting multi-instrument subscription)
    # Note: Comments like "MNQ or MES" or "MNQ/MES trade on CME" are allowed
    r'\[.*MNQ.*,.*MES.*\]',  # List with both
    r'subscribe.*MNQ.*MES',
    r'instruments.*=.*MNQ.*MES',
]

# Paths to exclude from scanning (tests, docs, examples can reference forbidden APIs)
EXCLUDE_PATTERNS = [
    r'.*/tests/test_j0_guardrails\.py$',  # This test file
    r'.*/docs/.*\.md$',  # Documentation
    r'.*/examples/.*\.py$',  # Examples (may show what NOT to do)
    r'.*/__pycache__/.*',
    r'.*/\..*',  # Hidden files/dirs
    r'.*/venv/.*',
    r'.*/build/.*',
    r'.*/dist/.*',
]


def should_scan_file(filepath: Path) -> bool:
    """
    Determine if file should be scanned for forbidden patterns.

    Args:
        filepath: Path to check

    Returns:
        True if file should be scanned
    """
    # Only scan Python source files
    if filepath.suffix != '.py':
        return False

    # Check exclusions
    filepath_str = str(filepath.as_posix())
    for pattern in EXCLUDE_PATTERNS:
        if re.search(pattern, filepath_str):
            return False

    return True


def scan_file_for_patterns(filepath: Path, patterns: list[str], category: str) -> list[tuple[int, str, str]]:
    """
    Scan a file for forbidden patterns.

    Args:
        filepath: File to scan
        patterns: List of regex patterns
        category: Category name for error messages

    Returns:
        List of (line_number, line_content, matched_pattern) tuples
    """
    violations = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, start=1):
                # Skip comments (allow discussing forbidden APIs in comments)
                if line.strip().startswith('#'):
                    continue

                # Check each pattern
                for pattern in patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        violations.append((line_num, line.strip(), pattern))

    except Exception as e:
        # Skip files that can't be read
        pass

    return violations


def test_no_execution_surface():
    """
    J0 Guardrail: Verify no execution/order placement surface exists.

    V1a is Silent Observer - no order placement allowed.
    """
    project_root = Path(__file__).parent.parent
    src_dir = project_root / 'src'

    all_violations = []

    # Scan all Python files in src/
    for filepath in src_dir.rglob('*.py'):
        if not should_scan_file(filepath):
            continue

        violations = scan_file_for_patterns(filepath, EXECUTION_PATTERNS, 'EXECUTION')

        for line_num, line_content, pattern in violations:
            all_violations.append(
                f"{filepath.relative_to(project_root)}:{line_num}: "
                f"EXECUTION pattern '{pattern}' matched: {line_content}"
            )

    if all_violations:
        pytest.fail(
            "\n\n❌ J0 GUARDRAIL VIOLATION: Execution surface detected!\n"
            "V1a is Silent Observer - no order placement allowed.\n\n"
            "Violations found:\n" + "\n".join(all_violations)
        )


def test_no_time_sales_surface():
    """
    J0 Guardrail: Verify no Time & Sales ingestion exists.

    V1a does not ingest T&S data - L1 quotes only.
    """
    project_root = Path(__file__).parent.parent
    src_dir = project_root / 'src'

    all_violations = []

    for filepath in src_dir.rglob('*.py'):
        if not should_scan_file(filepath):
            continue

        violations = scan_file_for_patterns(filepath, TIME_SALES_PATTERNS, 'TIME_SALES')

        for line_num, line_content, pattern in violations:
            all_violations.append(
                f"{filepath.relative_to(project_root)}:{line_num}: "
                f"TIME_SALES pattern '{pattern}' matched: {line_content}"
            )

    if all_violations:
        pytest.fail(
            "\n\n❌ J0 GUARDRAIL VIOLATION: Time & Sales surface detected!\n"
            "V1a does not ingest T&S - L1 quotes only.\n\n"
            "Violations found:\n" + "\n".join(all_violations)
        )


def test_no_historical_seeding_surface():
    """
    J0 Guardrail: Verify no historical seeding for features exists.

    V1a does not seed historical data (ATR/VWAP/levels) or backtest/replay.
    """
    project_root = Path(__file__).parent.parent
    src_dir = project_root / 'src'

    all_violations = []

    for filepath in src_dir.rglob('*.py'):
        if not should_scan_file(filepath):
            continue

        violations = scan_file_for_patterns(filepath, HISTORICAL_PATTERNS, 'HISTORICAL')

        for line_num, line_content, pattern in violations:
            all_violations.append(
                f"{filepath.relative_to(project_root)}:{line_num}: "
                f"HISTORICAL pattern '{pattern}' matched: {line_content}"
            )

    if all_violations:
        pytest.fail(
            "\n\n❌ J0 GUARDRAIL VIOLATION: Historical seeding surface detected!\n"
            "V1a does not seed historical data (ATR/VWAP/levels).\n"
            "No backtest/replay allowed.\n\n"
            "Violations found:\n" + "\n".join(all_violations)
        )


def test_single_instrument_only():
    """
    J0 Guardrail: Verify single-instrument-per-run enforcement.

    V1a allows exactly one instrument (MNQ or MES), not both.
    Config must not accept lists of instruments.
    """
    project_root = Path(__file__).parent.parent
    src_dir = project_root / 'src'

    all_violations = []

    for filepath in src_dir.rglob('*.py'):
        if not should_scan_file(filepath):
            continue

        violations = scan_file_for_patterns(filepath, MULTI_INSTRUMENT_PATTERNS, 'MULTI_INSTRUMENT')

        for line_num, line_content, pattern in violations:
            all_violations.append(
                f"{filepath.relative_to(project_root)}:{line_num}: "
                f"MULTI_INSTRUMENT pattern '{pattern}' matched: {line_content}"
            )

    if all_violations:
        pytest.fail(
            "\n\n❌ J0 GUARDRAIL VIOLATION: Multi-instrument surface detected!\n"
            "V1a allows exactly ONE instrument per run (MNQ or MES, not both).\n\n"
            "Violations found:\n" + "\n".join(all_violations)
        )


def test_ibkr_config_single_instrument_schema():
    """
    J0 Runtime: Verify IBKRConfig enforces single instrument at schema level.
    """
    from src.ibkr_adapter import IBKRConfig

    # Config schema should have singular fields, not plural/lists
    config = IBKRConfig(
        client_id=100,
        symbol="MNQ",  # Singular
        contract_key="MNQ.202603",  # Single explicit expiry
        tick_size=0.25,
    )

    # Verify fields are singular (not lists)
    assert isinstance(config.symbol, str), "symbol must be string (singular)"
    assert isinstance(config.contract_key, str), "contract_key must be string (singular)"

    # Config should not have plural fields
    assert not hasattr(config, 'symbols'), "Config must not have 'symbols' (plural)"
    assert not hasattr(config, 'instruments'), "Config must not have 'instruments' (plural)"
    assert not hasattr(config, 'contract_keys'), "Config must not have 'contract_keys' (plural)"


def test_ibkr_config_rejects_multi_instrument_list():
    """
    J0 Runtime: Verify IBKRConfig rejects list of instruments at construction.
    """
    from src.ibkr_adapter import IBKRConfig

    # Attempting to pass list should raise ValueError
    with pytest.raises(ValueError, match="V1a J0 Guardrail.*Multi-instrument not allowed"):
        IBKRConfig(
            client_id=100,
            symbol=["MNQ", "MES"],  # List not allowed
            contract_key="MNQ.202603",
            tick_size=0.25,
        )

    # Contract key as list should also fail
    with pytest.raises(ValueError, match="V1a J0 Guardrail.*Multi-instrument not allowed"):
        IBKRConfig(
            client_id=100,
            symbol="MNQ",
            contract_key=["MNQ.202603", "MES.202603"],  # List not allowed
            tick_size=0.25,
        )


def test_ibkr_config_requires_explicit_expiry():
    """
    J0 Runtime: Verify IBKRConfig rejects front-month / missing expiry.
    """
    from src.ibkr_adapter import IBKRConfig

    # Missing expiry (no dot) should raise ValueError
    with pytest.raises(ValueError, match="V1a requires explicit expiry"):
        IBKRConfig(
            client_id=100,
            symbol="MNQ",
            contract_key="MNQ",  # Missing explicit expiry
            tick_size=0.25,
        )
