"""
Main entrypoint - V1a.1 Slice 1
Minimal runnable skeleton with atomic snapshot publisher and CLI UI
"""
import sys
from src.datahub import DataHub
from src.engine import EngineLoop
from src.ui import MinimalCLI


def main():
    """
    Main entry point for EdgeHunter Core Kernel V1a.1 Slice 1.

    Starts:
    - DataHub (atomic snapshot publisher)
    - EngineLoop (10 Hz snapshot publication)
    - MinimalCLI (read-only display)

    Runs for 30 seconds by default or until Ctrl+C.
    """
    print("Initializing EdgeHunter Core Kernel V1a.1 Slice 1...")

    # Create components
    datahub = DataHub()
    engine = EngineLoop(datahub, cycle_target_ms=100)  # 10 Hz
    ui = MinimalCLI(datahub, display_interval_ms=500)

    try:
        # Start engine loop
        print("Starting engine loop (10 Hz)...")
        engine.start()

        # Give engine a moment to publish first snapshot
        import time
        time.sleep(0.2)

        # Run UI (default 30 seconds for demo, or until Ctrl+C)
        duration = int(sys.argv[1]) if len(sys.argv) > 1 else 30
        print(f"Starting UI (will run for {duration} seconds)...\n")
        ui.run(duration_seconds=duration)

    finally:
        # Clean shutdown
        print("\nStopping engine loop...")
        engine.stop()
        print("Shutdown complete.")


if __name__ == "__main__":
    main()
