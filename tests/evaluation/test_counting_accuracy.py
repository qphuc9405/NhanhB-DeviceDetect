import pytest

from research.counting_accuracy import CountingConfig, compare_pair, pass_labels, replay_capture, score
from research.detectors import ProbeConfig


A = '02:00:00:00:00:01'
B = '02:00:00:00:00:02'
SNIFFER = '02:00:00:00:00:ff'
IE = '1:8,50:4,45:26,127:8,221:6'


def radio(t, kind, **values):
    return dict(v=1, node='sniffer', type=kind, boot_id='test-radio',
                ts_us=round(t * 1_000_000), seq=round(t * 1000), **values)


def status(t, *, channel=6, mode='fixed', dropped=0, errors=0):
    return t, radio(t, 'status', own_mac=SNIFFER, capture_active=True, sniffer_enabled=True,
                    scan_mode=mode, channel=channel, dwell_ms=3000, probe_dropped=dropped,
                    serial_errors=errors, probe_seen=0, serial_baud=460800, invalid=0, bytes_written=0)


def probe(t, mac=A, channel=6, *, rssi=-60):
    return t, radio(t, 'probe', source_mac=mac, rssi=rssi, channel=channel,
                    frame_seq=round(t * 1000) % 4096, ie=IE, retry=False)


def replay(records, **changes):
    cfg = CountingConfig(probe=ProbeConfig(slot_s=10, arrival_slots=2, withdrawal_slots=2,
                                           departure_slots=3), **changes)
    return replay_capture(sorted(records, key=lambda row: row[0]), cfg)


def test_sparse_probe_timing_and_two_hits_in_same_slot():
    signals = [status(t) for t in range(0, 54, 2)] + [probe(t) for t in (1, 2, 31, 41)]
    rows, audit = replay(signals, sherlock_variants={
        'retain': dict(slot_s=10, arrival_slots=2, withdrawal_slots=3, departure_slots=3)})
    assert rows[2]['rssi_timeout'] == 1 and rows[2]['sherlock_mac'] == 0
    assert rows[2]['timeout_first_or_returning_hit_in_open_slot'] == 1
    assert rows[20]['timeout_candidate_waiting_for_more_positive_slots'] == 1
    assert rows[30]['timeout_no_current_sherlock_track'] == 1
    assert rows[40]['sherlock_mac'] == 0 and rows[40]['sherlock_mac__retain'] == 1
    assert rows[50]['sherlock_mac'] == 1
    assert audit['radio_inter_probe_gap_s'] == dict(n=3, median=10, p90=29, max=29)
    assert audit['stream_events']['candidate_cancelled_no_observation'] == 1


def test_hopping_exposure_and_loss_metadata_do_not_fill_heartbeat_gaps():
    records = [
        status(0, channel=1, mode='hopping'), probe(0, channel=1),
        (0, radio(0, 'channel', channel=6, dwell_ms=3000)), probe(1, channel=6),
        status(2, channel=6, mode='hopping', dropped=3, errors=2),
        probe(8, channel=6), status(10, channel=1, mode='hopping', dropped=3, errors=2),
        probe(11, channel=1), status(14, channel=1, mode='hopping', dropped=3, errors=2),
    ]
    rows, audit = replay(records)
    assert rows[8]['rssi_timeout'] is None and rows[10]['sherlock_mac'] == 0
    assert audit['probe_disposition']['no_valid_heartbeat'] == 1
    assert audit['stream_events']['heartbeat_gap'] == 1
    assert audit['scan_modes'] == ['hopping']
    assert audit['counter_increase'] == dict(probe_dropped=3, serial_errors=2)
    assert audit['gap_channel_opportunity']['no_tuned_time_on_previous_channel'] == 1
    assert audit['tuned_seconds_by_channel'] == {1: 4, 6: 7}


def test_scoring_only_uses_truth_after_replay():
    records = [status(t) for t in range(8)] + [probe(1), probe(2)]
    rows, _ = replay(records)
    manifest = dict(test_id='test', synthetic=True, started_at='2026-11-20T00:00:00Z')
    one = pass_labels(rows, [dict(t_s=0, device_count=1)], manifest)
    zero = pass_labels(rows, [dict(t_s=0, device_count=0)], manifest)
    assert [row['rssi_timeout'] for row in one] == [row['rssi_timeout'] for row in zero]
    assert score(one, 'rssi_timeout')['missed_count_units'] == 2
    assert score(zero, 'rssi_timeout')['excess_count_units'] == 5
    assert score(one, 'rssi_timeout')['false_negative_rate'] == 2 / 7
    assert score(zero, 'rssi_timeout')['false_positive_rate'] == 5 / 7
    assert score(zero, 'rssi_timeout')['false_negative_rate'] is None
    assert compare_pair(zero, 'rssi_timeout', 'sherlock_mac')['method_worse'] == 5


def test_rotation_is_causal_and_same_ie_with_overlapping_activity_does_not_merge():
    methods = ('sherlock_mac', 'sherlock_cluster')
    head = [status(t) for t in range(0, 35, 2)] + [probe(t) for t in (1, 6, 9)]
    rotation = [probe(t, B) for t in (11, 16, 21)]
    rows, _ = replay(head + rotation, methods=methods)
    old_prefix, _ = replay([(t, p) for t, p in head + rotation if t <= 20], methods=methods)
    assert rows[:20] == old_prefix
    assert rows[20]['sherlock_cluster'] == rows[20]['sherlock_mac'] == 0
    assert rows[21]['sherlock_cluster'] == 1 and rows[21]['sherlock_mac'] == 0

    overlapping, _ = replay(head + rotation + [probe(18)], methods=methods)
    assert overlapping[21]['sherlock_cluster'] == overlapping[21]['sherlock_mac'] == 1
    assert overlapping[31]['sherlock_cluster'] == overlapping[31]['sherlock_mac'] == 2


def test_probable_uses_spaced_observations_and_both_windows_with_unknown_location():
    methods = ('proposed_30s', 'proposed_60s', 'proposed_room_30s', 'proposed_room_60s')
    records = [status(t) for t in range(0, 72, 2)] + [probe(t) for t in (10.1, 10.2, 36, 43, 67)]
    rows, _ = replay(records, methods=methods)
    assert rows[30]['candidate_clusters_30s'] == 1 and rows[30]['proposed_30s'] == 0
    assert rows[40]['probable_clusters_30s'] == 1 and rows[40]['proposed_30s'] == 1
    assert rows[40]['proposed_60s'] is None
    assert rows[60]['probable_clusters_30s'] == rows[60]['confirmed_clusters_60s'] == 1
    assert all(row['proposed_room_30s'] is None and row['proposed_room_60s'] is None for row in rows)


def test_loss_restarts_proposed_coverage_only():
    methods = ('rssi_timeout', 'sherlock_cluster', 'proposed_30s')
    records = [status(t, dropped=int(t >= 32)) for t in range(0, 66, 2)]
    records += [probe(t) for t in (11, 12, 23, 31, 36, 41, 46)]
    rows, _ = replay(records, methods=methods)
    assert rows[31]['proposed_30s'] == 1
    assert rows[32]['rssi_timeout'] == 1 and rows[32]['proposed_30s'] is None
    assert rows[61]['proposed_30s'] is None and rows[62]['proposed_30s'] == 1


def test_capacity_reports_unknown_instead_of_truncating_cluster_count():
    records = [status(t) for t in range(0, 8, 2)]
    records += [probe(1, f'02:00:00:00:01:{i:02x}') for i in range(129)]
    rows, _ = replay(records, methods=('rssi_timeout', 'sherlock_cluster'))
    assert rows[1]['cluster_capacity_limited']
    assert rows[1]['sherlock_cluster'] is None and rows[1]['rssi_timeout'] == 0
    expanded, _ = replay(records, methods=('sherlock_cluster',), max_cluster_aliases=129)
    assert not expanded[1]['cluster_capacity_limited'] and expanded[1]['sherlock_cluster'] == 0


def test_room_count_requires_compatible_calibration():
    from test_experiment import manifest
    from research.in_room import RoomCalibration

    zones = {'inside_near': -55, 'inside_far': -80, 'inside_boundary': -70, 'hallway': -33, 'outside_boundary': -44}
    calibration = RoomCalibration(
        setup_id='setup', sniffer_mac=SNIFFER, channel=6, window_s=30, bin_s=5, rssi_min=-127,
        samples=[dict(zone=zone, session_id=f'dev-{zone}', window_end_s=30,
                      features=dict(median_rssi_dbm=rssi, rssi_mad_db=0, observation_ratio=1))
                 for zone, rssi in zones.items()])
    records = sorted([status(t) for t in range(0, 36, 2)]
                     + [probe(t, rssi=-80) for t in (1, 6, 11, 16, 21, 26)], key=lambda row: row[0])
    cfg = CountingConfig(methods=('proposed_room_30s',), calibration=calibration,
                         location={'min_reference_windows': 1, 'min_reference_sessions': 1})
    calibrated, _ = replay_capture(records, cfg, setup_id=manifest()['setup_id'])
    unknown, _ = replay_capture(records, cfg, setup_id='other')
    assert calibrated[30]['proposed_room_30s'] == 1
    assert unknown[30]['proposed_room_30s'] is None


def test_capture_external_timeline_split_and_report_artifacts(tmp_path):
    import csv
    import json

    from research.counting_accuracy import evaluate_suite
    from research.experiment import digest, package_capture, write_json

    external_truth = tmp_path / 'observer.jsonl'
    external_truth.write_text('{"t_s":0,"device_count":0}\n{"t_s":8,"device_count":1}\n')
    root = tmp_path / 'captures'
    for name in ('dev', 'holdout'):
        source = tmp_path / name
        source.mkdir()
        write_json(source / 'metadata.json', dict(synthetic=True, id=name, ended_at='2026-11-20T00:01:02Z',
                                                   started_at='2026-11-20T00:00:00Z'))
        raw = source / 'raw.jsonl'
        records = [status(t) for t in range(0, 63, 2)] + [probe(t) for t in (6, 8, 11, 16, 21, 26)]
        with raw.open('w') as out:
            for stamp, packet in sorted(records, key=lambda row: row[0]):
                json.dump(dict(host_elapsed_s=stamp, host_time='2026-11-20T00:00:00Z',
                               packet=dict(packet, boot_id=name)), out)
                out.write('\n')
        capture = package_capture(source, root, test_id=name, batch_id=name, scenario='entry_exit',
                                  truth_path=external_truth)
        assert (capture / 'raw.jsonl').read_bytes() == raw.read_bytes()
        assert (capture / 'truth.jsonl').read_bytes() == external_truth.read_bytes()
        assert not (source / 'truth.jsonl').exists()

    cfg, split = tmp_path / 'counting.json', tmp_path / 'split.json'
    write_json(cfg, dict(methods=['rssi_timeout', 'sherlock_mac', 'proposed_30s'],
                         probe=dict(slot_s=10, arrival_slots=2)))
    write_json(split, dict(development=['dev'], test=['holdout'], config_sha256=digest(cfg)))
    output = tmp_path / 'report'
    with pytest.raises(ValueError, match='synthetic'):
        evaluate_suite(root, split, cfg, output, phase='test')
    report = evaluate_suite(root, split, cfg, output, phase='test', allow_synthetic=True)
    assert report['synthetic'] and [row['test_id'] for row in report['sessions']] == ['holdout']
    assert report['pooled']['sherlock_mac']['arrival_delay']['detected'] == 1
    assert {row['baseline'] for row in report['comparisons']} == {'rssi_timeout', 'sherlock_mac'}
    assert any(row['method_worse'] for row in report['comparisons'])
    with (output / 'windows.csv').open() as handle:
        windows = list(csv.DictReader(handle))
    assert [(row['window_s'], row['start_s'], row['samples']) for row in windows] == [
        ('30', '0', '30'), ('30', '30', '30'), ('60', '0', '60')]
    assert windows[0]['proposed_30s_mean'] == '' and windows[2]['proposed_30s_available'] == '30'
    assert 'SYNTHETIC' in (output / 'timeline-holdout.svg').read_text()


def test_hopping_can_lose_a_positive_slot_from_the_same_emission_schedule():
    emissions = [probe(t, channel=6) for t in (1, 2, 11, 21)]
    fixed = [status(t) for t in range(0, 34, 2)] + emissions
    hopping = [status(t, channel=1 if 8 <= t < 16 else 6, mode='hopping')
               for t in range(0, 34, 2)]
    hopping += [row for row in emissions if not 8 <= row[0] < 16]
    fixed_rows, _ = replay(fixed)
    hopping_rows, _ = replay(hopping)
    assert fixed_rows[20]['sherlock_mac'] == 1 and hopping_rows[20]['sherlock_mac'] == 0
    assert hopping_rows[20]['rssi_timeout'] == 1
    assert hopping_rows[30]['sherlock_mac'] == 1
