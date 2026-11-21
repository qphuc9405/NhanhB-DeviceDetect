"""Package recorded Probe sessions and evaluate three methods on a fixed replay grid."""

import argparse
from bisect import bisect_left
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from hashlib import file_digest, sha256
from itertools import combinations
import json
import math
from pathlib import Path
import re
import shutil
from statistics import mean, median

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.protocol import mac_valid
from research.dashboard import MAX_CLUSTER_ALIASES, MAX_RECORDS, RETENTION_S
from research.detectors import ProbeConfig
from research.device_clustering import ClusteringConfig, cluster_devices
from research.evaluate import load_records
from research.ie_profile import fingerprint
from research.in_room import InRoomConfig, RoomCalibration, estimate_room
from research.presence import PresenceConfig
from research.stream import Stream


METHODS = ('A_mac_only', 'B_ie_clustering', 'C_cluster_presence_room')
STATIC = {f'room_{count}': count for count in (0, 1, 2, 3, 5)}
SCENARIOS = (*STATIC, 'entry_exit', 'hallway', 'mac_rotation', 'quiet_probe', 'calibration')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}')


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    step_s: float = Field(default=1, ge=.25, le=60)
    probe: ProbeConfig = Field(default_factory=ProbeConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    presence: PresenceConfig = Field(default_factory=PresenceConfig)
    location: InRoomConfig = Field(default_factory=InRoomConfig)
    calibration: RoomCalibration | None = None

    @model_validator(mode='after')
    def check_windows(self):
        if max(self.probe.unique_window_s, self.presence.observation_window_s,
               self.presence.departure_timeout_s, self.location.window_s) > RETENTION_S:
            raise ValueError(f'evaluation windows must fit within {RETENTION_S} seconds')
        return self


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def digest(path):
    with path.open('rb') as source:
        return file_digest(source, 'sha256').hexdigest()


def identifier(value, field):
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f'invalid {field}: use 1–80 ASCII letters, digits, dots, underscores or hyphens')
    return value


def capture_info(folder):
    metadata = read_json(folder / 'metadata.json')
    synthetic = metadata.get('synthetic')
    if type(synthetic) is not bool or not metadata.get('ended_at'):
        raise ValueError('capture needs explicit synthetic=true/false and ended_at in metadata.json')
    time = metadata.get('started_at')
    if synthetic and time == 'SYNTHETIC':
        time = '1970-01-01T00:00:00Z'
    if not isinstance(time, str):
        raise ValueError('capture needs a start timestamp')
    started_at = datetime.fromisoformat(time)
    if started_at.tzinfo is None:
        raise ValueError('capture timestamp needs a UTC offset')
    if not synthetic:
        with (folder / 'raw.jsonl').open() as source:
            for line in source:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get('source') == 'synthetic':
                    raise ValueError('raw data declares synthetic origin but metadata says real')
    return metadata, started_at.astimezone(timezone.utc)


def load_truth(path, end, scenario):
    truth = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        t, count = row['t_s'], row['device_count']
        if type(t) not in (float, int) or not math.isfinite(t) or not 0 <= t <= end:
            raise ValueError('truth timestamp must be within the recorded session')
        if type(count) is not int or not 0 <= count <= 200:
            raise ValueError('device_count must be an integer between 0 and 200')
        if truth and t <= truth[-1]['t_s']:
            raise ValueError('truth timestamps must strictly increase')
        truth.append(dict(t_s=t, device_count=count))
    if not truth or truth[0]['t_s'] != 0:
        raise ValueError('ground truth must start at t_s=0')
    if scenario in STATIC and any(row['device_count'] != STATIC[scenario] for row in truth):
        raise ValueError(f'ground truth count does not match scenario {scenario}')
    return truth


def load_alias_truth(path):
    if not path.exists():
        return None
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError('alias truth must be an object mapping full MAC to anonymous device ID')
    aliases = {}
    for mac, device in raw.items():
        if not mac_valid(mac) or mac.lower() in aliases:
            raise ValueError('invalid or duplicate MAC in alias truth')
        aliases[mac.lower()] = identifier(device, 'anonymous device ID')
    return aliases


def package_capture(source, root, *, test_id, batch_id, scenario, aliases=None, setup_id=None, truth_path=None):
    test_id = identifier(test_id, 'test ID')
    batch_id = identifier(batch_id, 'batch ID')
    if scenario not in SCENARIOS:
        raise ValueError('unsupported scenario')
    metadata, started_at = capture_info(source)
    raw_path = source / 'raw.jsonl'
    last = max((t for t, _ in load_records(raw_path)), default=0.)
    if last <= 0:
        raise ValueError('need a nonempty capture with positive recorded duration')
    truth_path = truth_path if truth_path is not None else source / 'truth.jsonl'
    load_truth(truth_path, last, scenario)
    alias_truth = load_alias_truth(aliases) if aliases is not None else None
    if aliases is not None and alias_truth is None:
        raise ValueError('alias truth file does not exist')
    recorded_setup = metadata.get('dashboard_setup_id')
    if recorded_setup is not None and setup_id is not None and recorded_setup != setup_id:
        raise ValueError('setup ID disagrees with the saved capture metadata')
    manifest = dict(test_id=test_id, batch_id=batch_id, scenario=scenario, synthetic=metadata['synthetic'],
                    source_session_id=identifier(metadata.get('id'), 'source session ID'),
                    started_at=started_at.isoformat(), duration_s=last, setup_id=setup_id or recorded_setup,
                    raw_sha256=digest(raw_path), truth_sha256=digest(truth_path))
    destination = root / test_id
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    for name in ('metadata.json', 'raw.jsonl'):
        shutil.copyfile(source / name, destination / name)
    shutil.copyfile(truth_path, destination / 'truth.jsonl')
    if alias_truth is not None:
        write_json(destination / 'alias_truth.json', alias_truth)
        manifest['alias_truth_sha256'] = digest(destination / 'alias_truth.json')
    manifest['metadata_sha256'] = digest(destination / 'metadata.json')
    write_json(destination / 'experiment.json', manifest)
    return destination


def validate_split(root, split, config_hash, config, allow_synthetic):
    if split.get('config_sha256') != config_hash:
        raise ValueError('configuration SHA-256 does not match the frozen split')
    manifests = {}
    partitions = {}
    for partition in ('development', 'test'):
        names = split.get(partition)
        if not isinstance(names, list) or not names:
            raise ValueError('development and test must be nonempty ID lists')
        partitions[partition] = []
        for name in names:
            identifier(name, 'test ID')
            if name in manifests:
                raise ValueError('test IDs must be unique and disjoint across partitions')
            folder = root / name
            manifest = read_json(folder / 'experiment.json')
            metadata, _ = capture_info(folder)
            if (manifest.get('test_id') != name or manifest.get('scenario') not in SCENARIOS
                    or manifest.get('synthetic') is not metadata['synthetic']
                    or manifest.get('source_session_id') != metadata['id']):
                raise ValueError('experiment manifest disagrees with capture metadata')
            identifier(manifest.get('batch_id'), 'batch ID')
            for filename, key in (('raw.jsonl', 'raw_sha256'), ('truth.jsonl', 'truth_sha256'),
                                  ('metadata.json', 'metadata_sha256'), ('alias_truth.json', 'alias_truth_sha256')):
                path = folder / filename
                if (filename != 'alias_truth.json' or key in manifest or path.exists()) and digest(path) != manifest.get(key):
                    raise ValueError(f'frozen input was modified in {name}: {filename}')
            if any(old['raw_sha256'] == manifest['raw_sha256'] or
                   old['source_session_id'] == manifest['source_session_id'] for old in manifests.values()):
                raise ValueError('the same capture was included more than once')
            manifests[name] = manifest
            partitions[partition].append(manifest)
    if {row['batch_id'] for row in partitions['development']} & {row['batch_id'] for row in partitions['test']}:
        raise ValueError('capture batches must be disjoint across development and test')
    kinds = {row['synthetic'] for row in manifests.values()}
    if len(kinds) != 1 or (True in kinds and not allow_synthetic):
        raise ValueError('keep real and synthetic datasets separate and enable synthetic explicitly')
    if not config.clustering.enabled:
        raise ValueError('methods B and C require clustering.enabled=true')
    if config.calibration is not None:
        development = {row['test_id']: row for row in partitions['development']}
        previous_by_capture = {}
        for sample in sorted(config.calibration.samples, key=lambda row: (row.session_id, row.window_end_s)):
            entry = development.get(sample.session_id)
            if (entry is None or entry['setup_id'] != config.calibration.setup_id
                    or not config.calibration.window_s <= sample.window_end_s <= entry['duration_s']):
                raise ValueError('calibration samples must name development test IDs with matching setup')
            previous = previous_by_capture.get(sample.session_id)
            if previous is not None and sample.window_end_s - previous < config.calibration.window_s:
                raise ValueError('calibration windows must not overlap within one capture')
            previous_by_capture[sample.session_id] = sample.window_end_s
    return partitions


def cluster_map(clustering):
    return {mac: row['cluster_id'] for row in clustering['clusters'] for mac in row['mac_aliases']}


def replay_rows(records, truth, manifest, config, config_hash):
    probe_cfg = config.probe
    cluster_cfg = config.clustering.model_copy(update={'rssi_min': probe_cfg.rssi_min})
    presence_cfg = config.presence.model_copy(update={'heartbeat_timeout_s': probe_cfg.heartbeat_s})
    stream = Stream(probe_cfg)
    excluded = set(probe_cfg.excluded_macs)
    recent = deque(maxlen=MAX_RECORDS)
    overflow_at = None
    next_record = truth_index = 0
    start = datetime.fromisoformat(manifest['started_at'])
    end = records[-1][0]
    for index in range(math.ceil(end / config.step_s)):
        t = index * config.step_s
        if t >= end:
            break
        while next_record < len(records) and records[next_record][0] <= t:
            stamp, packet = records[next_record]
            stream.feed(packet, stamp)
            if packet['type'] == 'status':
                excluded.add(packet['own_mac'])
            if packet.get('source_mac') not in excluded:
                if len(recent) == MAX_RECORDS:
                    overflow_at = recent[0][0]
                recent.append((stamp, packet))
            next_record += 1
        while recent and recent[0][0] < t - RETENTION_S:
            recent.popleft()
        while truth_index + 1 < len(truth) and truth[truth_index + 1]['t_s'] <= t:
            truth_index += 1
        state = stream.snapshot(t)
        row = dict(test_id=manifest['test_id'], timestamp_utc=(start + timedelta(seconds=t)).isoformat(),
                   t_s=t, synthetic=manifest['synthetic'], scenario=manifest['scenario'], config_sha256=config_hash,
                   ground_truth_device_count=truth[truth_index]['device_count'],
                   capture_valid=state['valid'], capacity_limited=False,
                   **dict.fromkeys((*METHODS, 'raw_mac_count', 'fingerprint_count', 'cluster_count',
                                    'confirmed_count', 'estimated_in_room_count', 'location_unknown_count')))
        if state['valid']:
            active = {mac for mac, item in stream.engine.rows.items()
                      if mac not in excluded and t - item['last'] <= probe_cfg.unique_window_s}
            row['raw_mac_count'] = state['raw_mac_count']
            row[METHODS[0]] = len(active)
            row['fingerprint_count'] = len({signature for stamp, packet in recent
                                           if t - stamp <= probe_cfg.unique_window_s and packet.get('source_mac') in active
                                           and packet['rssi'] >= probe_cfg.rssi_min
                                           and (signature := fingerprint(packet.get('ie')))})
            eligible = {packet['source_mac'] for _, packet in recent if packet['type'] == 'probe'
                        and packet['rssi'] >= probe_cfg.rssi_min}
            if (overflow_at is not None and overflow_at >= t - RETENTION_S) or len(eligible) > MAX_CLUSTER_ALIASES:
                row['capacity_limited'] = True
            else:
                prefix = [(stamp, packet) for stamp, packet in recent if packet.get('source_mac') not in excluded]
                clustering = cluster_devices(prefix, cluster_cfg)
                aliases = cluster_map(clustering)
                row['cluster_count'] = row[METHODS[1]] = len({aliases[mac] for mac in active if mac in aliases})
                room = estimate_room(prefix, clustering, presence_cfg, config.location, source_clock=t,
                                     setup_id=manifest['setup_id'], calibration=config.calibration)
                if room['observation_valid']:
                    row['confirmed_count'] = room['confirmed_count']
                    row['location_unknown_count'] = room['location_unknown_count']
                    if (room['calibration_status'] == 'ready' and not room['location_unknown_count']
                            and room['continuous_coverage_s'] >= config.location.window_s):
                        row['estimated_in_room_count'] = row[METHODS[2]] = room['estimated_in_room_count']
        yield row


def count_metrics(rows, method):
    errors = [row[method] - row['ground_truth_device_count'] for row in rows if row[method] is not None]
    count = len(errors)
    return dict(samples=len(rows), available=count, coverage=count / len(rows) if rows else None,
                mae=mean(map(abs, errors)) if count else None,
                rmse=math.sqrt(mean(error**2 for error in errors)) if count else None,
                overcount_rate=sum(error > 0 for error in errors) / count if count else None,
                undercount_rate=sum(error < 0 for error in errors) / count if count else None)


def event_delays(rows, truth, method, end):
    times = [row['t_s'] for row in rows]
    for i, (before, target) in enumerate(zip(truth, truth[1:]), 1):
        old, new, stamp = before['device_count'], target['device_count'], target['t_s']
        if old == new:
            continue
        arrival = new > old
        stop = next((row['t_s'] for row in truth[i+1:] if row['device_count'] != new), end)
        first = bisect_left(times, stamp)
        prior = rows[first-1][method] if first else None
        reached = lambda value: value >= new if arrival else value <= new
        delay = None
        status = 'pre_event_unavailable' if prior is None else 'preexisting_target' if reached(prior) else 'not_detected'
        if status == 'not_detected':
            for row in rows[first:bisect_left(times, stop)]:
                value = row[method]
                if value is None:
                    status = 'coverage_gap'
                    break
                if reached(value):
                    delay, status = row['t_s'] - stamp, 'detected'
                    break
        yield dict(method=method, event_t_s=stamp, direction='arrival' if arrival else 'departure',
                   old_count=old, target_count=new, followup_s=stop-stamp, delay_s=delay, status=status)


def delay_metrics(events, method, direction):
    selected = [event for event in events if event['method'] == method and event['direction'] == direction]
    delays = [event['delay_s'] for event in selected if event['delay_s'] is not None]
    return dict(events=len(selected), detected=len(delays), statuses=dict(Counter(event['status'] for event in selected)),
                mean_delay_s=mean(delays) if delays else None, median_delay_s=median(delays) if delays else None)


def identity_metrics(labels, assignments):
    if labels is None or assignments is None:
        return None
    observed = sorted(set(labels) & assignments.keys())
    same, different, merged, split = 0, 0, 0, 0
    for first, second in combinations(observed, 2):
        same_truth = labels[first] == labels[second]
        same_cluster = assignments[first] == assignments[second]
        same += same_truth
        different += not same_truth
        merged += not same_truth and same_cluster
        split += same_truth and not same_cluster
    return dict(labelled_aliases=len(labels), observed_labelled_aliases=len(observed),
                same_device_pairs=same, different_device_pairs=different, over_merge_pairs=merged, over_split_pairs=split,
                over_merge_rate=merged / different if different else None, over_split_rate=split / same if same else None)


def session_identity(folder, records, config, *, max_aliases=MAX_CLUSTER_ALIASES):
    labels = load_alias_truth(folder / 'alias_truth.json')
    if labels is None:
        return dict.fromkeys(METHODS)
    excluded = set(config.probe.excluded_macs) | {p['own_mac'] for _, p in records if p['type'] == 'status'}
    filtered = [(t, p) for t, p in records if p.get('source_mac') not in excluded]
    eligible = {p['source_mac'] for _, p in filtered
                if p['type'] == 'probe' and p['rssi'] >= config.probe.rssi_min}
    assigned = None
    if len(eligible) <= max_aliases:
        cfg = config.clustering.model_copy(update={'rssi_min': config.probe.rssi_min})
        assigned = cluster_map(cluster_devices(filtered, cfg))
    return {METHODS[0]: identity_metrics(labels, {mac: mac for mac in eligible}),
            METHODS[1]: identity_metrics(labels, assigned), METHODS[2]: identity_metrics(labels, assigned)}


def summarize(rows, events, identities):
    common = [row for row in rows if all(row[method] is not None for method in METHODS)]
    return {method: dict(available_case=count_metrics(rows, method), common_case=count_metrics(common, method),
                         arrival_delay=delay_metrics(events, method, 'arrival'),
                         departure_delay=delay_metrics(events, method, 'departure'), identity=identities[method])
            for method in METHODS}


def pooled_identity(sessions):
    counts = ('labelled_aliases', 'observed_labelled_aliases', 'same_device_pairs', 'different_device_pairs',
              'over_merge_pairs', 'over_split_pairs')
    result = {}
    for method in METHODS:
        scored = [session['methods'][method]['identity'] for session in sessions
                  if session['methods'][method]['identity'] is not None]
        if not scored:
            result[method] = None
            continue
        total = {key: sum(row[key] for row in scored) for key in counts}
        for error, denominator in [('merge', 'different_device_pairs'), ('split', 'same_device_pairs')]:
            total[f'over_{error}_rate'] = total[f'over_{error}_pairs'] / total[denominator] if total[denominator] else None
        result[method] = total
    return result


def recorded_provenance(folder, records):
    metadata = read_json(folder / 'metadata.json')
    probe_config = dict(metadata.get('config', {}))
    excluded_count = len(probe_config.pop('excluded_macs', []))
    status = [packet for _, packet in records if packet['type'] == 'status']
    return dict(probe_config=probe_config, excluded_mac_count=excluded_count,
                scan_modes=sorted({packet['scan_mode'] for packet in status}),
                status_channels=sorted({packet['channel'] for packet in status}),
                observed_sniffers=len({packet['own_mac'] for packet in status}),
                status_count=len(status), probe_records=sum(packet['type'] == 'probe' for _, packet in records))


def evaluate_suite(root, split_path, config_path, output, *, phase, allow_synthetic=False):
    from research.experiment_report import export_outputs

    config_bytes = config_path.read_bytes()
    config = EvaluationConfig.model_validate_json(config_bytes)
    config_hash = sha256(config_bytes).hexdigest()
    partitions = validate_split(root, read_json(split_path), config_hash, config, allow_synthetic)
    sessions, rows, events = [], [], []
    for manifest in partitions[phase]:
        folder = root / manifest['test_id']
        raw = folder / 'raw.jsonl'
        records = list(load_records(raw))
        if not records or records[-1][0] <= 0:
            raise ValueError(f'no full observation window in {manifest["test_id"]}')
        end = records[-1][0]
        if end != manifest['duration_s']:
            raise ValueError(f'recorded duration disagrees with manifest in {manifest["test_id"]}')
        truth = load_truth(folder / 'truth.jsonl', end, manifest['scenario'])
        measured = list(replay_rows(records, truth, manifest, config, config_hash))
        delays = [dict(test_id=manifest['test_id'], synthetic=manifest['synthetic'], **event)
                  for method in METHODS for event in event_delays(measured, truth, method, end)]
        with raw.open() as source:
            skipped = sum(bool(line.strip()) for line in source) - len(records)
        sessions.append(dict(test_id=manifest['test_id'], scenario=manifest['scenario'], started_at=manifest['started_at'],
                             raw_sha256=manifest['raw_sha256'], truth_sha256=manifest['truth_sha256'],
                             duration_s=end, parsed_records=len(records), skipped_records=skipped,
                             recorded=recorded_provenance(folder, records),
                             methods=summarize(measured, delays, session_identity(folder, records, config))))
        rows.extend(measured)
        events.extend(delays)
    safe_config = config.model_dump(exclude={'calibration': {'samples', 'sniffer_mac'}, 'probe': {'excluded_macs'}})
    safe_config['excluded_mac_count'] = len(config.probe.excluded_macs)
    safe_config['reference_window_count'] = len(config.calibration.samples) if config.calibration else 0
    report = dict(version='pbl3-physical-device-evaluation-v1', phase=phase, synthetic=partitions[phase][0]['synthetic'],
                  config_sha256=config_hash, config=safe_config, split_sha256=digest(split_path),
                  partitions={key: [row['test_id'] for row in value] for key, value in partitions.items()},
                  sessions=sessions, pooled=summarize(rows, events, pooled_identity(sessions)))
    export_outputs(output, report, rows, events, METHODS)
    return report


def make_synthetic_suite(root):
    from scripts.probe_fixture import generate

    root.mkdir(parents=True, exist_ok=False)
    archive = root / 'captures'
    for phase, rssi_shift in [('development', 0), ('test', -2)]:
        source = root / f'seed-{phase}'
        generate(source)
        meta = read_json(source / 'metadata.json')
        meta['id'] = 'synthetic-' + phase
        write_json(source / 'metadata.json', meta)
        path = source / 'raw.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        for row in rows:
            packet = row['packet']
            packet['boot_id'] = 'synthetic-' + phase
            if packet['type'] == 'probe':
                packet['rssi'] += rssi_shift
                packet['ie'] = '1:8,50:4,45:26,127:8,221:6'
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        package_capture(source, archive, test_id=phase, batch_id='fixture-' + phase, scenario='entry_exit')
    config = root / 'evaluation.json'
    write_json(config, {'step_s': 1, 'probe': {'unique_window_s': 12}})
    write_json(root / 'split.json', {'development': ['development'], 'test': ['test'], 'config_sha256': digest(config)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    package = commands.add_parser('package', help='đóng gói phiên đã kết thúc cùng nhãn và checksum')
    package.add_argument('--session', type=Path, required=True)
    package.add_argument('--root', type=Path, required=True)
    package.add_argument('--test-id', required=True)
    package.add_argument('--batch-id', required=True)
    package.add_argument('--scenario', choices=SCENARIOS, required=True)
    package.add_argument('--alias-truth', type=Path)
    package.add_argument('--truth', type=Path, help='nhãn timeline JSONL do người quan sát ghi')
    package.add_argument('--setup-id')
    replay = commands.add_parser('replay', help='phát lại offline và xuất đánh giá A/B/C')
    replay.add_argument('--root', type=Path, required=True)
    replay.add_argument('--split', type=Path, required=True)
    replay.add_argument('--config', type=Path, required=True)
    replay.add_argument('--phase', choices=('development', 'test'), required=True)
    replay.add_argument('--output', type=Path, required=True)
    replay.add_argument('--allow-synthetic', action='store_true')
    demo = commands.add_parser('synthetic', help='tạo bộ dữ liệu mô phỏng để kiểm tra công cụ')
    demo.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'package':
            destination = package_capture(args.session, args.root, test_id=args.test_id, batch_id=args.batch_id,
                                          scenario=args.scenario, aliases=args.alias_truth, setup_id=args.setup_id,
                                          truth_path=args.truth)
            print(destination)
        elif args.command == 'synthetic':
            make_synthetic_suite(args.output)
            print(args.output)
        else:
            report = evaluate_suite(args.root, args.split, args.config, args.output,
                                    phase=args.phase, allow_synthetic=args.allow_synthetic)
            kind = 'SYNTHETIC' if report['synthetic'] else 'RF capture'
            print(f"{kind} · {report['phase']} · {len(report['sessions'])} sessions · {args.output}")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
