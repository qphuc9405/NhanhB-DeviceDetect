import json
import sys
import pytest
from backend.app.protocol import parse_line
from research.evaluate import load_records
from research.ie_fingerprint import analyze,fingerprint,burst_rate,group,main
from research.ie_profile import parse_ie, similarity

def probe(mac,ts_us,seq,ie,rssi=-30,boot='b'):
    return dict(v=1,type='probe',node='sniffer',boot_id=boot,ts_us=ts_us,seq=0,source_mac=mac,rssi=rssi,
                channel=6,frame_seq=seq,retry=False,ie=ie)

def test_fingerprint_drops_ssid_length():
    assert fingerprint('0:0,1:4,50:8') == fingerprint('0:11,1:4,50:8') == '1:4,50:8'

def test_burst_rate_handles_seq_wrap():
    frames=[probe('02:00:00:00:00:01',i*10_000,(4094+i)%4096,'1:4') for i in range(5)]
    assert burst_rate(frames) == pytest.approx(100)
    assert burst_rate(frames[:2]) is None

def test_two_macs_same_fingerprint_form_one_group():
    rows=group([probe('02:00:00:00:00:01',0,10,'0:0,1:4'),probe('02:00:00:00:00:01',20_000,11,'0:0,1:4'),
                probe('06:00:00:00:00:02',5_000_000,900,'0:9,1:4'),probe('0a:00:00:00:00:03',0,5,'1:8',rssi=-90)],rssi_min=-50)
    assert [(r['fingerprint'],r['macs'],r['bursts'],r['probes']) for r in rows] == [('1:4',2,2,3)]

def test_parser_keeps_ie_and_rejects_garbage():
    assert parse_line(json.dumps(probe('02:00:00:00:00:01',0,1,'0:0,1:4')))['ie'] == '0:0,1:4'
    legacy=probe('02:00:00:00:00:01',0,1,'');del legacy['ie']
    assert parse_line(json.dumps(legacy))['ie'] == ''
    with pytest.raises(ValueError):parse_line(json.dumps(probe('02:00:00:00:00:01',0,1,'0:0;rm')))

def test_raw_uart_fingerprint_keeps_probe_queued_before_channel_record(tmp_path,monkeypatch):
    first=probe('02:00:00:00:00:01',990_000,10,'0:3,1:4')
    second=probe('02:00:00:00:00:02',1_020_000,11,'0:9,1:4')
    channel=dict(v=1,type='channel',node='sniffer',boot_id='b',ts_us=1_000_000,seq=0,channel=6,dwell_ms=3000)
    raw=tmp_path/'uart.jsonl'
    raw.write_text(''.join(json.dumps(p)+'\n' for p in [channel,dict(first,seq=1),dict(second,seq=2)]))

    rows=list(load_records(raw))
    assert [t for t,_ in rows]==[0,0,.02]
    assert rows[1][1]['ts_us']==990_000
    output=tmp_path/'fingerprints.json'
    monkeypatch.setattr(sys,'argv',['ie_fingerprint',str(raw),'--json',str(output)])
    main()
    assert [(g['fingerprint'],g['macs'],g['probes']) for g in json.loads(output.read_text())]==[('1:4',2,2)]


def test_profile_is_reproducible_across_mac_and_private_ie_changes():
    first = probe('02:00:00:00:00:01', 0, 1, '0:5,001:008,50:4,45:26,127:8,221:6,84:7,255:9')
    second = probe('02:00:00:00:00:02', 1, 2, '0:0,1:8,50:4,45:26,127:8,221:6,84:33,255:21')
    left, right = [parse_ie(packet['ie']) for packet in (first, second)]
    expected = '1:8,50:4,45:26,127:8,221:6'
    assert left.signature == right.signature == expected
    assert left.fingerprint_hash == right.fingerprint_hash == (
        'b91e8bd8374a149dfaf221fcfd106c40b8ee60dd3b2584fb8431e54d122a7f07')
    assert left.describe()['excluded_ids'] == [0, 84, 255]
    assert similarity(left, right)['score'] == 1
    rows = group([first, second])
    assert len(rows) == 1 and rows[0]['macs'] == 2
    assert rows[0]['fingerprint_hash'] == left.fingerprint_hash
    assert first['source_mac'] not in json.dumps(rows)
    assert second['source_mac'] not in json.dumps(rows)


def test_similarity_explains_missing_changed_and_reordered_elements():
    base = parse_ie('1:8,45:26,127:8,221:6,221:6')
    missing = parse_ie('1:8,45:26,127:8,221:6')
    changed = parse_ie('1:8,45:26,127:8,221:7,221:6')
    reordered = parse_ie('45:26,1:8,127:8,221:6,221:6')

    assert base.describe()['duplicate_ids'] == [221]
    assert similarity(base, missing)['score'] == pytest.approx(.8)
    changed_result = similarity(base, changed)
    assert changed_result['composition_score'] == pytest.approx(4 / 6)
    assert changed_result['order_score'] == pytest.approx(4 / 5)
    assert changed_result['score'] == similarity(changed, base)['score']
    assert similarity(base, reordered)['composition_score'] == 1
    assert similarity(base, reordered)['score'] == pytest.approx(.94)
    assert similarity(base, parse_ie('50:4'))['score'] == 0
    assert base.fingerprint_hash != reordered.fingerprint_hash


@pytest.mark.parametrize('ie,status', [('', 'missing'), ('0:12,84:8,255:12', 'no_usable_ie'),
                                        ('1:8,221:', 'malformed'), ('999:5', 'malformed'),
                                        ('1:256', 'malformed'), ('1:4,' * 24 + '1:4', 'malformed')])
def test_unusable_profiles_have_no_hash_or_similarity(ie, status):
    profile = parse_ie(ie)
    assert profile.status == status
    assert profile.signature == '' and profile.fingerprint_hash is None
    assert similarity(profile, parse_ie('1:8'))['score'] is None


def test_report_preserves_burst_variants_and_counts_distinct_macs(tmp_path, monkeypatch):
    mac_a, mac_b = '02:00:00:00:00:01', '02:00:00:00:00:02'
    frames = [probe(mac_a, 0, 1, '1:8,45:26'), probe(mac_a, 1000, 2, '1:8,221:6,221:6'),
              probe(mac_b, 2000, 3, '0:12,1:8,45:26'), probe(mac_b, 3000, 4, ''),
              probe(mac_b, 4000, 5, '0:7'), probe(mac_b, 5000, 6, '221:999'),
              probe(mac_b, 6000, 7, ','.join(['50:4'] * 24), rssi=-95)]
    report = analyze(frames, rssi_min=-50)
    assert analyze(reversed(frames), rssi_min=-50) == report
    assert [(row['fingerprint'], row['macs'], row['probes']) for row in report['groups']] == [
        ('1:8,45:26', 2, 2), ('1:8,221:6,221:6', 1, 1)]
    assert report['distinct_profiled_macs'] == 2
    assert report['probes_by_status'] == dict(usable=4, missing=1, no_usable_ie=1, malformed=1)
    assert report['possibly_truncated_probes'] == 1
    inventory = {entry['id']: entry for entry in report['inventory']}
    assert inventory[0]['probes'] == 2 and inventory[0]['lengths'] == {}
    assert inventory[221]['probes'] == 1 and inventory[221]['lengths'] == {6: 2}
    assert inventory[50]['probes'] == 1 and inventory[50]['occurrences'] == 24

    raw, output = tmp_path / 'rf.jsonl', tmp_path / 'report.json'
    raw.write_text(''.join(json.dumps(frame) + '\n' for frame in frames))
    monkeypatch.setattr(sys, 'argv', ['ie_fingerprint', str(raw), '--rssi-min', '-50', '--report', str(output)])
    main()
    assert json.loads(output.read_text()) == json.loads(json.dumps(report))
