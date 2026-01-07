"""
V1a J1 Adapter Demo - Manual validation with live/paper IBKR

This script demonstrates J1 functionality:
- Connect to IBKR with storm control
- Qualify explicit-expiry contract
- Subscribe to L1 market data
- Display events from inbound queue

Prerequisites:
- TWS or IB Gateway running on localhost:7497 (paper trading)
- Unique clientId (not already in use)

To test clientId collision (error 326): Run this script twice with same clientId.
"""
import time
import logging
import sys

from src.ibkr_adapter import IBKRAdapter, IBKRConfig
from src.event_queue import InboundQueue
from src.adapter_runner import AdapterRunner
from src.events import StatusEvent, QuoteEvent


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """
    J1 Adapter demo: connect, qualify, subscribe, display events.

    Usage:
        python -m examples.j1_adapter_demo
    """
    logger.info("=== V1a J1 Adapter Demo ===")

    # Configuration
    config = IBKRConfig(
        client_id=999,  # Change if needed
        host="127.0.0.1",
        port=7497,  # Paper trading port (7496 for live, 4002 for Gateway)
        symbol="MNQ",
        contract_key="MNQ.202603",  # Explicit expiry required
        tick_size=0.25,
    )

    # Create inbound queue
    inbound_queue = InboundQueue(maxsize=1000)

    # Create adapter
    adapter = IBKRAdapter(config, inbound_queue)

    try:
        # Step 1: Connect
        logger.info("Step 1: Connecting to IBKR...")
        connected = adapter.connect()

        if not connected:
            logger.error("Connection failed. Is TWS/Gateway running?")
            return

        logger.info("✓ Connected successfully")

        # Step 2: Qualify contract
        logger.info("Step 2: Qualifying contract...")
        qualified = adapter.qualify_contract()

        if not qualified:
            logger.error("Contract qualification failed")
            return

        logger.info(f"✓ Contract qualified: {config.contract_key} → conId={adapter._con_id}")

        # Step 3: Subscribe to L1
        logger.info("Step 3: Subscribing to L1 market data...")
        subscribed = adapter.subscribe_market_data()

        if not subscribed:
            logger.error("L1 subscription failed")
            return

        logger.info("✓ L1 subscription active")

        # Step 4: Start adapter event loop
        logger.info("Step 4: Starting adapter event loop...")
        runner = AdapterRunner(adapter)
        runner.start()

        logger.info("✓ Adapter running. Monitoring events for 30 seconds...")
        logger.info("")

        # Step 5: Monitor events from inbound queue
        start_time = time.time()
        event_count = 0
        quote_count = 0
        status_count = 0

        while time.time() - start_time < 30.0:
            # Drain events from queue
            events = inbound_queue.drain(max_events=10)

            for event in events:
                event_count += 1

                if isinstance(event, StatusEvent):
                    status_count += 1
                    logger.info(
                        f"[STATUS] connected={event.connected}, "
                        f"md_mode={event.md_mode.value}, reason={event.reason}"
                    )

                elif isinstance(event, QuoteEvent):
                    quote_count += 1
                    logger.info(
                        f"[QUOTE] conId={event.con_id}, "
                        f"bid={event.bid}, ask={event.ask}, last={event.last}, "
                        f"bid_size={event.bid_size}, ask_size={event.ask_size}"
                    )

            time.sleep(0.5)

        # Summary
        logger.info("")
        logger.info("=== Demo Complete ===")
        logger.info(f"Total events: {event_count}")
        logger.info(f"Status events: {status_count}")
        logger.info(f"Quote events: {quote_count}")

        # Stop adapter
        runner.stop()
        adapter.disconnect()

        logger.info("✓ Clean shutdown")

    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        adapter.disconnect()

    except Exception as e:
        logger.error(f"Demo error: {e}", exc_info=True)
        adapter.disconnect()
        sys.exit(1)


if __name__ == "__main__":
    main()
