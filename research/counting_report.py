"""Exports for the offline PBL3 counting comparison."""

from collections import defaultdict
from math import nan
from statistics import mean

from research.cluster_counting import WINDOWS
from research.experiment import write_json
from research.experiment_report import save_figure, write_csv
from matplotlib import pyplot as plt


def window_rows(rows, report):
    """Use complete 30 s and 60 s bins and retain the sample coverage of each method."""
    durations = {session['test_id']: session['duration_s'] for session in report['sessions']}
    bins = defaultdict(list)
    for row in rows:
        for width in WINDOWS:
            start = int(row['t_s'] // width) * width
            if start + width <= durations[row['test_id']]:
                bins[row['test_id'], width, start].append(row)
    for (test_id, width, start), samples in sorted(bins.items()):
        row = dict(test_id=test_id, synthetic=report['synthetic'], window_s=width,
                   start_s=start, end_s=start + width, samples=len(samples))
        for name in ('ground_truth_device_count', *report['methods']):
            known = [sample[name] for sample in samples if sample[name] is not None]
            row[f'{name}_mean'] = mean(known) if known else None
            row[f'{name}_available'] = len(known)
        yield row


def export(output, report, rows, events):
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'report.json', report)
    write_csv(output / 'timeline.csv', tuple(rows[0]), rows)
    write_csv(output / 'event-delays.csv',
              ('test_id', 'method', 'event_t_s', 'direction', 'old_count',
               'target_count', 'followup_s', 'delay_s', 'status'), events)
    write_csv(output / 'comparisons.csv',
              ('test_id', 'scenario', 'method', 'baseline', 'common_samples',
               'method_unavailable_with_baseline', 'method_worse', 'method_better', 'mae_difference'),
              report['comparisons'])
    windows = list(window_rows(rows, report))
    fields = ('test_id', 'synthetic', 'window_s', 'start_s', 'end_s', 'samples')
    fields += tuple(f'{name}_{metric}' for name in ('ground_truth_device_count', *report['methods'])
                    for metric in ('mean', 'available'))
    write_csv(output / 'windows.csv', fields, windows)

    source = 'SYNTHETIC · kiểm thử công cụ' if report['synthetic'] else 'RF · phiên thực tế có nhãn'
    labels = {'rssi_timeout': 'RSSI + timeout', 'sherlock_mac': 'Sherlock / MAC',
              'sherlock_cluster': 'Sherlock / cluster',
              'proposed_30s': 'Proposed · cụm quan sát 30 s',
              'proposed_60s': 'Proposed · cụm quan sát 60 s',
              'proposed_room_30s': 'Proposed · trong phòng 30 s',
              'proposed_room_60s': 'Proposed · trong phòng 60 s'}
    for session in report['sessions']:
        test_id = session['test_id']
        samples = [row for row in rows if row['test_id'] == test_id]
        times = [row['t_s'] for row in samples]
        fig, axis = plt.subplots(figsize=(10, 4), layout='constrained')
        axis.step(times, [row['ground_truth_device_count'] for row in samples], where='post',
                  label='Ground truth', color='black', linestyle='--', linewidth=2)
        for name in report['methods']:
            values = [row[name] if row[name] is not None else nan for row in samples]
            label = labels.get(name, name.replace('sherlock_mac__', 'Sherlock / MAC · '))
            if all(row[name] is None for row in samples):
                label += ' (N/A)'
            axis.step(times, values, where='post', label=label, alpha=.85)
        axis.set(title=f'{source} · {test_id}', xlabel='Thời gian (s)', ylabel='Số đếm')
        axis.grid(axis='y', alpha=.25)
        axis.legend(ncols=2, fontsize=8)
        save_figure(fig, output / f'timeline-{test_id}.svg')
