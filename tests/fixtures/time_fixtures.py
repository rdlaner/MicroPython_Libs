import pytest
from mp_libs.time import ptp


@pytest.fixture
def ptp_make_sm():
    """Factory fixture to create and start a PTP state machine with a dummy tx function.

    Returns a factory `make(num_sync_cycles=2, timeout_ms=100, tx_fxn=None)` that returns (sm, tx_msgs).

    Timer tests should explicitly set shorter timeout_ms values when testing timeout behavior.
    """

    def _make(num_sync_cycles=2, timeout_ms=100, tx_fxn=None):
        tx_msgs = []

        def dummy_tx(data, **kwargs):
            tx_msgs.append(data)
            if tx_fxn is None:
                return True
            return tx_fxn(data, **kwargs)

        ptp.state_machine_init(dummy_tx, num_sync_cycles=num_sync_cycles, timeout_ms=timeout_ms)
        sm = ptp._ptp_sm
        sm.start(ptp.StateReady())
        return sm, tx_msgs

    return _make
