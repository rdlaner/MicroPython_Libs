"""Tests for unhandled/invalid events and state robustness for PTP SM.

These tests ensure unexpected signals do not change state or crash the SM and that
some edge payloads are handled gracefully.
"""

# Standard imports
import pytest

# Local imports
from mp_libs.time import ptp
from tests.fixtures.time_fixtures import ptp_make_sm


@pytest.mark.parametrize("state_cls", [
    ptp.StateReady,
    ptp.StateSyncReq,
    ptp.StateSyncResp,
    ptp.StateDelayReq,
    ptp.StateDelayResp,
])
def test_state_unhandled_signal_is_ignored(state_cls, ptp_make_sm):
    # Setup
    sm, tx_msgs = ptp_make_sm(num_sync_cycles=2)
    sm.transition(sm._current_state, state_cls())

    # snapshot
    before_state = type(sm._current_state)
    before_timestamps = (sm.t1, sm.t2, sm.t3, sm.t4)
    before_cycle = sm.cycle_count()
    before_timestamps_list = list(sm.timestamps)
    before_tx_len = len(tx_msgs)

    # Act: send an unknown signal value (not in PtpSig)
    sm.process_evt(ptp.PtpEvt(999))

    # Assert: no state change, no timestamp change, no new tx, results unchanged
    assert type(sm._current_state) is before_state
    assert (sm.t1, sm.t2, sm.t3, sm.t4) == before_timestamps
    assert sm.cycle_count() == before_cycle
    assert sm.timestamps == before_timestamps_list
    assert len(tx_msgs) == before_tx_len
