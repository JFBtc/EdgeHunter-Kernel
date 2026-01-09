"""
Tests for V1a J7 - TriggerCards JSONL Validator

Validates:
- Valid JSONL files parse correctly
- schema_version validation
- Required fields validation
- Truncated last line tolerance (crash tolerance)
- Error reporting
"""
import json
import tempfile
from pathlib import Path

import pytest

from src.triggercard_validator import validate_triggercard_file, ValidationResult


def test_j7_validator_valid_file():
    """Test validator accepts valid TriggerCards JSONL file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        # Write valid cards
        with open(filepath, "w") as f:
            for i in range(1, 6):
                card = {
                    "schema_version": "triggercard.v1",
                    "run_id": "test-run",
                    "ts_unix_ms": i * 1000,
                    "snapshot_id": i,
                    "ready": True,
                    "ready_reasons": [],
                }
                f.write(json.dumps(card) + "\n")

        result = validate_triggercard_file(filepath)

        assert result.success is True
        assert result.valid_count == 5
        assert result.has_truncated_line is False
        assert len(result.errors) == 0


def test_j7_validator_truncated_last_line_tolerated():
    """Test validator tolerates truncated last line (crash tolerance)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        # Write 3 valid cards
        with open(filepath, "w") as f:
            for i in range(1, 4):
                card = {
                    "schema_version": "triggercard.v1",
                    "run_id": "test-run",
                    "ts_unix_ms": i * 1000,
                    "snapshot_id": i,
                    "ready": True,
                    "ready_reasons": [],
                }
                f.write(json.dumps(card) + "\n")

            # Append truncated line (simulate crash)
            f.write('{"schema_version":"triggercard.v1","run_id":"test')

        result = validate_triggercard_file(filepath)

        assert result.success is True  # Truncated last line is tolerated
        assert result.valid_count == 3  # Only complete lines counted
        assert result.has_truncated_line is True
        assert result.truncated_line_content is not None
        assert len(result.errors) == 0


def test_j7_validator_invalid_schema_version():
    """Test validator rejects invalid schema_version."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        with open(filepath, "w") as f:
            # Valid card
            card1 = {
                "schema_version": "triggercard.v1",
                "run_id": "test-run",
                "ts_unix_ms": 1000,
                "snapshot_id": 1,
                "ready": True,
                "ready_reasons": [],
            }
            f.write(json.dumps(card1) + "\n")

            # Invalid schema version
            card2 = {
                "schema_version": "triggercard.v2",  # Wrong version
                "run_id": "test-run",
                "ts_unix_ms": 2000,
                "snapshot_id": 2,
                "ready": True,
                "ready_reasons": [],
            }
            f.write(json.dumps(card2) + "\n")

        result = validate_triggercard_file(filepath)

        assert result.success is False
        assert result.valid_count == 1  # Only first card valid
        assert len(result.errors) == 1
        assert "Invalid schema_version" in result.errors[0]


def test_j7_validator_missing_schema_version():
    """Test validator rejects card without schema_version."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        with open(filepath, "w") as f:
            card = {
                # Missing schema_version
                "run_id": "test-run",
                "ts_unix_ms": 1000,
                "snapshot_id": 1,
                "ready": True,
                "ready_reasons": [],
            }
            f.write(json.dumps(card) + "\n")

        result = validate_triggercard_file(filepath)

        assert result.success is False
        assert result.valid_count == 0
        assert len(result.errors) == 1
        assert "Missing schema_version" in result.errors[0]


def test_j7_validator_missing_required_fields():
    """Test validator rejects cards missing required fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        with open(filepath, "w") as f:
            card = {
                "schema_version": "triggercard.v1",
                "run_id": "test-run",
                # Missing: ts_unix_ms, snapshot_id, ready, ready_reasons
            }
            f.write(json.dumps(card) + "\n")

        result = validate_triggercard_file(filepath)

        assert result.success is False
        assert result.valid_count == 0
        assert len(result.errors) == 1
        assert "Missing required fields" in result.errors[0]


def test_j7_validator_invalid_json_middle_line():
    """Test validator reports error for invalid JSON in middle of file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        with open(filepath, "w") as f:
            # Valid card
            card1 = {
                "schema_version": "triggercard.v1",
                "run_id": "test-run",
                "ts_unix_ms": 1000,
                "snapshot_id": 1,
                "ready": True,
                "ready_reasons": [],
            }
            f.write(json.dumps(card1) + "\n")

            # Invalid JSON in middle
            f.write("not valid json\n")

            # Valid card
            card2 = {
                "schema_version": "triggercard.v1",
                "run_id": "test-run",
                "ts_unix_ms": 2000,
                "snapshot_id": 2,
                "ready": True,
                "ready_reasons": [],
            }
            f.write(json.dumps(card2) + "\n")

        result = validate_triggercard_file(filepath)

        assert result.success is False
        assert result.valid_count == 2  # First and third lines valid
        assert len(result.errors) == 1
        assert "Line 2" in result.errors[0]
        assert "JSON decode error" in result.errors[0]


def test_j7_validator_empty_file():
    """Test validator handles empty file gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        # Create empty file
        filepath.touch()

        result = validate_triggercard_file(filepath)

        assert result.success is True
        assert result.valid_count == 0
        assert result.has_truncated_line is False
        assert len(result.errors) == 0


def test_j7_validator_file_not_found():
    """Test validator handles missing file gracefully."""
    result = validate_triggercard_file("/nonexistent/path/file.jsonl")

    assert result.success is False
    assert result.valid_count == 0
    assert len(result.errors) == 1
    assert "File not found" in result.errors[0]


def test_j7_validator_empty_lines_ignored():
    """Test validator ignores empty lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        with open(filepath, "w") as f:
            card1 = {
                "schema_version": "triggercard.v1",
                "run_id": "test-run",
                "ts_unix_ms": 1000,
                "snapshot_id": 1,
                "ready": True,
                "ready_reasons": [],
            }
            f.write(json.dumps(card1) + "\n")
            f.write("\n")  # Empty line
            f.write("   \n")  # Whitespace only line

            card2 = {
                "schema_version": "triggercard.v1",
                "run_id": "test-run",
                "ts_unix_ms": 2000,
                "snapshot_id": 2,
                "ready": True,
                "ready_reasons": [],
            }
            f.write(json.dumps(card2) + "\n")

        result = validate_triggercard_file(filepath)

        assert result.success is True
        assert result.valid_count == 2
        assert len(result.errors) == 0


def test_j7_validator_ready_reasons_with_values():
    """Test validator accepts cards with ready_reasons containing values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = Path(tmpdir) / "triggercards.jsonl"

        with open(filepath, "w") as f:
            card = {
                "schema_version": "triggercard.v1",
                "run_id": "test-run",
                "ts_unix_ms": 1000,
                "snapshot_id": 1,
                "ready": False,
                "ready_reasons": ["ARM_OFF", "INTENT_FLAT", "OUTSIDE_OPERATING_WINDOW"],
            }
            f.write(json.dumps(card) + "\n")

        result = validate_triggercard_file(filepath)

        assert result.success is True
        assert result.valid_count == 1
        assert len(result.errors) == 0
