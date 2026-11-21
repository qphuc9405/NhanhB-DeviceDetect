from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from research.device_clustering import ClusteringConfig, cluster_devices
from research.in_room import InRoomConfig, RoomCalibration, SignalSample, estimate_room, window_features
from research.presence import PresenceConfig


MAC = '02:00:00:00:00:01'
SNIFFER = '02:00:00:00:00:ff'
SETUP = 'room-a-fixed-6'
TIMES = (1, 6, 11, 16, 21, 26)


def records(rssis, *, times=TIMES, scan_mode='fixed', missing_status=(), dropped_from=None):
    rows = []
    for t in range(0, 31, 2):
        if t in missing_status:
            continue
        rows.append((t, dict(v=1, type='status', node='sniffer', boot_id='boot', ts_us=t * 1_000_000,
                             seq=t * 10, capture_active=True, own_mac=SNIFFER, channel=6, probe_seen=0,
                             probe_dropped=int(dropped_from is not None and t >= dropped_from), invalid=0,
                             serial_errors=0, bytes_written=0, serial_baud=460800, sniffer_enabled=True,
                             scan_mode=scan_mode, dwell_ms=3000)))
    for t, rssi in zip(times, rssis, strict=True):
        rows.append((t, dict(v=1, type='probe', node='sniffer', boot_id='boot', ts_us=t * 1_000_000,
                             seq=t * 10 + 1, source_mac=MAC, rssi=rssi, channel=6, frame_seq=t,
                             ie='1:8,50:4,45:26,127:8,221:6')))
    return sorted(rows, key=lambda row: row[0])


def references(*, hallway=-33, omit=None):
    samples = []
    zones = {'inside_near': -55, 'inside_far': -80, 'inside_boundary': -70,
             'hallway': hallway, 'outside_boundary': -44}
    for zone, rssi in zones.items():
        if zone == omit:
            continue
        for session, t in [(1, 30), (1, 60), (2, 30)]:
            samples.append(dict(session_id=f'{zone}-{session}', window_end_s=t, zone=zone,
                                features=dict(median_rssi_dbm=rssi, rssi_mad_db=0, observation_ratio=1)))
    return RoomCalibration(setup_id=SETUP, sniffer_mac=SNIFFER, channel=6,
                           window_s=30, bin_s=5, rssi_min=-127, samples=samples)


def estimate(rows, calibration=None, *, setup_id=SETUP, until=None):
    clustering = cluster_devices(rows, ClusteringConfig())
    before = deepcopy(clustering)
    result = estimate_room(rows, clustering, PresenceConfig(), InRoomConfig(), setup_id=setup_id,
                           calibration=calibration, until=until)
    assert clustering == before
    assert result['confirmed_count'] == (result['estimated_in_room_count'] + result['outside_likely_count']
                                         + result['location_unknown_count'])
    return result


def test_strong_hallway_signal_and_weak_indoor_signal_can_be_separated_by_references():
    hallway = estimate(records([-33] * 6), references())
    assert hallway['outside_likely_count'] == 1
    assert hallway['clusters'][0]['evidence']['nearest_outside_zone'] == 'hallway'
    indoor = estimate(records([-80] * 6), references())
    assert indoor['estimated_in_room_count'] == 1
    row = indoor['clusters'][0]
    assert row['features'] == dict(median_rssi_dbm=-80, rssi_mad_db=0, probe_count=6,
                                   observation_count=6, observation_ratio=1, last_seen_s=26,
                                   channels=[6], recent_shift_db=0)
    assert row['evidence']['inside_support_sessions'] == 4


def test_overlapping_hallway_and_inside_references_abstain():
    report = estimate(records([-55] * 6), references(hallway=-55))
    assert report['estimated_in_room_count'] == 0 and report['location_unknown_count'] == 1
    assert report['clusters'][0]['reason'] == 'overlapping_location_evidence'


@pytest.mark.parametrize('rows,reason', [
    (records([-80] * 3, times=(1, 11, 21)), 'insufficient_observations'),
    (records([-45, -75] * 3), 'unstable_or_changing_rssi'),
    (records([-55] * 3 + [-80] * 3), 'unstable_or_changing_rssi'),
    (records([-55] * 5 + [-80]), 'unstable_or_changing_rssi'),
    (records([-80] * 6, missing_status=(12, 14, 16)), 'insufficient_continuous_coverage'),
    (records([-80] * 6, dropped_from=24), 'insufficient_continuous_coverage'),
    (records([-80] * 6, scan_mode='hopping'), 'unsupported_or_mixed_channels'),
])
def test_sparse_loss_noise_movement_and_hopping_stay_unknown(rows, reason):
    report = estimate(rows, references())
    assert report['location_unknown_count'] == 1
    assert report['clusters'][0]['reason'] == reason
    assert not report['clusters'][0]['reference_eligible']


def test_missing_incomplete_or_wrong_setup_calibration_stays_unknown():
    rows = records([-80] * 6)
    for calibration, setup, reason in [(None, SETUP, 'missing_calibration'),
                                        (references(omit='inside_boundary'), SETUP, 'insufficient_calibration'),
                                        (references(), 'other-placement', 'calibration_setup_mismatch')]:
        report = estimate(rows, calibration, setup_id=setup)
        assert report['location_unknown_count'] == 1
        assert report['calibration_status'] == report['clusters'][0]['reason'] == reason
        assert report['clusters'][0]['reference_eligible']
        assert report['clusters'][0]['evidence'] is None


def test_an_isolated_matching_reference_session_does_not_support_classification():
    calibration = references()
    for sample in calibration.samples:
        if sample.session_id == 'inside_far-2':
            sample.features.median_rssi_dbm = -105
    report = estimate(records([-90] * 6), calibration)
    assert report['location_unknown_count'] == 1
    assert report['clusters'][0]['reason'] == 'insufficient_nearby_reference_sessions'


def test_dense_burst_only_populates_one_time_bin_and_one_probe_stays_unconfirmed():
    samples = [SignalSample(28 + index * .01, 'cluster', -45, 6) for index in range(50)]
    result = window_features(samples, 30, InRoomConfig())
    assert result['probe_count'] == 50 and result['observation_count'] == 1
    assert estimate(records([-80], times=(26,)), references())['confirmed_count'] == 0


def test_cli_reads_reference_file_without_mutating_raw_session(tmp_path):
    rows = records([-80] * 6)
    raw = tmp_path / 'raw.jsonl'
    contents = ''.join(json.dumps(dict(host_elapsed_s=t, packet=packet)) + '\n' for t, packet in rows)
    raw.write_text(contents)
    calibration = tmp_path / 'calibration.json'
    calibration.write_text(references().model_dump_json())
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, '-m', 'research.in_room', str(raw), '--setup-id', SETUP,
               '--calibration', str(calibration), '--until', '30']
    result = json.loads(subprocess.check_output(command, cwd=root))
    assert result['estimated_in_room_count'] == 1 and result['observed_sniffer_count'] == 1
    assert result['scan_mode'] == 'fixed' and result['fixed_channel'] == 6
    assert raw.read_text() == contents


def test_default_snapshot_uses_last_capture_before_intentional_close():
    rows = records([-80] * 6) + [(31, {'type': 'control', 'kind': 'session_stopped'})]
    report = estimate(rows, references())
    assert report['t_s'] == 30 and report['estimated_in_room_count'] == 1
    assert estimate(rows, references(), until=31)['observation_valid'] is False
