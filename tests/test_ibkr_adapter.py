import pytest

from src.ibkr_adapter import (
    IBKRAdapter,
    InboundQueue,
    MD_DELAYED,
    MD_FROZEN,
    MD_NONE,
    MD_REALTIME,
    StatusEvent,
    SubscriptionManager,
    map_md_mode,
)


class _FakeClient:
    def __init__(self) -> None:
        self.mktdata_calls = []

    def connect(self, host, port, client_id):
        return True

    def disconnect(self):
        return None

    def isConnected(self):
        return True

    def reqMktData(self, req_id, contract, *args, **kwargs):
        self.mktdata_calls.append((req_id, contract))

    def reqContractDetails(self, req_id, contract):
        return None


def test_map_md_mode_values():
    assert map_md_mode(1) == MD_REALTIME
    assert map_md_mode(2) == MD_FROZEN
    assert map_md_mode(3) == MD_DELAYED
    assert map_md_mode(4) == MD_FROZEN
    assert map_md_mode(None) == MD_NONE
    assert map_md_mode(999) == MD_NONE


def test_md_mode_transition_emits_status():
    inbound = InboundQueue()
    adapter = IBKRAdapter(
        host="127.0.0.1",
        port=4001,
        client_id=123,
        contract_key="MNQ.202603",
        inbound_queue=inbound,
        client=_FakeClient(),
    )

    adapter.marketDataType(0, 1)
    event = inbound.get(timeout=0.1)
    assert isinstance(event, StatusEvent)
    assert event.md_mode == MD_REALTIME
    assert adapter.md_mode == MD_REALTIME


def test_subscription_manager_idempotent_and_rate_limited():
    client = _FakeClient()
    manager = SubscriptionManager(client, min_reapply_interval_s=5.0)
    contract = object()
    now = 100.0

    manager.mark_connected()
    assert manager.maybe_apply(contract, 1, now) is True
    assert len(client.mktdata_calls) == 1

    assert manager.maybe_apply(contract, 1, now + 1.0) is False
    assert len(client.mktdata_calls) == 1

    manager.mark_connected()
    assert manager.maybe_apply(contract, 1, now + 2.0) is False
    assert len(client.mktdata_calls) == 1

    assert manager.maybe_apply(contract, 1, now + 6.0) is True
    assert len(client.mktdata_calls) == 2


def test_error_326_fails_fast():
    inbound = InboundQueue()
    adapter = IBKRAdapter(
        host="127.0.0.1",
        port=4001,
        client_id=123,
        contract_key="MNQ.202603",
        inbound_queue=inbound,
        client=_FakeClient(),
    )

    with pytest.raises(SystemExit) as excinfo:
        adapter.error(0, 326, "clientId already in use")

    assert excinfo.value.code == 1
