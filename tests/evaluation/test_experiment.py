import csv
from statistics import mean

import pytest

from research.experiment import (
    METHODS, EvaluationConfig, capture_info, count_metrics, digest, evaluate_suite, event_delays,
    identity_metrics, make_synthetic_suite, package_capture, read_json, replay_rows,
    validate_split, write_json,
)
from research.in_room import RoomCalibration


A, B = '02:00:00:00:00:01', '02:00:00:00:00:02'
SNIFFER = '02:00:00:00:00:ff'


def status(t):
    return t, dict(v=1, type='status', node='sniffer', boot_id='synthetic-eval', ts_us=t * 1_000_000,
                   seq=t * 10, capture_active=True, own_mac=SNIFFER, channel=6, probe_seen=0,
                   probe_dropped=0, invalid=0, serial_errors=0, bytes_written=0, serial_baud=460800,
                   sniffer_enabled=True, scan_mode='fixed', dwell_ms=3000)


def probe(t, mac=A, rssi=-80):
    return t, dict(v=1, type='probe', node='sniffer', boot_id='synthetic-eval', ts_us=t * 1_000_000,
                   seq=t * 10 + 1, source_mac=mac, rssi=rssi, channel=6, frame_seq=t,
                   ie='1:8,50:4,45:26,127:8,221:6')


def manifest():
    return dict(test_id='case', scenario='room_1', synthetic=True, started_at='2026-11-20T00:00:00Z', setup_id='setup')


@pytest.fixture
def study(tmp_path):
    root = tmp_path / 'study'
    make_synthetic_suite(root)
    return root


def test_count_metrics_preserve_unknown_and_measure_both_error_directions():
    method = METHODS[0]
    rows = [dict(ground_truth_device_count=2, **{method: value}) for value in (3, 0, None, 2)]
    scores = count_metrics(rows, method)
    assert scores == dict(samples=4, available=3, coverage=.75, mae=1, rmse=pytest.approx((5 / 3) ** .5),
                          overcount_rate=1 / 3, undercount_rate=1 / 3)
    assert count_metrics([dict(ground_truth_device_count=1, **{method: None})], method)['rmse'] is None


def test_delay_censors_existing_count_and_missing_coverage():
    method = METHODS[0]
    rows = [dict(t_s=t, **{method: value}) for t, value in enumerate((1, 1, 1, None, 0, 0, 1, 1))]
    truth = [dict(t_s=t, device_count=value) for t, value in [(0, 0), (1, 1), (3, 0), (5, 1)]]
    events = list(event_delays(rows, truth, method, 8))
    assert [(event['direction'], event['status'], event['delay_s']) for event in events] == [
        ('arrival', 'preexisting_target', None), ('departure', 'coverage_gap', None), ('arrival', 'detected', 1)]
    departure = list(event_delays([dict(t_s=t, **{method: value}) for t, value in enumerate((1, 1, 1, 0))],
                                  [dict(t_s=0, device_count=1), dict(t_s=1, device_count=0)], method, 4))
    assert departure[0]['delay_s'] == 2


def test_identity_error_stats_ignore_unobserved_labels_and_count_pair_errors():
    labels = {'a': 'p1', 'b': 'p1', 'c': 'p2', 'unobserved': 'p2'}
    result = identity_metrics(labels, {'a': 'c1', 'b': 'c2', 'c': 'c2', 'unlabelled': 'c1'})
    assert result['labelled_aliases'] == 4 and result['observed_labelled_aliases'] == 3
    assert result['over_merge_pairs'] == result['over_split_pairs'] == 1
    assert result['over_merge_rate'] == .5 and result['over_split_rate'] == 1
    assert identity_metrics(None, {}) is None


def test_replay_prefix_avoids_using_future_aliases_and_missing_calibration_is_unknown():
    records = sorted([status(t) for t in range(10)] + [probe(t) for t in (0, 1, 2)]
                     + [probe(t, B) for t in (3, 4, 5)], key=lambda row: row[0])
    truth = [dict(t_s=0., device_count=1)]
    measured = list(replay_rows(records, truth, manifest(), EvaluationConfig(), 'cfg'))
    assert measured[3][METHODS[0]] == measured[3][METHODS[1]] == 2
    assert measured[5][METHODS[0]] == 2 and measured[5][METHODS[1]] == 1
    assert measured[5]['fingerprint_count'] == 1
    assert all(row[METHODS[2]] is None for row in measured)
    assert measured[0]['timestamp_utc'] == '2026-11-20T00:00:00+00:00'
    # Mutating ground truth changes labels only.
    changed = list(replay_rows(records, [dict(t_s=0., device_count=5)], manifest(), EvaluationConfig(), 'cfg'))
    assert [[row[method] for method in METHODS] for row in measured] == [[row[method] for method in METHODS] for row in changed]


def test_c_reports_numeric_counts_when_a_compatible_reference_is_supplied():
    zones = {'inside_near': -55, 'inside_far': -80, 'inside_boundary': -70, 'hallway': -33, 'outside_boundary': -44}
    refs = RoomCalibration(setup_id='setup', sniffer_mac=SNIFFER, channel=6, window_s=30, bin_s=5, rssi_min=-127,
                           samples=[dict(zone=zone, session_id=f'dev-{zone}', window_end_s=30,
                                         features=dict(median_rssi_dbm=rssi, rssi_mad_db=0, observation_ratio=1))
                                    for zone, rssi in zones.items()])
    config = EvaluationConfig(calibration=refs, location={'min_reference_windows': 1, 'min_reference_sessions': 1})
    frames = sorted([status(t) for t in range(0, 33, 2)] + [probe(t) for t in (1, 6, 11, 16, 21, 26)], key=lambda row: row[0])
    rows = list(replay_rows(frames, [dict(t_s=0, device_count=1)], manifest(), config, 'cfg'))
    assert rows[29][METHODS[2]] is None
    assert {rows[30][method] for method in METHODS} == {1}
    assert rows[30]['estimated_in_room_count'] == 1 and rows[30]['location_unknown_count'] == 0


def test_package_preserves_capture_and_requires_explicit_synthetic_origin(study, tmp_path):
    source = study / 'seed-development'
    with pytest.raises(ValueError, match='does not match scenario'):
        package_capture(source, tmp_path, test_id='room-zero', batch_id='run1', scenario='room_0')
    assert not (tmp_path / 'room-zero').exists()
    destination = package_capture(source, tmp_path, test_id='annotated', batch_id='run1', scenario='entry_exit')
    assert digest(destination / 'raw.jsonl') == digest(source / 'raw.jsonl')
    metadata = read_json(destination / 'metadata.json')
    metadata.update(synthetic=False, started_at='2026-11-20T00:00:00Z')
    write_json(destination / 'metadata.json', metadata)
    with pytest.raises(ValueError, match='declares synthetic'):
        capture_info(destination)


def test_split_detects_config_drift_shared_batches_and_test_reference(study):
    root = study / 'captures'
    split = read_json(study / 'split.json')
    config = EvaluationConfig()
    with pytest.raises(ValueError, match='configuration SHA-256'):
        validate_split(root, split, 'wrong', config, True)
    with pytest.raises(ValueError, match='enable synthetic'):
        validate_split(root, split, split['config_sha256'], config, False)
    test_manifest = root / 'test' / 'experiment.json'
    data = read_json(test_manifest)
    original = data['batch_id']
    data['batch_id'] = 'fixture-development'
    write_json(test_manifest, data)
    with pytest.raises(ValueError, match='batches must be disjoint'):
        validate_split(root, split, split['config_sha256'], config, True)
    data['batch_id'] = original
    write_json(test_manifest, data)
    calibration = RoomCalibration(setup_id='setup', sniffer_mac=SNIFFER, channel=6, window_s=30, bin_s=5, rssi_min=-127,
                                  samples=[dict(session_id='test', zone='hallway', window_end_s=30,
                                                features=dict(median_rssi_dbm=-50, rssi_mad_db=0, observation_ratio=1))])
    with pytest.raises(ValueError, match='must name development'):
        validate_split(root, split, split['config_sha256'], config.model_copy(update={'calibration': calibration}), True)


def test_split_detects_capture_copied_under_another_id(study):
    source = study / 'seed-development'
    metadata = read_json(source / 'metadata.json')
    metadata['id'] = 'synthetic-renamed'
    write_json(source / 'metadata.json', metadata)
    root = study / 'captures'
    package_capture(source, root, test_id='renamed', batch_id='another-batch', scenario='entry_exit')
    split = read_json(study / 'split.json')
    split['test'] = ['renamed']
    with pytest.raises(ValueError, match='same capture'):
        validate_split(root, split, split['config_sha256'], EvaluationConfig(), True)


def test_replay_exports_synthetic_markers_csv_schema_and_plots(study, tmp_path):
    output = tmp_path / 'results'
    report = evaluate_suite(study / 'captures', study / 'split.json', study / 'evaluation.json', output,
                            phase='test', allow_synthetic=True)
    assert report['synthetic'] and report['sessions'][0]['test_id'] == 'test'
    assert report['pooled'][METHODS[2]]['available_case']['available'] == 0
    assert all(report['pooled'][method]['common_case']['samples'] == 0 for method in METHODS)
    rows = list(csv.DictReader((output / 'timeline.csv').open()))
    assert len(rows) == 89 and {row['synthetic'] for row in rows} == {'True'}
    assert all(row['estimated_in_room_count'] == '' for row in rows)
    assert report['pooled'][METHODS[0]]['available_case']['mae'] == mean(
        abs(int(row[METHODS[0]]) - int(row['ground_truth_device_count'])) for row in rows if row[METHODS[0]])
    assert (output / 'summary.csv').is_file() and (output / 'events.csv').is_file()
    for name in ('summary.md', 'overview.svg', 'timeline-test.svg'):
        assert 'SYNTHETIC' in (output / name).read_text()
    assert A not in (output / 'report.json').read_text()
