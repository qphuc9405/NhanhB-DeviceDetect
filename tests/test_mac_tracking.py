import json
import sys

import pytest

from backend.app import main
from research.detectors import ProbeConfig
from research.evaluate import load_records
from research.ie_fingerprint import main as fingerprint_cli
from research.stream import RecentProbeRecords, Stream


MAC_A = '02:00:00:00:00:ab'
MAC_B = '02:00:00:00:00:01'


def probe(seq, mac=MAC_A, **fields):
    packet = dict(v=1, type='probe', node='sniffer', boot_id='boot', seq=seq,
                  ts_us=seq * 1_000, source_mac=mac, channel=6, rssi=-60,
                  frame_seq=9, retry=False, ie='0:3,1:4')
    return {**packet, **fields}


def test_repeated_mac_updates_fields_and_identical_fingerprint_keeps_macs_separate():
    stream = Stream(ProbeConfig(rssi_min=-45))
    stream.feed(probe(1), 1)
    stream.feed(probe(2, mac=MAC_A.upper(), channel=11, rssi=-72), 2)
    stream.feed(probe(3, mac=MAC_B, ie='0:9,1:4'), 3)
    stream.feed(probe(4, ie=''), 4)

    snapshot = stream.snapshot(4)
    assert snapshot['raw_mac_count'] == snapshot['active_mac_count'] == 2
    assert snapshot['expired_mac_count'] == 0
    rows = {row['mac']: row for row in snapshot['recent_sources']}
    assert rows[MAC_A]['fingerprint_id'] == rows[MAC_B]['fingerprint_id'] == '1:4'
    assert rows[MAC_B]['probe_count'] == 1
    row = stream.diagnostics(MAC_A, 4)
    assert (row['first_seen_s'], row['last_seen_s'], row['channel'], row['rssi_last']) == (1, 4, 6, -60)
    assert row['probe_count'] == row['received'] == 3
    assert row['rssi_history'] == [-60, -72, -60]
    assert row['channels'] == [6, 11]
    assert stream.snapshot(4)['result'] is None


def test_duplicate_record_does_not_refresh_expired_mac_and_new_capture_can_return():
    stream = Stream(ProbeConfig(mac_expiry_s=2))
    first = probe(1)
    stream.feed(first, 0)
    stream.feed(first.copy(), 1.5)
    assert stream.diagnostics(MAC_A, 2)['last_seen_s'] == 0
    stream.feed(first.copy(), 2.5)
    snapshot = stream.snapshot(2.5)
    assert (snapshot['raw_mac_count'], snapshot['active_mac_count'], snapshot['expired_mac_count']) == (1, 0, 1)
    assert snapshot['quality']['duplicate_probe_records'] == 2
    assert snapshot['recent_sources'] == [] and snapshot['result'] is None
    assert not stream.audit
    assert stream.diagnostics(MAC_A, 2.5)['observed'] is False

    stream.feed(probe(2, retry=True), 3)
    result = stream.diagnostics(MAC_A, 3)
    assert result['first_seen_s'] == result['last_seen_s'] == 3
    assert result['probe_count'] == 1
    assert stream.snapshot(3)['expired_mac_count'] == 1


def test_cache_and_rssi_history_have_fixed_limits():
    stream = Stream(ProbeConfig())
    stream.probe_records = RecentProbeRecords(limit=3)
    stream.feed(probe(0, mac=MAC_B), 0)
    for seq in range(1, 21):
        stream.feed(probe(seq, rssi=-seq), seq)
    assert len(stream.probe_records.records) == 3
    snapshot = stream.snapshot(20)
    assert snapshot['raw_mac_count'] == 1
    assert snapshot['active_mac_count'] == 2
    row = stream.diagnostics(MAC_A, 20)
    assert row['probe_count'] == 20
    assert row['rssi_history'] == list(range(-5, -21, -1))


def test_delayed_wrapped_probe_keeps_capture_timestamp_and_invalid_clocks_are_rejected(tmp_path):
    base = probe(1, ts_us=4_000)
    late = probe(2, ts_us=1_000, rssi=-75)
    log = tmp_path / 'capture.jsonl'
    wrapped = [(4, base), (3, late), (5, late), (-1, probe(3)),
               ('NaN', probe(4)), (True, probe(5)), (6, probe(6, ts_us=-1)),
               (7, probe(7, ie='0:4'))]
    log.write_text(''.join(json.dumps(dict(host_elapsed_s=t, packet=p)) + '\n' for t, p in wrapped))

    records = list(load_records(log))
    assert [(t, p['ts_us']) for t, p in records] == [(4, 4_000), (4, 1_000), (5, 1_000), (7, 7_000)]
    assert [t for t, _ in load_records(log, deduplicate_probes=True)] == [4, 4, 7]
    stream = Stream(ProbeConfig())
    for t, packet in records:
        stream.feed(packet, t)
    with pytest.raises(ValueError, match='invalid stream clock'):
        stream.feed(probe(8), float('nan'))
    result = stream.diagnostics(MAC_A, 7)
    assert result['probe_count'] == 3
    assert result['fingerprint_id'] == '1:4'
    assert result['recent'][1]['ts_us'] == 1_000


def test_state_and_diagnostics_expose_mac_tracking(client):
    packet = json.dumps(probe(1))
    main.svc.ingest(packet)
    main.svc.ingest(packet)
    state = client.get('/api/probe/state').json()
    assert not state['valid'] and state['result'] is None
    assert (state['raw_mac_count'], state['active_mac_count'], state['expired_mac_count']) == (1, 1, 0)
    assert state['quality']['duplicate_probe_records'] == 1
    diagnostic = client.get('/api/probe/diagnostics', params={'mac': MAC_A}).json()
    assert diagnostic['probe_count'] == 1 and diagnostic['rssi_last'] == -60


def test_fingerprint_cli_counts_distinct_captures_including_rf_retry(tmp_path, monkeypatch):
    first = probe(1)
    radio_retry = probe(2, retry=True, rssi=-77)
    raw = tmp_path / 'uart.jsonl'
    raw.write_text(''.join(json.dumps(packet) + '\n' for packet in (first, first, radio_retry)))
    result = tmp_path / 'fingerprints.json'
    monkeypatch.setattr(sys, 'argv', ['ie_fingerprint', str(raw), '--json', str(result)])

    fingerprint_cli()

    group, = json.loads(result.read_text())
    assert (group['fingerprint'], group['macs'], group['probes']) == ('1:4', 1, 2)
