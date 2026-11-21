"""Replay recorded Probe sessions to diagnose count gaps and compare estimators."""

import argparse
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timedelta
from hashlib import sha256
from math import ceil
from pathlib import Path
from statistics import mean, median

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research.cluster_counting import CLUSTER_METHODS, ClusterReplay, EvidenceConfig
from research.dashboard import MAX_CLUSTER_ALIASES
from research.detectors import ProbeConfig
from research.evaluate import load_records
from research.experiment import (
    EvaluationConfig, capture_info, count_metrics, delay_metrics, digest, event_delays,
    identifier, load_truth, read_json, session_identity, validate_split, write_json,
)
from research.stream import Stream


BASELINES = ('rssi_timeout', 'sherlock_mac')
METHODS = (*BASELINES, *CLUSTER_METHODS)


class SherlockTiming(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

    slot_s: float = Field(ge=1, le=300)
    arrival_slots: int = Field(ge=1, le=30)
    withdrawal_slots: int = Field(ge=1, le=30)
    departure_slots: int = Field(ge=1, le=30)


class CountingConfig(EvaluationConfig):
    step_s: float = Field(default=1, ge=.25, le=5)
    methods: tuple[str, ...] = BASELINES
    sherlock_variants: dict[str, SherlockTiming] = Field(default_factory=dict, max_length=12)
    evidence: EvidenceConfig = Field(default_factory=EvidenceConfig)
    max_cluster_aliases: int = Field(default=MAX_CLUSTER_ALIASES, ge=1, le=512)

    @field_validator('methods')
    @classmethod
    def check_methods(cls, methods):
        if not methods or len(methods) != len(set(methods)) or set(methods) - set(METHODS):
            raise ValueError(f'methods must be a unique selection from {METHODS}')
        return methods

    @field_validator('sherlock_variants')
    @classmethod
    def check_variant_names(cls, variants):
        for name in variants:
            identifier(name, 'variant name')
        return variants

    def variant_configs(self):
        return {f'sherlock_mac__{name}': self.probe.model_copy(update=timing.model_dump())
                for name, timing in self.sherlock_variants.items()}

    def selected_methods(self):
        return (*self.methods, *self.variant_configs())

    def export_config(self):
        return self.model_dump(exclude={'calibration': {'samples', 'sniffer_mac'}, 'probe': {'excluded_macs'}})


class ProbeAudit:
    """Aggregate capture intervals and eligibility without exporting MAC addresses."""

    def __init__(self):
        self.last = {}
        self.received = Counter()
        self.per_source = Counter()
        self.channels = Counter()
        self.modes = set()
        self.host_gaps = []
        self.capture_gaps = []
        self.gap_opportunity = Counter()
        self.counter_increase = Counter()
        self.last_status = None
        self.events = Counter()
        self.event_sequence = 0

    def take_events(self, stream):
        for event in stream.events:
            if event['event_seq'] <= self.event_sequence:
                continue
            kind = event['kind']
            if kind == 'inference_reset':
                kind = event['reason']
                self.last.clear()
            self.events[kind] += 1
            self.event_sequence = event['event_seq']

    def feed(self, t, packet, reason, stream):
        self.take_events(stream)
        if packet['type'] == 'status':
            self.modes.add(packet['scan_mode'])
            status = (packet['boot_id'], packet['probe_dropped'], packet['serial_errors'])
            if self.last_status and self.last_status[0] == status[0]:
                for key, current, previous in zip(
                    ('probe_dropped', 'serial_errors'), status[1:], self.last_status[1:]
                ):
                    self.counter_increase[key] += max(0, current - previous)
            self.last_status = status
        if packet['type'] != 'probe':
            return
        self.received[reason or 'unclassified'] += 1
        if reason != 'accepted':
            return
        mac, channel, captured = packet['source_mac'], packet['channel'], packet['ts_us']
        self.channels[channel] += 1
        self.per_source[mac] += 1
        if previous := self.last.get(mac):
            last_t, last_us, last_channel, last_exposure = previous
            self.host_gaps.append(t - last_t)
            if captured >= last_us:
                self.capture_gaps.append((captured - last_us) / 1_000_000)
            exposed = stream.channel_seconds.get(last_channel, 0) - last_exposure
            self.gap_opportunity['gaps'] += 1
            self.gap_opportunity['no_tuned_time_on_previous_channel'] += exposed <= 1e-9
            self.gap_opportunity['next_probe_on_different_channel'] += last_channel != channel
        self.last[mac] = (t, captured, channel, stream.channel_seconds.get(channel, 0))

    def report(self, stream):
        def stats(values):
            ordered = sorted(values)
            return dict(n=len(ordered), median=median(ordered) if ordered else None,
                        p90=ordered[ceil(len(ordered) * .9) - 1] if ordered else None,
                        max=ordered[-1] if ordered else None)

        return dict(probe_disposition=dict(self.received), scan_modes=sorted(self.modes),
                    accepted_probes_per_mac=stats(list(self.per_source.values())),
                    accepted_mac_count=len(self.per_source),
                    single_probe_macs=sum(count == 1 for count in self.per_source.values()),
                    accepted_probes_by_channel=dict(self.channels),
                    tuned_seconds_by_channel={key: round(value, 3) for key, value in stream.channel_seconds.items()},
                    host_inter_probe_gap_s=stats(self.host_gaps),
                    radio_inter_probe_gap_s=stats(self.capture_gaps),
                    gap_channel_opportunity=dict(self.gap_opportunity),
                    counter_increase={key: self.counter_increase[key] for key in ('probe_dropped', 'serial_errors')},
                    stream_events=dict(self.events))


def timeout_gap(engine, t):
    """Explain timeout-positive MACs which are absent from Sherlock's count."""
    result = Counter()
    sherlock = engine.sherlock
    for mac, recent in engine.rows.items():
        if not recent['confirmed'] or t - recent['last'] > engine.cfg.timeout_s:
            continue
        track = sherlock.tracks.get(mac)
        if track and track.state != 'candidate':
            result['also_sherlock'] += 1
        elif track:
            result['candidate_waiting_for_more_positive_slots'] += 1
        elif mac in sherlock.seen:
            result['first_or_returning_hit_in_open_slot'] += 1
        else:
            result['no_current_sherlock_track'] += 1
    return result


def replay_capture(records, config, *, setup_id=None):
    """Predict from the packet prefix and configuration, with no label input."""
    stream = Stream(config.probe)
    variants = {name: Stream(cfg) for name, cfg in config.variant_configs().items()}
    clusters = ClusterReplay(config, setup_id) if set(config.methods) & set(CLUSTER_METHODS) else None
    audit = ProbeAudit()
    index = 0
    end = records[-1][0]
    rows = []
    for sample in range(ceil(end / config.step_s)):
        t = sample * config.step_s
        while index < len(records) and records[index][0] <= t:
            stamp, packet = records[index]
            engine = stream.engine
            reason = stream.feed(packet, stamp)
            audit.feed(stamp, packet, reason, stream)
            if clusters is not None:
                clusters.feed(stamp, packet, reason, reset=engine is not stream.engine)
            for variant in variants.values():
                variant.feed(packet, stamp)
            index += 1

        state = stream.snapshot(t)
        audit.take_events(stream)
        metrics = state['result']
        row = dict(t_s=t, capture_valid=state['valid'], mac_in_window=None)
        row.update(dict.fromkeys(config.selected_methods()))
        gap = timeout_gap(stream.engine, t) if metrics is not None else {}
        for category in ('also_sherlock', 'candidate_waiting_for_more_positive_slots',
                         'first_or_returning_hit_in_open_slot', 'no_current_sherlock_track'):
            row[f'timeout_{category}'] = gap.get(category, 0) if metrics is not None else None
        if metrics is not None:
            row['mac_in_window'] = metrics['unique_count']
            if 'rssi_timeout' in config.methods:
                row['rssi_timeout'] = metrics['timeout_count']
            if 'sherlock_mac' in config.methods:
                row['sherlock_mac'] = metrics['sherlock']['count']
        for name, variant in variants.items():
            result = variant.snapshot(t)['result']
            row[name] = result['sherlock']['count'] if result is not None else None
        if clusters is not None:
            row.update(clusters.snapshot(t, state['valid']))
        rows.append(row)

    # Include the last packet and trailing coverage in capture diagnostics only.
    for stamp, packet in records[index:]:
        reason = stream.feed(packet, stamp)
        audit.feed(stamp, packet, reason, stream)
    audit.take_events(stream)
    return rows, audit.report(stream)


def score(rows, method):
    result = count_metrics(rows, method)
    known = [(row['ground_truth_device_count'], row[method]) for row in rows if row[method] is not None]
    errors = [predicted - actual for actual, predicted in known]
    empty = sum(actual == 0 for actual, _ in known)
    occupied = len(known) - empty
    false_positives = sum(actual == 0 and predicted > 0 for actual, predicted in known)
    false_negatives = sum(actual > 0 and predicted == 0 for actual, predicted in known)
    return dict(**result, excess_count_units=sum(max(0, value) for value in errors) if errors else None,
                missed_count_units=sum(max(0, -value) for value in errors) if errors else None,
                empty_room_samples=empty, occupied_room_samples=occupied,
                false_positive_samples=false_positives, false_negative_samples=false_negatives,
                false_positive_rate=false_positives / empty if empty else None,
                false_negative_rate=false_negatives / occupied if occupied else None)


def pass_labels(rows, truth, manifest):
    times = [label['t_s'] for label in truth]
    start = datetime.fromisoformat(manifest['started_at'])
    return [dict(test_id=manifest['test_id'], synthetic=manifest['synthetic'],
                 timestamp_utc=(start + timedelta(seconds=row['t_s'])).isoformat(),
                 ground_truth_device_count=truth[bisect_right(times, row['t_s']) - 1]['device_count'], **row)
            for row in rows]


def compare_pair(rows, method, baseline):
    common = [row for row in rows if row[method] is not None and row[baseline] is not None]
    errors = [(abs(row[method] - row['ground_truth_device_count']),
               abs(row[baseline] - row['ground_truth_device_count'])) for row in common]
    unavailable = sum(row[method] is None and row[baseline] is not None for row in rows)
    return dict(common_samples=len(common), method_unavailable_with_baseline=unavailable,
                method_worse=sum(a > b for a, b in errors),
                method_better=sum(a < b for a, b in errors),
                mae_difference=mean(a - b for a, b in errors) if errors else None)


def score_session(rows, events, methods):
    return {name: dict(**score(rows, name),
                       arrival_delay=delay_metrics(events, name, 'arrival'),
                       departure_delay=delay_metrics(events, name, 'departure'))
            for name in methods}


def evaluate_suite(root, split, config_path, output, *, phase, allow_synthetic=False):
    from research.counting_report import export

    config_bytes = config_path.read_bytes()
    config = CountingConfig.model_validate_json(config_bytes)
    config_hash = sha256(config_bytes).hexdigest()
    partitions = validate_split(root, read_json(split), config_hash, config, allow_synthetic)
    methods = config.selected_methods()
    sessions, rows, events = [], [], []
    for manifest in partitions[phase]:
        test_id = manifest['test_id']
        folder = root / test_id
        raw = folder / 'raw.jsonl'
        records = list(load_records(raw))
        if not records or records[-1][0] <= 0 or records[-1][0] != manifest['duration_s']:
            raise ValueError(f'invalid recorded duration in {test_id}')
        predictions, audit = replay_capture(records, config, setup_id=manifest['setup_id'])
        truth = load_truth(folder / 'truth.jsonl', records[-1][0], manifest['scenario'])
        measured = pass_labels(predictions, truth, manifest)
        delays = [dict(test_id=test_id, **event) for method in methods
                  for event in event_delays(measured, truth, method, records[-1][0])]
        with raw.open() as source:
            skipped = sum(bool(line.strip()) for line in source) - len(records)
        identity = (session_identity(folder, records, config, max_aliases=config.max_cluster_aliases)
                    if set(methods) & set(CLUSTER_METHODS) else None)
        sessions.append(dict(test_id=test_id, scenario=manifest['scenario'], duration_s=records[-1][0],
                             raw_sha256=manifest['raw_sha256'], truth_sha256=manifest['truth_sha256'],
                             parsed_records=len(records), skipped_records=skipped, audit=audit, identity=identity,
                             methods=score_session(measured, delays, methods)))
        rows.extend(measured)
        events.extend(delays)

    comparisons = []
    for session in sessions:
        selected = [row for row in rows if row['test_id'] == session['test_id']]
        for method in set(methods) - set(BASELINES):
            for baseline in BASELINES:
                if baseline in methods:
                    comparisons.append(dict(test_id=session['test_id'], scenario=session['scenario'],
                                            method=method, baseline=baseline,
                                            **compare_pair(selected, method, baseline)))
    comparisons.sort(key=lambda row: (row['test_id'], row['method'], row['baseline']))
    report = dict(version='pbl3-counting-research-v1', phase=phase, synthetic=partitions[phase][0]['synthetic'],
                  config_sha256=config_hash, config=config.export_config(),
                  split_sha256=digest(split), methods=methods,
                  partitions={key: [row['test_id'] for row in value] for key, value in partitions.items()},
                  sessions=sessions, pooled=score_session(rows, events, methods), comparisons=comparisons)
    export(output, report, rows, events)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    diagnose = commands.add_parser('diagnose', help='replay one stopped capture without using truth')
    diagnose.add_argument('--session', type=Path, required=True)
    diagnose.add_argument('--config', type=Path)
    compare = commands.add_parser('compare', help='score methods on one frozen dataset partition')
    compare.add_argument('--root', type=Path, required=True)
    compare.add_argument('--split', type=Path, required=True)
    compare.add_argument('--config', type=Path, required=True)
    compare.add_argument('--phase', choices=('development', 'test'), required=True)
    for command in (diagnose, compare):
        command.add_argument('--output', type=Path, required=True)
        command.add_argument('--allow-synthetic', action='store_true')
    args = parser.parse_args()

    try:
        if args.command == 'diagnose':
            from research.experiment_report import write_csv

            metadata, started_at = capture_info(args.session)
            if metadata['synthetic'] and not args.allow_synthetic:
                raise ValueError('synthetic capture requires --allow-synthetic')
            config = (CountingConfig.model_validate_json(args.config.read_bytes()) if args.config
                      else CountingConfig(probe=ProbeConfig.model_validate(metadata['config'])))
            raw = args.session / 'raw.jsonl'
            records = list(load_records(raw))
            if not records or records[-1][0] <= 0:
                raise ValueError('capture needs positive recorded duration')
            rows, audit = replay_capture(records, config, setup_id=metadata.get('dashboard_setup_id'))
            args.output.mkdir(parents=True, exist_ok=False)
            write_csv(args.output / 'timeline.csv', tuple(rows[0]), rows)
            write_json(args.output / 'diagnostics.json', dict(synthetic=metadata['synthetic'],
                       raw_sha256=digest(raw), started_at=started_at.isoformat(),
                       duration_s=records[-1][0], config=config.export_config(), **audit))
        else:
            evaluate_suite(args.root, args.split, args.config, args.output,
                           phase=args.phase, allow_synthetic=args.allow_synthetic)
        print(args.output)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
