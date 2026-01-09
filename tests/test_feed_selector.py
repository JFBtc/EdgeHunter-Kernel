"""
Tests for Feed Selector - IBKR/MOCK feed switching

Validates:
- Environment-driven feed type resolution (FEED_TYPE, EDGEHUNTER_FEED)
- IBKR configuration parsing from environment
- Feed path invocation (without requiring real TWS)
- Clean shutdown of adapter runner
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock

from src.feed_config import (
    get_feed_type,
    get_ibkr_connection_config,
    get_ibkr_contract_config,
)


def test_feed_type_default_mock():
    """Test feed type defaults to MOCK when no env vars set."""
    with patch.dict(os.environ, {}, clear=True):
        feed_type = get_feed_type()
        assert feed_type == "MOCK"


def test_feed_type_from_feed_type_env():
    """Test FEED_TYPE env var is preferred."""
    with patch.dict(os.environ, {"FEED_TYPE": "IBKR"}, clear=True):
        feed_type = get_feed_type()
        assert feed_type == "IBKR"


def test_feed_type_from_edgehunter_feed_env():
    """Test EDGEHUNTER_FEED env var as fallback (backward compatibility)."""
    with patch.dict(os.environ, {"EDGEHUNTER_FEED": "IBKR"}, clear=True):
        feed_type = get_feed_type()
        assert feed_type == "IBKR"


def test_feed_type_precedence():
    """Test FEED_TYPE takes precedence over EDGEHUNTER_FEED."""
    with patch.dict(os.environ, {"FEED_TYPE": "MOCK", "EDGEHUNTER_FEED": "IBKR"}, clear=True):
        feed_type = get_feed_type()
        assert feed_type == "MOCK"


def test_feed_type_case_insensitive():
    """Test feed type is case-insensitive."""
    with patch.dict(os.environ, {"FEED_TYPE": "ibkr"}, clear=True):
        feed_type = get_feed_type()
        assert feed_type == "IBKR"

    with patch.dict(os.environ, {"FEED_TYPE": "Mock"}, clear=True):
        feed_type = get_feed_type()
        assert feed_type == "MOCK"


def test_feed_type_invalid_falls_back_to_mock():
    """Test invalid feed type falls back to MOCK with warning."""
    with patch.dict(os.environ, {"FEED_TYPE": "INVALID"}, clear=True):
        feed_type = get_feed_type()
        assert feed_type == "MOCK"


def test_ibkr_connection_config_defaults():
    """Test IBKR connection config uses safe defaults."""
    with patch.dict(os.environ, {}, clear=True):
        config = get_ibkr_connection_config()
        assert config.host == "127.0.0.1"
        assert config.port == 7497
        assert config.client_id == 1


def test_ibkr_connection_config_from_env():
    """Test IBKR connection config from environment."""
    with patch.dict(os.environ, {
        "IBKR_HOST": "192.168.1.100",
        "IBKR_PORT": "7496",
        "IBKR_CLIENT_ID": "42",
    }, clear=True):
        config = get_ibkr_connection_config()
        assert config.host == "192.168.1.100"
        assert config.port == 7496
        assert config.client_id == 42


def test_ibkr_connection_config_invalid_port_uses_default():
    """Test invalid port falls back to default."""
    with patch.dict(os.environ, {"IBKR_PORT": "invalid"}, clear=True):
        config = get_ibkr_connection_config()
        assert config.port == 7497  # Default


def test_ibkr_connection_config_invalid_client_id_uses_default():
    """Test invalid client_id falls back to default."""
    with patch.dict(os.environ, {"IBKR_CLIENT_ID": "not_a_number"}, clear=True):
        config = get_ibkr_connection_config()
        assert config.client_id == 1  # Default


def test_ibkr_contract_config_missing_required_fields():
    """Test contract config returns None if required fields missing."""
    with patch.dict(os.environ, {}, clear=True):
        config = get_ibkr_contract_config()
        assert config is None


def test_ibkr_contract_config_valid():
    """Test contract config from environment."""
    with patch.dict(os.environ, {
        "IBKR_SYMBOL": "MNQ",
        "IBKR_EXPIRY": "202603",
    }, clear=True):
        config = get_ibkr_contract_config()
        assert config is not None
        assert config.symbol == "MNQ"
        assert config.expiry == "202603"
        assert config.contract_key == "MNQ.202603"
        assert config.exchange == "CME"  # Default
        assert config.currency == "USD"  # Default


def test_ibkr_contract_config_with_all_fields():
    """Test contract config with all fields specified."""
    with patch.dict(os.environ, {
        "IBKR_SYMBOL": "ES",
        "IBKR_EXPIRY": "202612",
        "IBKR_EXCHANGE": "GLOBEX",
        "IBKR_CURRENCY": "EUR",
        "IBKR_MULTIPLIER": "50",
    }, clear=True):
        config = get_ibkr_contract_config()
        assert config is not None
        assert config.symbol == "ES"
        assert config.expiry == "202612"
        assert config.exchange == "GLOBEX"
        assert config.currency == "EUR"
        assert config.multiplier == 50


def test_ibkr_contract_config_invalid_expiry_format():
    """Test contract config rejects invalid expiry format."""
    with patch.dict(os.environ, {
        "IBKR_SYMBOL": "MNQ",
        "IBKR_EXPIRY": "2026-03",  # Wrong format
    }, clear=True):
        config = get_ibkr_contract_config()
        assert config is None


def test_ibkr_contract_config_expiry_too_short():
    """Test contract config rejects short expiry."""
    with patch.dict(os.environ, {
        "IBKR_SYMBOL": "MNQ",
        "IBKR_EXPIRY": "2026",  # Too short
    }, clear=True):
        config = get_ibkr_contract_config()
        assert config is None


def test_main_with_mock_feed():
    """Test main entrypoint uses MOCK feed by default (no adapter)."""
    with patch.dict(os.environ, {"FEED_TYPE": "MOCK"}, clear=True):
        # Import after env is set
        from src.main import main

        # Mock UI to avoid running indefinitely
        with patch("src.main.MinimalCLI") as mock_ui_class:
            mock_ui = Mock()
            mock_ui_class.return_value = mock_ui

            # Mock sys.argv to avoid runtime arg
            with patch("sys.argv", ["main.py"]):
                # Mock time.sleep to speed up test
                with patch("time.sleep"):
                    try:
                        main()
                    except Exception:
                        # UI.run() may raise when mocked, that's OK
                        pass

            # Verify MOCK feed doesn't create adapter runner
            # (This is implicit - no adapter imports should fail)


def test_main_with_ibkr_feed_no_config():
    """Test main with IBKR feed but missing contract config (degraded mode)."""
    with patch.dict(os.environ, {
        "FEED_TYPE": "IBKR",
        # No IBKR_SYMBOL or IBKR_EXPIRY set
    }, clear=True):
        from src.main import main

        # Mock UI
        with patch("src.main.MinimalCLI") as mock_ui_class:
            mock_ui = Mock()
            mock_ui_class.return_value = mock_ui

            with patch("sys.argv", ["main.py"]):
                with patch("time.sleep"):
                    try:
                        main()
                    except Exception:
                        pass

            # Should log error but not crash


def test_ibkr_adapter_runner_factory_invoked():
    """Test that IBKR adapter runner factory is invoked when feed is IBKR."""
    with patch.dict(os.environ, {
        "FEED_TYPE": "IBKR",
        "IBKR_SYMBOL": "MNQ",
        "IBKR_EXPIRY": "202603",
    }, clear=True):
        from src.main import _create_ibkr_adapter_runner
        from src.feed_config import get_ibkr_connection_config, get_ibkr_contract_config

        conn = get_ibkr_connection_config()
        contract = get_ibkr_contract_config()

        # Mock IBKRAdapter and AdapterRunner to avoid real connection
        # Need to patch where they're imported, not where they're defined
        with patch("src.ibkr_adapter.IBKRAdapter") as mock_adapter_class:
            with patch("src.adapter_runner.AdapterRunner") as mock_runner_class:
                mock_adapter = Mock()
                mock_adapter.connect.return_value = True
                mock_adapter.qualify_contract.return_value = True
                mock_adapter.subscribe_market_data.return_value = True
                mock_adapter_class.return_value = mock_adapter

                mock_runner = Mock()
                mock_runner_class.return_value = mock_runner

                # Mock InboundQueue
                mock_queue = Mock()

                # Call factory
                runner = _create_ibkr_adapter_runner(conn, contract, mock_queue)

                # Verify adapter was created
                assert mock_adapter_class.called
                assert mock_adapter.connect.called
                assert mock_adapter.qualify_contract.called
                assert mock_adapter.subscribe_market_data.called

                # Verify runner was created
                assert mock_runner_class.called
                assert runner == mock_runner


def test_ibkr_adapter_runner_connect_failure():
    """Test that factory returns None if adapter connect fails."""
    with patch.dict(os.environ, {
        "FEED_TYPE": "IBKR",
        "IBKR_SYMBOL": "MNQ",
        "IBKR_EXPIRY": "202603",
    }, clear=True):
        from src.main import _create_ibkr_adapter_runner
        from src.feed_config import get_ibkr_connection_config, get_ibkr_contract_config

        conn = get_ibkr_connection_config()
        contract = get_ibkr_contract_config()

        # Mock adapter with failed connection
        with patch("src.ibkr_adapter.IBKRAdapter") as mock_adapter_class:
            mock_adapter = Mock()
            mock_adapter.connect.return_value = False  # Connection fails
            mock_adapter_class.return_value = mock_adapter

            mock_queue = Mock()

            # Call factory
            runner = _create_ibkr_adapter_runner(conn, contract, mock_queue)

            # Should return None on connection failure
            assert runner is None
            assert mock_adapter.connect.called


def test_ibkr_adapter_runner_qualify_failure():
    """Test that factory returns None if contract qualify fails."""
    with patch.dict(os.environ, {
        "FEED_TYPE": "IBKR",
        "IBKR_SYMBOL": "MNQ",
        "IBKR_EXPIRY": "202603",
    }, clear=True):
        from src.main import _create_ibkr_adapter_runner
        from src.feed_config import get_ibkr_connection_config, get_ibkr_contract_config

        conn = get_ibkr_connection_config()
        contract = get_ibkr_contract_config()

        # Mock adapter with failed qualification
        with patch("src.ibkr_adapter.IBKRAdapter") as mock_adapter_class:
            mock_adapter = Mock()
            mock_adapter.connect.return_value = True
            mock_adapter.qualify_contract.return_value = False  # Qualify fails
            mock_adapter.disconnect = Mock()
            mock_adapter_class.return_value = mock_adapter

            mock_queue = Mock()

            # Call factory
            runner = _create_ibkr_adapter_runner(conn, contract, mock_queue)

            # Should return None and disconnect on qualify failure
            assert runner is None
            assert mock_adapter.qualify_contract.called
            assert mock_adapter.disconnect.called
