"""
TriggerCards JSONL Validator

Validates TriggerCards JSONL files for V1a J7 soak test.

Validates:
- Each complete line is valid JSON
- schema_version == "triggercard.v1"
- Tolerates truncated last line (crash tolerance)

Usage:
    from src.triggercard_validator import validate_triggercard_file

    result = validate_triggercard_file("logs/triggercards_2024-01-15_run-123.jsonl")
    print(f"Valid cards: {result.valid_count}")
    print(f"Truncated: {result.has_truncated_line}")
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ValidationResult:
    """Result of TriggerCards JSONL validation."""
    valid_count: int
    has_truncated_line: bool
    truncated_line_content: Optional[str]
    errors: list[str]
    success: bool


def validate_triggercard_file(filepath: str | Path) -> ValidationResult:
    """
    Validate a TriggerCards JSONL file.

    Validates each line as valid JSON with schema_version == "triggercard.v1".
    Tolerates a truncated last line (common after crash).

    Args:
        filepath: Path to JSONL file

    Returns:
        ValidationResult with counts and error details
    """
    filepath = Path(filepath)

    if not filepath.exists():
        return ValidationResult(
            valid_count=0,
            has_truncated_line=False,
            truncated_line_content=None,
            errors=[f"File not found: {filepath}"],
            success=False,
        )

    valid_count = 0
    has_truncated_line = False
    truncated_line_content = None
    errors = []

    with open(filepath, "r") as f:
        lines = f.readlines()

    for i, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue

        try:
            card = json.loads(line)

            # Validate schema_version
            if "schema_version" not in card:
                errors.append(f"Line {i}: Missing schema_version")
                continue

            if card["schema_version"] != "triggercard.v1":
                errors.append(
                    f"Line {i}: Invalid schema_version '{card['schema_version']}' (expected 'triggercard.v1')"
                )
                continue

            # Validate required fields
            required_fields = ["run_id", "ts_unix_ms", "snapshot_id", "ready", "ready_reasons"]
            missing_fields = [field for field in required_fields if field not in card]

            if missing_fields:
                errors.append(f"Line {i}: Missing required fields: {missing_fields}")
                continue

            valid_count += 1

        except json.JSONDecodeError as e:
            # Last line truncated is expected after crash
            if i == len(lines):
                has_truncated_line = True
                truncated_line_content = line
                # Don't count as error - this is expected
            else:
                errors.append(f"Line {i}: JSON decode error: {e}")

    success = len(errors) == 0

    return ValidationResult(
        valid_count=valid_count,
        has_truncated_line=has_truncated_line,
        truncated_line_content=truncated_line_content,
        errors=errors,
        success=success,
    )


def validate_and_report(filepath: str | Path) -> None:
    """
    Validate and print a report to stdout.

    Args:
        filepath: Path to JSONL file
    """
    result = validate_triggercard_file(filepath)

    print("\n" + "=" * 80)
    print("TRIGGERCARD JSONL VALIDATION REPORT")
    print("=" * 80)
    print(f"File: {filepath}")
    print(f"Valid cards: {result.valid_count}")
    print(f"Truncated last line: {'Yes' if result.has_truncated_line else 'No'}")

    if result.has_truncated_line and result.truncated_line_content:
        print(f"Truncated content preview: {result.truncated_line_content[:80]}...")

    if result.errors:
        print(f"\nErrors: {len(result.errors)}")
        for error in result.errors:
            print(f"  - {error}")

    print(f"\nValidation: {'PASSED' if result.success else 'FAILED'}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.triggercard_validator <filepath>")
        sys.exit(1)

    validate_and_report(sys.argv[1])
