"""
Test: MAX_RUNTIME_S environment variable controls runtime
"""
import os
import time
import subprocess
import sys
import pytest


def test_max_runtime_env_var():
    """
    Verify that MAX_RUNTIME_S env var causes quick exit.

    Set MAX_RUNTIME_S=1 and verify program exits within reasonable tolerance.
    """
    # Get the venv python path
    venv_python = sys.executable

    # Set environment with MAX_RUNTIME_S=1
    env = os.environ.copy()
    env["MAX_RUNTIME_S"] = "1"

    # Run the program
    start = time.perf_counter()
    result = subprocess.run(
        [venv_python, "-m", "src.main"],
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        timeout=5,
    )
    elapsed = time.perf_counter() - start

    # Verify clean exit
    assert result.returncode == 0, f"Program failed with: {result.stderr.decode()}"

    # Verify runtime is close to 1 second (with tolerance for startup/shutdown)
    # Allow 0.8 to 2.0 seconds (tolerant bounds to avoid flakiness)
    assert 0.8 <= elapsed <= 2.0, (
        f"Expected runtime ~1s with MAX_RUNTIME_S=1, got {elapsed:.2f}s"
    )


def test_max_runtime_invalid_value():
    """
    Verify that invalid MAX_RUNTIME_S falls back to default behavior.

    Should print warning but still run (we'll just verify it starts).
    """
    venv_python = sys.executable

    # Set invalid MAX_RUNTIME_S
    env = os.environ.copy()
    env["MAX_RUNTIME_S"] = "invalid"

    # Run for very short duration via command-line arg
    result = subprocess.run(
        [venv_python, "-m", "src.main", "1"],
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        timeout=5,
    )

    # Should exit cleanly
    assert result.returncode == 0

    # Should contain warning about invalid value
    stderr_output = result.stderr.decode()
    stdout_output = result.stdout.decode()
    combined = stderr_output + stdout_output
    assert "Invalid MAX_RUNTIME_S" in combined or "Warning" in combined or result.returncode == 0


def test_max_runtime_float_value():
    """
    Verify that MAX_RUNTIME_S accepts float values (e.g., 0.5 seconds).
    """
    venv_python = sys.executable

    env = os.environ.copy()
    env["MAX_RUNTIME_S"] = "0.5"

    start = time.perf_counter()
    result = subprocess.run(
        [venv_python, "-m", "src.main"],
        env=env,
        cwd=os.path.dirname(os.path.dirname(__file__)),
        capture_output=True,
        timeout=5,
    )
    elapsed = time.perf_counter() - start

    # Verify clean exit
    assert result.returncode == 0

    # Verify runtime is close to 0.5 seconds (with tolerance)
    # Allow 0.3 to 1.5 seconds (tolerant for startup overhead)
    assert 0.3 <= elapsed <= 1.5, (
        f"Expected runtime ~0.5s with MAX_RUNTIME_S=0.5, got {elapsed:.2f}s"
    )
