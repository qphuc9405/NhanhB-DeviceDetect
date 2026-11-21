"""CSV, Markdown and Matplotlib figures for the physical-device evaluation."""

import csv
import json
import math

import matplotlib

matplotlib.use('Agg')
from matplotlib import pyplot as plt


EVENT_FIELDS = ('test_id', 'synthetic', 'method', 'event_t_s', 'direction', 'old_count',
                'target_count', 'followup_s', 'delay_s', 'status')
SUMMARY_FIELDS = ('test_id', 'synthetic', 'phase', 'slice', 'method', 'samples', 'available', 'coverage',
                  'mae', 'rmse', 'overcount_rate', 'undercount_rate', 'arrival_events', 'arrival_detected',
                  'arrival_median_delay_s', 'departure_events', 'departure_detected', 'departure_median_delay_s',
                  'labelled_aliases', 'observed_labelled_aliases', 'over_merge_pairs', 'over_split_pairs',
                  'over_merge_rate', 'over_split_rate')


def write_csv(path, fields, rows):
    with path.open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


def summaries(report, methods):
    for test_id, scored in [*((session['test_id'], session['methods']) for session in report['sessions']),
                            ('POOLED', report['pooled'])]:
        for method in methods:
            score = scored[method]
            for section in ('available_case', 'common_case'):
                row = dict(test_id=test_id, synthetic=report['synthetic'], phase=report['phase'],
                           slice=section, method=method, **score[section])
                if section == 'available_case':
                    for direction in ('arrival', 'departure'):
                        data = score[f'{direction}_delay']
                        for field in ('events', 'detected', 'median_delay_s'):
                            row[f'{direction}_{field}'] = data[field]
                    row.update({key: value for key, value in (score['identity'] or {}).items() if key in SUMMARY_FIELDS})
                yield row


def title(report):
    return 'SYNTHETIC — kiểm tra công cụ, không phải đo RF' if report['synthetic'] else 'RF — phiên thu có nhãn'


def markdown_table(report, methods):
    def fmt(value):
        return 'N/A' if value is None else f'{value:.3f}'

    lines = [f'# {title(report)}', '', f"Phân vùng: `{report['phase']}`. Số phiên: {len(report['sessions'])}.", '']
    for section, name in (('available_case', 'Mốc có kết quả theo từng phương pháp'),
                          ('common_case', 'Mốc có kết quả ở cả ba phương pháp')):
        lines.extend([f'## {name}', '',
                      '| Phương pháp | Mốc có kết quả / tổng | MAE | RMSE | Overcount | Undercount |',
                      '|---|---:|---:|---:|---:|---:|'])
        for method in methods:
            metric = report['pooled'][method][section]
            values = ' | '.join(fmt(metric[key]) for key in ('mae', 'rmse', 'overcount_rate', 'undercount_rate'))
            lines.append(f"| `{method}` | {metric['available']}/{metric['samples']} | {values} |")
        lines.append('')
    lines.extend(['## Sự kiện và nhãn alias', '',
                  '| Phương pháp | Vào phát hiện / tổng | Median vào (s) | Ra phát hiện / tổng | Median ra (s) | Over-merge / over-split (cặp) |',
                  '|---|---:|---:|---:|---:|---:|'])
    for method in methods:
        data = report['pooled'][method]
        arrival, departure, identities = data['arrival_delay'], data['departure_delay'], data['identity']
        pairs = 'N/A' if identities is None else f"{identities['over_merge_pairs']} / {identities['over_split_pairs']}"
        lines.append(f"| `{method}` | {arrival['detected']}/{arrival['events']} | {fmt(arrival['median_delay_s'])} | "
                     f"{departure['detected']}/{departure['events']} | {fmt(departure['median_delay_s'])} | {pairs} |")
    lines.append('')
    return '\n'.join(lines)


def save_figure(figure, path):
    figure.savefig(path, metadata={'Date': None})
    plt.close(figure)


def plots(output, report, rows, methods):
    names = ('A · MAC-only', 'B · IE + Cluster', 'C · Presence + Room')
    colors = ('#637085', '#26775f', '#a95031')
    with plt.rc_context({'svg.hashsalt': 'pbl3-physical-device-evaluation-v1', 'axes.spines.top': False,
                         'axes.spines.right': False, 'font.size': 10}):
        for session in report['sessions']:
            test_id = session['test_id']
            samples = [row for row in rows if row['test_id'] == test_id]
            times = [row['t_s'] for row in samples]
            fig, axis = plt.subplots(figsize=(9, 3.8), layout='constrained')
            axis.step(times, [row['ground_truth_device_count'] for row in samples], where='post',
                      color='#20272b', linewidth=2.5, linestyle='--', label='Ground truth')
            for method, name, color in zip(methods, names, colors):
                values = [math.nan if row[method] is None else row[method] for row in samples]
                available = any(math.isfinite(value) for value in values)
                axis.step(times, values, where='post', color=color, label=name if available else name + ' (N/A)')
            axis.set(title=f'{title(report)} · {test_id}', xlabel='Thời gian phiên (s)', ylabel='Số đếm')
            axis.grid(axis='y', alpha=.25)
            axis.legend(ncols=2, fontsize=9)
            save_figure(fig, output / f'timeline-{test_id}.svg')

        fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), layout='constrained')
        fig.suptitle(title(report))
        metrics = [report['pooled'][method]['available_case'] for method in methods]
        for index, metric in enumerate(metrics):
            if metric['mae'] is None:
                axes[0].text(index, 0, 'N/A', ha='center', va='bottom')
            else:
                axes[0].bar(index, metric['mae'], color=colors[index])
            axes[1].bar(index, 100 * (metric['coverage'] or 0), color=colors[index])
        axes[0].set(ylabel='MAE (thiết bị)', ylim=(0, max(1, *(item['mae'] or 0 for item in metrics)) * 1.12))
        axes[1].set(ylabel='Mốc có kết quả (%)', ylim=(0, 105))
        for axis in axes:
            axis.set(xticks=range(3), xticklabels=('A', 'B', 'C'), xlim=(-.55, 2.55))
            axis.grid(axis='y', alpha=.25)
        save_figure(fig, output / 'overview.svg')


def export_outputs(output, report, rows, events, methods):
    output.mkdir(parents=True, exist_ok=False)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    write_csv(output / 'timeline.csv', tuple(rows[0]), rows)
    write_csv(output / 'events.csv', EVENT_FIELDS, events)
    write_csv(output / 'summary.csv', SUMMARY_FIELDS, summaries(report, methods))
    (output / 'summary.md').write_text(markdown_table(report, methods))
    plots(output, report, rows, methods)
