import pytest
from tests.mocks.mock_protocols import MockESPNow, MockWifiProtocol


@pytest.fixture
def protocol_mocks(mocker):
    wifi_proto_mock = mocker.patch("mp_libs.protocols.espnow_protocol.WifiProtocol", side_effect=MockWifiProtocol)
    espnow_mock = mocker.patch("mp_libs.protocols.espnow_protocol.espnow.ESPNow", side_effect=MockESPNow)
    MockESPNow.clear_peers()

    yield wifi_proto_mock, espnow_mock
