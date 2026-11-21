"""Kiểm kê và so sánh cấu trúc IE quan sát được trong Probe Request."""
import argparse,json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

from research.ie_profile import IE_NAMES, VERSION, fingerprint, parse_ie, similarity

BURST_GAP_US=500_000  # bài báo: khung cách nhau < 0,5 s thuộc cùng một đợt quét

def burst_rate(frames):
    """Độ dốc SEQ theo thời gian (khung/giây) trong một đợt; None nếu < 3 khung. SEQ quay vòng ở 4096."""
    if len(frames)<3:return None
    seq=[frames[0]['frame_seq']]
    for f in frames[1:]:seq.append(seq[-1]+(f['frame_seq']-seq[-1])%4096)
    xs=[(f['ts_us']-frames[0]['ts_us'])/1e6 for f in frames];mx=sum(xs)/len(xs);my=sum(seq)/len(seq)
    den=sum((x-mx)**2 for x in xs)
    return None if den==0 else sum((x-mx)*(y-my) for x,y in zip(xs,seq))/den

def bursts(frames):
    out=[]
    for f in frames:
        if out and f['ts_us']-out[-1][-1]['ts_us']<BURST_GAP_US:out[-1].append(f)
        else:out.append([f])
    return out

def analyze(probes, rssi_min=-127):
    by_source = defaultdict(list)
    profiles = {}
    inventory = defaultdict(Counter)
    probe_presence = Counter()
    quality = Counter(dict.fromkeys(('usable', 'missing', 'no_usable_ie', 'malformed'), 0))
    issues = Counter()
    profiled_macs = set()
    possibly_truncated = 0

    for packet in probes:
        profile = parse_ie(packet.get('ie'))
        quality[profile.status] += 1
        issues.update(profile.issues)
        possibly_truncated += profile.possibly_truncated
        if profile.status != 'malformed':
            observed = [*profile.elements, *((element_id, None) for element_id in profile.excluded_ids)]
            probe_presence.update({element_id for element_id, _ in observed})
            for element_id, length in observed:
                inventory[element_id][length] += 1
        if profile.status == 'usable' and packet['rssi'] >= rssi_min:
            signature = profile.signature
            mac = packet['source_mac'].lower()
            profiles.setdefault(signature, profile)
            profiled_macs.add(mac)
            by_source[packet['boot_id'], mac].append((packet, signature))

    groups = defaultdict(lambda: dict(macs=set(), probes=0, rssi_max=-127, bursts=0, rates=[], gaps_ms=[]))
    for (_, mac), entries in by_source.items():
        # The wire sequence resolves capture-time ties. Boot clocks stay separate.
        entries.sort(key=lambda entry: (entry[0]['ts_us'], entry[0]['seq']))
        for burst in bursts([dict(packet, signature=signature) for packet, signature in entries]):
            variants = defaultdict(list)
            for packet in burst:
                variants[packet['signature']].append(packet)
            for signature, frames in variants.items():
                bucket = groups[signature]
                bucket['macs'].add(mac)
                bucket['probes'] += len(frames)
                bucket['bursts'] += 1
                bucket['rssi_max'] = max(bucket['rssi_max'], *(frame['rssi'] for frame in frames))
                rate = burst_rate(frames)
                if rate is not None:
                    bucket['rates'].append(rate)
                if len(frames) > 1:
                    gap = (frames[-1]['ts_us'] - frames[0]['ts_us']) / 1e3 / (len(frames) - 1)
                    bucket['gaps_ms'].append(gap)

    rows = [
        dict(fingerprint=signature, fingerprint_hash=profiles[signature].fingerprint_hash,
             fingerprint_version=VERSION, macs=len(bucket['macs']), probes=bucket['probes'],
             bursts=bucket['bursts'], rssi_max=bucket['rssi_max'],
             median_rate=median(bucket['rates']) if bucket['rates'] else None,
             median_gap_ms=median(bucket['gaps_ms']) if bucket['gaps_ms'] else None)
        for signature, bucket in sorted(groups.items(), key=lambda item: (-len(item[1]['macs']), item[0]))
    ]
    return dict(version=VERSION, rssi_min=rssi_min, groups=rows, distinct_profiled_macs=len(profiled_macs),
                probes_by_status=dict(quality), issues=dict(sorted(issues.items())),
                possibly_truncated_probes=possibly_truncated,
                inventory=[dict(id=element_id, name=IE_NAMES.get(element_id), probes=probe_presence[element_id],
                                occurrences=sum(lengths.values()),
                                lengths={} if None in lengths else dict(sorted(lengths.items())))
                           for element_id, lengths in sorted(inventory.items())])


def group(probes, rssi_min=-127):
    return analyze(probes, rssi_min)['groups']

def main():
    from research.evaluate import load_records

    ap=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('raw', nargs='?', help='raw.jsonl của một phiên hoặc JSONL thô từ serial')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--describe-ie', metavar='IE', help='mô tả dãy mã:độ dài')
    mode.add_argument('--compare-ie', nargs=2, metavar=('LEFT', 'RIGHT'), help='so sánh hai dãy mã:độ dài')
    ap.add_argument('--rssi-min',type=int,default=-127,help='bỏ Probe yếu hơn ngưỡng này (dBm)')
    ap.add_argument('--json',help='ghi kết quả ra file JSON')
    ap.add_argument('--report', help='ghi báo cáo JSON với kiểm kê IE và chất lượng dữ liệu')
    a=ap.parse_args()
    if a.describe_ie is not None or a.compare_ie is not None:
        if a.raw or a.json or a.report:
            ap.error('--describe-ie và --compare-ie nhận dãy IE trực tiếp')
        if a.describe_ie is not None:
            result = parse_ie(a.describe_ie).describe()
        else:
            left, right = map(parse_ie, a.compare_ie)
            result = dict(left=left.describe(), right=right.describe(), similarity=similarity(left, right))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if not a.raw:
        ap.error('cần file JSONL, --describe-ie hoặc --compare-ie')
    report = analyze((p for _,p in load_records(Path(a.raw), deduplicate_probes=True) if p['type']=='probe'), a.rssi_min)
    rows = report['groups']
    print(f"{'MAC':>4} {'goi':>5} {'dot':>4} {'RSSI':>5} {'SEQ/s':>6} {'ms/khung':>8}  cau truc IE chuan hoa")
    for r in rows:
        rate='-' if r['median_rate'] is None else f"{r['median_rate']:.0f}"
        gap='-' if r['median_gap_ms'] is None else f"{r['median_gap_ms']:.0f}"
        print(f"{r['macs']:4d} {r['probes']:5d} {r['bursts']:4d} {r['rssi_max']:5d} {rate:>6} {gap:>8}  {r['fingerprint']}")
    print(f"\n{len(rows)} nhom cau truc IE, {report['distinct_profiled_macs']} MAC phan biet trong cac nhom.")
    if a.json:Path(a.json).write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    if a.report:Path(a.report).write_text(json.dumps(report, ensure_ascii=False, indent=2))

if __name__=='__main__':main()
