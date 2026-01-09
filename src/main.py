"""
Main entrypoint - V1a.1 Slice 1
Minimal runnable skeleton with atomic snapshot publisher and CLI UI
"""
import os
import sys
import time
import logging
from pathlib import Path
from typing import Optional
from src.command_queue import CommandQueue
from src.datahub import DataHub
from src.engine import EngineLoop
from src.event_queue import InboundQueue
from src.triggercard_logger import TriggerCardLogger
from src.ui import MinimalCLI
from src.feed_config import (
    get_feed_type,
    get_ibkr_connection_config,
    get_ibkr_contract_config,
    log_feed_config,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


def _create_mock_adapter_runner(inbound_queue):
    """
    Create and initialize MOCK adapter runner.

    Args:
        inbound_queue: InboundQueue for events

    Returns:
        AdapterRunner instance (not started)
    """
    try:
        from src.mock_adapter import MockL1Adapter
        from src.adapter_runner import AdapterRunner
    except ImportError as e:
        logger.error(f"Failed to import MOCK adapter: {e}")
        return None

    try:
        # Create mock adapter with deterministic settings
        adapter = MockL1Adapter(
            inbound_queue=inbound_queue,
            base_price=18500.0,  # MNQ-like base price
            tick_size=0.25,
            spread_ticks=1,
            quote_rate_hz=10.0,  # 10 Hz quote rate
        )

        # Connect (always succeeds for mock)
        logger.info("Connecting to MOCK feed...")
        if not adapter.connect():
            logger.error("MOCK adapter connection failed")
            return None

        logger.info("MOCK adapter initialized successfully")

        # Wrap in runner
        runner = AdapterRunner(adapter)
        return runner

    except Exception as e:
        logger.error(f"Failed to create MOCK adapter: {e}", exc_info=True)
        return None


def _create_ibkr_adapter_runner(conn, contract, inbound_queue):
    """
    Create and initialize IBKR adapter runner.

    Args:
        conn: IBKRConnectionConfig
        contract: IBKRContractConfig
        inbound_queue: InboundQueue for events

    Returns:
        AdapterRunner instance (not started)
    """
    try:
        from src.ibkr_adapter import IBKRAdapter, IBKRConfig
        from src.adapter_runner import AdapterRunner
    except ImportError as e:
        logger.error(f"Failed to import IBKR adapter: {e}")
        logger.error("Install ib_insync: pip install ib_insync")
        return None

    # Build IBKRConfig from environment-driven config
    ibkr_config = IBKRConfig(
        client_id=conn.client_id,
        host=conn.host,
        port=conn.port,
        symbol=contract.symbol,
        contract_key=contract.contract_key,
        tick_size=0.25,  # Default for MNQ/MES (should be configurable in future)
    )

    try:
        # Create adapter
        adapter = IBKRAdapter(ibkr_config, inbound_queue)

        # Connect and qualify contract
        logger.info("Connecting to IBKR...")
        if not adapter.connect():
            logger.error("IBKR connection failed")
            return None

        logger.info("Qualifying contract...")
        if not adapter.qualify_contract():
            logger.error(f"Contract qualification failed: {contract.contract_key}")
            adapter.disconnect()
            return None

        logger.info("Subscribing to market data...")
        if not adapter.subscribe_market_data():
            logger.error("Market data subscription failed")
            adapter.disconnect()
            return None

        logger.info("IBKR adapter initialized successfully")

        # Wrap in runner
        runner = AdapterRunner(adapter)
        return runner

    except Exception as e:
        logger.error(f"Failed to create IBKR adapter: {e}", exc_info=True)
        return None


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

    # Resolve feed type and configuration
    feed_type = get_feed_type()
    ibkr_conn = None
    ibkr_contract = None

    if feed_type == "IBKR":
        ibkr_conn = get_ibkr_connection_config()
        ibkr_contract = get_ibkr_contract_config()

        # Validate IBKR configuration
        if not ibkr_contract:
            logger.error(
                "IBKR feed selected but contract configuration incomplete. "
                "System will run in degraded mode (feed disconnected). "
                "Set IBKR_SYMBOL and IBKR_EXPIRY to enable live feed."
            )

    # Log resolved feed configuration
    log_feed_config(feed_type, ibkr_conn, ibkr_contract)

    # Configure TriggerCard logger (J6/J7)
    triggercard_logger = None
    if os.environ.get("ENABLE_TRIGGERCARD_LOGGER", "").lower() in ("true", "1", "yes"):
        log_dir = os.environ.get("TRIGGERCARD_LOG_DIR", "logs")
        cadence_hz = float(os.environ.get("TRIGGERCARD_CADENCE_HZ", "1.0"))

        # Create log directory if it doesn't exist
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        logger.info(f"Enabling TriggerCard logger: {log_dir}, {cadence_hz} Hz")
        triggercard_logger = TriggerCardLogger(
            run_id=f"run-{int(time.time())}",  # Simple run_id for now
            log_dir=log_dir,
            cadence_hz=cadence_hz,
        )

    # Create inbound queue for feed events
    inbound_queue = InboundQueue(maxsize=1000)

    # Create components
    datahub = DataHub()
    command_queue = CommandQueue(maxsize=100)

    # Initialize adapter runner based on feed type
    adapter_runner = None
    if feed_type == "MOCK":
        logger.info("Starting adapter: MOCK")
        adapter_runner = _create_mock_adapter_runner(inbound_queue)
    elif feed_type == "IBKR" and ibkr_contract and ibkr_conn:
        logger.info("Starting adapter: IBKR")
        adapter_runner = _create_ibkr_adapter_runner(
            ibkr_conn, ibkr_contract, inbound_queue
        )

    # Create engine with inbound queue
    engine = EngineLoop(
        datahub,
        cycle_target_ms=100,
        command_queue=command_queue,
        triggercard_logger=triggercard_logger,
        inbound_queue=inbound_queue,
    )  # 10 Hz
    ui = MinimalCLI(datahub, display_interval_ms=500, command_queue=command_queue)

    try:
        # Start adapter runner (if MOCK or IBKR)
        if adapter_runner:
            logger.info(f"Starting {feed_type} adapter runner...")
            adapter_runner.start()

            # Give adapter time to initialize
            if feed_type == "IBKR":
                logger.info("Waiting for IBKR adapter to connect and qualify contract...")
                time.sleep(2.0)
            else:
                # MOCK adapter starts immediately
                time.sleep(0.2)

        # Start engine loop
        logger.info("Starting engine loop (10 Hz)...")
        engine.start()

        # Give engine a moment to publish first snapshot
        time.sleep(0.2)

        # Run UI with runtime limit
        logger.info(f"Starting UI (will run for {duration} seconds)...\n")
        ui.run(duration_seconds=duration)

    finally:
        # Clean shutdown
        logger.info("\nStopping engine loop...")
        engine.stop()

        # Stop adapter runner
        if adapter_runner:
            logger.info(f"Stopping {feed_type} adapter runner...")
            adapter_runner.stop()

        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
