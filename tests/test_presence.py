import json
from pathlib import Path
import subprocess
import sys

import pytest

from research.device_clustering import ClusteringConfig, cluster_devices
from research.evaluate import load_records
from research.presence import PresenceConfig, PresenceTracker, replay_presence


A, B = '02:00:00:00:00:01', '02:00:00:00:00:02'


def config(**values):
    return PresenceConfig(**(dict(observation_window_s=8, min_observation_spacing_s=2,
                                  stale_timeout_s=4, departure_timeout_s=9,
                                  heartbeat_timeout_s=3, absent_retention_s=5) | values))


def observe(tracker, t, cluster='one', captured=None):
    tracker.observe(cluster, t, round((t if captured is None else captured) * 1_000_000))


def status(t, *, boot='b', active=True):
    return t, dict(v=1, type='status', node='sniffer', boot_id=boot, ts_us=round(t * 1_000_000),
                   seq=round(t * 1000), capture_active=active, own_mac='02:00:00:00:00:ff', channel=6,
                   probe_seen=0, probe_dropped=0, invalid=0, serial_errors=0, bytes_written=0,
                   serial_baud=460800, sniffer_enabled=active, scan_mode='fixed', dwell_ms=3000)


def probe(t, mac=A, *, captured=None, boot='b'):
    return t, dict(v=1, type='probe', node='sniffer', boot_id=boot, seq=round(t * 1000) + 1,
                   ts_us=round((t if captured is None else captured) * 1_000_000), source_mac=mac,
                   channel=6, rssi=-52, frame_seq=1, ie='1:8,50:4,45:26,127:8,221:6')


def replay(records, cfg=None, *, clustering=None, until=None):
    cfg = cfg or config()
    clustering = clustering if clustering is not None else cluster_devices(records, ClusteringConfig())
    return replay_presence(records, clustering, cfg, until=until)


def test_one_probe_and_a_dense_burst_do_not_confirm():
    tracker = PresenceTracker(config())
    observe(tracker, 0)
    assert tracker.snapshot()['candidate_count'] == 1
    for t in (.1, .2, .3, .4):
        observe(tracker, t)
    assert tracker.snapshot()['clusters'][0]['independent_observations_pending'] == 1
    assert tracker.snapshot()['confirmed_count'] == 0
    tracker.advance(8.5)
    assert tracker.snapshot()['absent_count'] == 1
    assert tracker.events[-1]['reason'] == 'candidate_window_expired'


def test_confirmation_silence_recovery_and_departure_timeout():
    tracker = PresenceTracker(config())
    for t in (0, 2, 4):
        observe(tracker, t)
    assert tracker.snapshot()['confirmed_count'] == 1
    tracker.advance(7.9)
    assert tracker.snapshot()['confirmed_count'] == 1
    tracker.advance(8)
    assert tracker.snapshot()['stale_count'] == 1
    observe(tracker, 9)
    assert tracker.snapshot()['confirmed_count'] == 1
    assert tracker.events[-1]['reason'] == 'observed_again'
    tracker.advance(18)
    assert tracker.snapshot()['absent_count'] == 1
    assert tracker.events[-1]['observation_t_s'] == 18
    assert tracker.events[-1]['reason'] == 'observation_timeout'
    observe(tracker, 19)
    assert tracker.snapshot()['candidate_count'] == 1
    assert tracker.events[-1]['reason'] == 'observed_after_timeout'


def test_window_discards_spaced_but_old_evidence():
    tracker = PresenceTracker(config())
    for t in (0, 5, 10):
        observe(tracker, t)
    snapshot = tracker.snapshot()
    assert snapshot['clusters'][0]['independent_observations_pending'] == 2
    assert snapshot['confirmed_count'] == 0


def test_capture_spacing_blocks_a_burst_delivered_slowly():
    tracker = PresenceTracker(config())
    for t, capture_t in [(0, 0), (2, .1), (4, .2)]:
        observe(tracker, t, captured=capture_t)
    assert tracker.snapshot()['candidate_count'] == 1
    assert tracker.snapshot()['clusters'][0]['independent_observations_pending'] == 1


def test_capacity_cleanup_and_bounded_event_history():
    emitted = []
    tracker = PresenceTracker(config(max_clusters=2, max_recent_events=2), emitted.append)
    for cluster in ('one', 'two', 'three'):
        observe(tracker, 0, cluster)
    assert tracker.snapshot()['capacity_drops'] == 1
    tracker.advance(13)
    assert tracker.snapshot()['absent_count'] == 0
    assert tracker.snapshot()['cleaned_up_count'] == 2
    assert len(tracker.events) == 2 and len(emitted) == 6
    assert [event['observation_t_s'] for event in emitted] == [0, 0, 8, 8, 13, 13]
    assert tracker.events[-1]['to_state'] is None and tracker.events[-1]['reason'] == 'retention_expired'
    observe(tracker, 14, 'three')
    assert tracker.snapshot()['candidate_count'] == 1


def test_config_rejects_inconsistent_timeouts_and_unreachable_confirmation():
    with pytest.raises(ValueError, match='departure_timeout_s'):
        config(departure_timeout_s=4)
    with pytest.raises(ValueError, match='observation_window_s'):
        config(observation_window_s=3)


def test_replay_mac_rotation_shares_evidence_and_two_clusters_remain_independent():
    records = sorted([status(t) for t in range(0, 13, 2)] +
                     [probe(t) for t in (0, .1, .2)] + [probe(t, B) for t in (2, 4, 4.1)],
                     key=lambda row: row[0])
    report = replay(records)
    assert report['stale_count'] == 1
    assert [(event['cluster_id'], event['to_state'], event['t_s']) for event in report['events']] == [
        ('cluster-00001', 'CANDIDATE', 0), ('cluster-00001', 'CONFIRMED', 4),
        ('cluster-00001', 'STALE', 8.1)]
    baseline = cluster_devices(records, ClusteringConfig(enabled=False))
    baseline_report = replay(records, clustering=baseline, until=4.2)
    assert baseline_report['candidate_count'] == 2
    assert baseline_report['confirmed_count'] == 0


def test_heartbeat_gap_freezes_departure_clock_and_probe_recovers_stale():
    records = [status(0), probe(0), status(2), probe(2), status(4), probe(4),
               probe(20), status(21), probe(21), status(23)]
    gap = replay(records, until=20)
    assert gap['stale_count'] == 1 and gap['absent_count'] == 0
    assert gap['observation_valid'] is False and gap['observation_t_s'] == 7
    assert gap['probes_without_coverage'] == 1
    assert gap['events'][-1]['reason'] == 'heartbeat_gap' and gap['events'][-1]['t_s'] == 7
    report = replay(records)
    assert report['confirmed_count'] == 1 and report['observation_valid'] is True
    assert report['events'][-1]['reason'] == 'observed_again' and report['events'][-1]['t_s'] == 21


def test_two_overlapping_clusters_each_confirm_on_their_own_evidence():
    records = sorted([status(t) for t in (0, 2, 4)] + [probe(t) for t in (0, 2, 4)]
                     + [probe(t, B) for t in (.1, 2.2, 4.3)], key=lambda row: row[0])
    report = replay(records)
    assert report['confirmed_count'] == 2
    assert [event['cluster_id'] for event in report['events'] if event['to_state'] == 'CONFIRMED'] == [
        'cluster-00001', 'cluster-00002']


def test_probe_only_log_reports_missing_coverage():
    report = replay([probe(0), probe(2), probe(4)])
    assert report['confirmed_count'] == report['candidate_count'] == report['absent_count'] == 0
    assert report['probes_without_coverage'] == 3
    assert report['observation_valid'] is False


def test_covered_silence_expires_and_replay_does_not_extrapolate_past_eof():
    records = [status(0), probe(0), status(2), probe(2), status(4), probe(4)]
    prefix = replay(records, until=50)
    assert prefix['t_s'] == 4 and prefix['confirmed_count'] == 1
    result = replay(records + [status(t) for t in (6, 8, 10, 12, 14)])
    assert result['events'][-1]['t_s'] == 13
    assert result['absent_count'] == 1


def test_cli_replay_ignores_late_probe_and_is_repeatable(tmp_path):
    records = [status(0), probe(0), status(2), probe(2), status(4), probe(4),
               status(6), status(8), probe(6.2, captured=3), status(10), status(12), status(14)]
    raw = tmp_path / 'raw.jsonl'
    raw.write_text(''.join(json.dumps(dict(host_elapsed_s=t, packet=packet)) + '\n' for t, packet in records))
    assert [p['ts_us'] for t, p in load_records(raw) if t == 8] == [8_000_000, 3_000_000]
    configuration = tmp_path / 'presence.json'
    configuration.write_text(config().model_dump_json())
    command = [sys.executable, '-m', 'research.presence', str(raw), '--config', str(configuration)]
    root = Path(__file__).resolve().parents[1]
    output = subprocess.check_output(command, cwd=root)
    assert output == subprocess.check_output(command, cwd=root)
    result = json.loads(output)
    assert result['late_observation_count'] == 1
    assert result['events'][-1]['t_s'] == 13
    assert result['absent_count'] == 1
