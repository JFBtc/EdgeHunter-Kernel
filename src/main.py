"""
Main entrypoint - V1a.1 Slice 1
Minimal runnable skeleton with atomic snapshot publisher and CLI UI
"""
import os
import sys
import time
from pathlib import Path
from src.command_queue import CommandQueue
from src.datahub import DataHub
from src.engine import EngineLoop
from src.triggercard_logger import TriggerCardLogger
from src.ui import MinimalCLI


def main():
    """
    Main entry point for EdgeHunter Core Kernel V1a.1 Slice 1.

    Starts:
    - DataHub (atomic snapshot publisher)
    - EngineLoop (10 Hz snapshot publication)
    - MinimalCLI (read-only display)

    Runtime control:
    - MAX_RUNTIME_S env var: overall runtime limit (monotonic time)
    - Command-line arg: duration (if MAX_RUNTIME_S not set)
    - Default: 30 seconds
    - Ctrl+C: immediate shutdown
    """
    print("Initializing EdgeHunter Core Kernel V1a.1 Slice 1...")

    # Determine runtime limit (prefer MAX_RUNTIME_S, then argv, then default)
    duration = None
    max_runtime_s = os.environ.get("MAX_RUNTIME_S")
    if max_runtime_s:
        try:
            duration = float(max_runtime_s)
        except ValueError:
            print(f"Warning: Invalid MAX_RUNTIME_S='{max_runtime_s}', using default")

    if duration is None:
        duration = int(sys.argv[1]) if len(sys.argv) > 1 else 30

    # Configure TriggerCard logger (J6/J7)
    triggercard_logger = None
    if os.environ.get("ENABLE_TRIGGERCARD_LOGGER", "").lower() in ("true", "1", "yes"):
        log_dir = os.environ.get("TRIGGERCARD_LOG_DIR", "logs")
        cadence_hz = float(os.environ.get("TRIGGERCARD_CADENCE_HZ", "1.0"))

        # Create log directory if it doesn't exist
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        print(f"Enabling TriggerCard logger: {log_dir}, {cadence_hz} Hz")
        triggercard_logger = TriggerCardLogger(
            run_id=f"run-{int(time.time())}",  # Simple run_id for now
            log_dir=log_dir,
            cadence_hz=cadence_hz,
        )

    # Create components
    datahub = DataHub()
    command_queue = CommandQueue(maxsize=100)
    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        command_queue=command_queue,
        triggercard_logger=triggercard_logger,
    )  # 10 Hz
    ui = MinimalCLI(datahub, display_interval_ms=500, command_queue=command_queue)

    try:
        # Start engine loop
        print("Starting engine loop (10 Hz)...")
        engine.start()

        # Give engine a moment to publish first snapshot
        time.sleep(0.2)

        # Run UI with runtime limit
        print(f"Starting UI (will run for {duration} seconds)...\n")
        ui.run(duration_seconds=duration)

    finally:
        # Clean shutdown
        print("\nStopping engine loop...")
        engine.stop()
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
