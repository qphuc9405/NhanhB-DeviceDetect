from itertools import combinations
import json
from pathlib import Path
import subprocess
import sys

import pytest

from research.device_clustering import ClusteringConfig, cluster_devices


A, B, C = [f'02:00:00:00:00:0{i}' for i in range(1, 4)]
PROFILE = '0:0,1:8,50:4,45:26,127:8,221:6'


def capture(mac, start, rssis=(-50, -51, -50), *, ie=PROFILE, channel=6, boot='test'):
    for index, rssi in enumerate(rssis):
        time = start + index * .2
        stamp = round(time * 1_000_000)
        yield time, dict(v=1, type='probe', boot_id=boot, node='sniffer', ts_us=stamp, seq=stamp,
                         source_mac=mac, rssi=rssi, channel=channel, frame_seq=index, ie=ie)


def infer(*captures, enabled=True):
    records = sorted((row for group in captures for row in group), key=lambda row: row[0])
    return cluster_devices(records, ClusteringConfig(enabled=enabled))


def decisions(report):
    return {event['mac']: event for cluster in report['clusters'] for event in cluster['association_history']}


def pair_errors(report, labels):
    # Labels are consulted only after association. Compare all known alias pairs.
    assigned = {mac: cluster['cluster_id'] for cluster in report['clusters'] for mac in cluster['mac_aliases']}
    over_merge = over_split = 0
    for left, right in combinations(labels, 2):
        same_cluster = assigned[left] == assigned[right]
        same_device = labels[left] == labels[right]
        over_merge += same_cluster and not same_device
        over_split += same_device and not same_cluster
    return over_merge, over_split


@pytest.mark.parametrize('specs, labels, expected', [
    pytest.param([(A, 0), (B, 3), (C, 6)], {A: 1, B: 1, C: 1}, (0, 0), id='three-aliases-one-device'),
    pytest.param([(A, 0), (B, .1)], {A: 1, B: 2}, (0, 0), id='same-fingerprint-overlap'),
    pytest.param([(A, 0), (B, 12)], {A: 1, B: 1}, (0, 0), id='rotation-after-brief-absence'),
    pytest.param([(A, 0), (B, 40)], {A: 1, B: 1}, (0, 1), id='rotation-beyond-window'),
    pytest.param([(A, 0), (B, 3)], {A: 1, B: 2}, (1, 0), id='indistinguishable-sequential-devices'),
    pytest.param([(A, 0), (B, .1), (C, 4)], {A: 1, B: 2, C: 1}, (0, 1), id='competing-predecessors'),
    pytest.param([(A, 0), (B, 4), (C, 4.1)], {A: 1, B: 1, C: 2}, (0, 1), id='competing-successors'),
])
def test_synthetic_pair_errors(specs, labels, expected):
    report = infer(*(capture(*spec) for spec in specs))
    assert pair_errors(report, labels) == expected
    assert report['raw_mac_count'] == len(specs)
    baseline = infer(*(capture(*spec) for spec in specs), enabled=False)
    assert baseline['mode'] == 'mac-only'
    assert baseline['inferred_cluster_count'] == baseline['raw_mac_count']
    assert pair_errors(baseline, labels) == (0, sum(labels[a] == labels[b] for a, b in combinations(labels, 2)))


def test_match_keeps_the_first_cluster_id_and_reports_evidence():
    prefix = infer(capture(A, 0))
    report = infer(capture(A, 0), capture(B, 3), capture(C, 6))
    cluster, = report['clusters']
    assert cluster['cluster_id'] == prefix['clusters'][0]['cluster_id']
    assert cluster['mac_aliases'] == [A, B, C]
    assert cluster['first_seen_s'] == 0 and cluster['last_seen_s'] == 6.4
    assert cluster['confidence']['kind'] == 'uncalibrated_heuristic'
    assert cluster['fingerprint_profile'][B]['signature'].startswith('1:8')
    assert cluster['rssi_statistics'][B][6]['probes'] == 3
    event = decisions(report)[C]
    assert event['decision'] == 'MATCH'
    pairs = event['candidates'][0]['pairs']
    assert [pair['mac_alias'] for pair in pairs] == [A, B]
    assert all(pair['evidence']['ie_similarity']['score'] == 1 for pair in pairs)


def test_overlap_is_strong_conflict_and_competing_candidates_are_ambiguous():
    report = infer(capture(A, 0), capture(B, .1), capture(C, 4))
    events = decisions(report)
    assert events[B]['decision'] == 'NON_MATCH'
    assert events[B]['candidates'][0]['pairs'][0]['reason'] == 'overlapping_mac_activity'
    assert events[C]['decision'] == 'AMBIGUOUS' and events[C]['reason'] == 'competing_candidates'
    assert all(candidate['decision'] == 'MATCH' for candidate in events[C]['candidates'])
    report = infer(capture(A, 0), capture(B, 4), capture(C, 4.1))
    events = decisions(report)
    assert events[B]['competing_successor']['mac'] == C
    assert events[C]['competing_successor']['mac'] == B


def test_pairwise_chain_does_not_override_weaker_link():
    first = list(capture(A, 0, (-45, -45, -45)))
    middle = list(capture(B, 2, (-51, -51, -51)))
    last = list(capture(C, 4, (-57, -57, -57)))
    assert decisions(infer(middle, last))[C]['decision'] == 'MATCH'
    combined = infer(first, middle, last)
    assert combined['clusters'][0]['mac_aliases'] == [A, B]
    event = decisions(combined)[C]
    assert event['decision'] == 'AMBIGUOUS'
    assert [pair['decision'] for pair in event['candidates'][0]['pairs']] == ['AMBIGUOUS', 'MATCH']


def test_ie_similarity_allows_reordered_profile_and_rejects_incompatible_ie():
    first = list(capture(A, 0))
    reordered = '45:26,1:8,50:4,127:8,221:6'
    report = infer(first, capture(B, 4, ie=reordered))
    assert decisions(report)[B]['decision'] == 'MATCH'
    pair, = decisions(report)[B]['candidates'][0]['pairs']
    assert pair['evidence']['ie_similarity']['score'] == pytest.approx(.94)
    report = infer(first, capture(B, 4, ie='1:4,50:8,3:1,127:10'))
    pair, = decisions(report)[B]['candidates'][0]['pairs']
    assert pair['decision'] == 'NON_MATCH' and pair['reason'] == 'incompatible_ie'


@pytest.mark.parametrize('fields,reason', [
    ({'rssis': (-40, -75, -50)}, 'unstable_or_different_rssi'),
    ({'ie': ''}, 'insufficient_stable_ie'),
    ({'ie': '221:6,221:6,221:6,221:6'}, 'insufficient_stable_ie'),
    ({'channel': 11}, 'no_comparable_channel_rssi'),
])
def test_insufficient_evidence_keeps_aliases_separate(fields, reason):
    report = infer(capture(A, 0), capture(B, 4, **fields))
    event = decisions(report)[B]
    assert event['decision'] == 'AMBIGUOUS'
    assert event['candidates'][0]['pairs'][0]['reason'] == reason
    assert report['inferred_cluster_count'] == 2


def test_does_not_associate_across_capture_boundaries():
    controls = [(1, dict(type='control', kind='serial_disconnected'))]
    report = infer(capture(A, 0), controls, capture(B, 4))
    assert report['inferred_cluster_count'] == 2
    assert decisions(report)[B]['decision'] == 'AMBIGUOUS'
    reboot = infer(capture(A, 0), capture(B, 4, boot='new-boot'))
    assert reboot['inferred_cluster_count'] == 2


def test_cli_out_of_order_preserves_overlap_and_ignores_duplicates_and_labels(tmp_path):
    first = list(capture(A, 0))
    second = list(capture(B, .1))
    rows = [first[0], *second, *first[1:], second[0]]
    raw = tmp_path / 'raw.jsonl'
    raw.write_text(''.join(json.dumps(dict(host_elapsed_s=t, packet=p)) + '\n' for t, p in rows))
    # A deliberately wrong label file must have no effect on the CLI.
    (tmp_path / 'truth.jsonl').write_text('incorrect label data')
    output = tmp_path / 'report.json'
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'enabled': True, 'min_probes': 3}))
    command = [sys.executable, '-m', 'research.device_clustering', str(raw), '--config', str(config)]
    root = Path(__file__).resolve().parents[1]
    subprocess.run([*command, '--output', str(output)], check=True, cwd=root)
    report = json.loads(output.read_text())
    assert report['raw_mac_count'] == report['inferred_cluster_count'] == 2
    event = decisions(report)[B]
    assert event['candidates'][0]['pairs'][0]['evidence']['overlap_s'] == .3
    assert report['clusters'][1]['rssi_statistics'][B]['6']['probes'] == 3
    baseline = json.loads(subprocess.check_output([*command, '--mac-only'], cwd=root))
    assert baseline['mode'] == 'mac-only' and baseline['inferred_cluster_count'] == 2
