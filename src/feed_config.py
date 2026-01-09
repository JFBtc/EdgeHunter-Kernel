"""
Feed Configuration - Environment-driven feed selection and IBKR config

Supports:
- FEED_TYPE or EDGEHUNTER_FEED environment variables (MOCK or IBKR)
- IBKR connection configuration from environment
- Explicit contract configuration (no front-month logic)
"""
import os
import logging
from typing import Optional, Literal
from dataclasses import dataclass


logger = logging.getLogger(__name__)

FeedType = Literal["MOCK", "IBKR"]


@dataclass
class IBKRConnectionConfig:
    """IBKR connection parameters from environment."""
    host: str
    port: int
    client_id: int


@dataclass
class IBKRContractConfig:
    """IBKR contract specification from environment."""
    symbol: str
    expiry: str  # YYYYMM format
    exchange: str
    currency: str
    sec_type: str
    multiplier: Optional[int]

    @property
    def contract_key(self) -> str:
        """Return contract_key in SYMBOL.YYYYMM format."""
        return f"{self.symbol}.{self.expiry}"


def get_feed_type() -> FeedType:
    """
    Resolve feed type from environment with explicit precedence.

    Precedence:
    1. FEED_TYPE (if set)
    2. EDGEHUNTER_FEED (backward compatibility)
    3. Default: MOCK

    Returns:
        "MOCK" or "IBKR" (normalized, case-insensitive)
    """
    # Check FEED_TYPE first
    feed_type = os.environ.get("FEED_TYPE", "").strip().upper()

    # Fall back to EDGEHUNTER_FEED if FEED_TYPE not set
    if not feed_type:
        feed_type = os.environ.get("EDGEHUNTER_FEED", "").strip().upper()

    # Default to MOCK
    if not feed_type:
        feed_type = "MOCK"

    # Normalize to MOCK or IBKR
    if feed_type not in ("MOCK", "IBKR"):
        logger.warning(
            f"Invalid feed type '{feed_type}', falling back to MOCK. "
            f"Valid values: MOCK, IBKR"
        )
        feed_type = "MOCK"

    return feed_type  # type: ignore


def get_ibkr_connection_config() -> IBKRConnectionConfig:
    """
    Load IBKR connection configuration from environment.

    Environment variables:
    - IBKR_HOST (default: 127.0.0.1)
    - IBKR_PORT (default: 7497)
    - IBKR_CLIENT_ID (default: 1)

    Returns:
        IBKRConnectionConfig with safe defaults
    """
    host = os.environ.get("IBKR_HOST", "127.0.0.1").strip()

    # Parse port with validation
    port_str = os.environ.get("IBKR_PORT", "7497").strip()
    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError(f"Port must be 1-65535, got {port}")
    except ValueError as e:
        logger.warning(f"Invalid IBKR_PORT '{port_str}': {e}. Using default 7497")
        port = 7497

    # Parse client_id with validation
    client_id_str = os.environ.get("IBKR_CLIENT_ID", "1").strip()
    try:
        client_id = int(client_id_str)
        if client_id < 0:
            raise ValueError(f"client_id must be >= 0, got {client_id}")
    except ValueError as e:
        logger.warning(f"Invalid IBKR_CLIENT_ID '{client_id_str}': {e}. Using default 1")
        client_id = 1

    return IBKRConnectionConfig(host=host, port=port, client_id=client_id)


def get_ibkr_contract_config() -> Optional[IBKRContractConfig]:
    """
    Load IBKR contract configuration from environment.

    Supports explicit field configuration:
    - IBKR_SYMBOL (required)
    - IBKR_EXPIRY (required, YYYYMM format)
    - IBKR_EXCHANGE (default: CME)
    - IBKR_CURRENCY (default: USD)
    - IBKR_SECTYPE (default: FUT)
    - IBKR_MULTIPLIER (optional)

    Returns:
        IBKRContractConfig if all required fields present, else None
    """
    symbol = os.environ.get("IBKR_SYMBOL", "").strip()
    expiry = os.environ.get("IBKR_EXPIRY", "").strip()

    # Required fields
    if not symbol or not expiry:
        logger.error(
            "IBKR contract configuration incomplete. Required: IBKR_SYMBOL, IBKR_EXPIRY. "
            f"Got: IBKR_SYMBOL='{symbol}', IBKR_EXPIRY='{expiry}'"
        )
        return None

    # Validate expiry format (YYYYMM)
    if len(expiry) != 6 or not expiry.isdigit():
        logger.error(
            f"Invalid IBKR_EXPIRY format: '{expiry}'. Expected YYYYMM (e.g., 202603)"
        )
        return None

    # Optional fields with defaults
    exchange = os.environ.get("IBKR_EXCHANGE", "CME").strip()
    currency = os.environ.get("IBKR_CURRENCY", "USD").strip()
    sec_type = os.environ.get("IBKR_SECTYPE", "FUT").strip()

    # Optional multiplier
    multiplier = None
    multiplier_str = os.environ.get("IBKR_MULTIPLIER", "").strip()
    if multiplier_str:
        try:
            multiplier = int(multiplier_str)
        except ValueError:
            logger.warning(f"Invalid IBKR_MULTIPLIER '{multiplier_str}', ignoring")

    return IBKRContractConfig(
        symbol=symbol,
        expiry=expiry,
        exchange=exchange,
        currency=currency,
        sec_type=sec_type,
        multiplier=multiplier,
    )


def log_feed_config(feed_type: FeedType, conn: Optional[IBKRConnectionConfig] = None, contract: Optional[IBKRContractConfig] = None) -> None:
    """
    Log concise startup diagnostics (single line per component).

    Args:
        feed_type: Resolved feed type
        conn: IBKR connection config (if IBKR feed)
        contract: IBKR contract config (if IBKR feed)
    """
    logger.info(f"Feed type: {feed_type}")

    if feed_type == "IBKR":
        if conn:
            logger.info(
                f"IBKR connection: host={conn.host} port={conn.port} client_id={conn.client_id}"
            )
        else:
            logger.warning("IBKR connection config missing")

        if contract:
            logger.info(
                f"IBKR contract: {contract.contract_key} ({contract.symbol} {contract.expiry} "
                f"{contract.exchange} {contract.currency})"
            )
        else:
            logger.error("IBKR contract config missing or invalid")
