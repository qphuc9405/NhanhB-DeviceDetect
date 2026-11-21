import {useEffect, useState} from 'react';

const METRICS = {
  raw_mac_count: 'MAC quan sát', active_mac_count: 'MAC còn hiệu lực',
  inferred_cluster_count: 'Cụm suy luận', candidate_count: 'Ứng viên',
  confirmed_count: 'Cụm đã xác nhận', stale_count: 'Cụm thiếu quan sát',
  estimated_in_room_count: 'Ước lượng trong phòng', location_unknown_count: 'Chưa rõ vị trí',
} as const;
type Metrics = Partial<Record<keyof typeof METRICS, number | null>>;
type Sample = Metrics & {t_s: number};
type Cluster = {
  cluster_id: string; mac_alias_count: number; fingerprint_summary: string[];
  rssi_statistics: {channel: number; median_dbm: number; max_spread_db: number; probes: number}[];
  first_seen_s: number; last_seen_s: number; heuristic_score: number | null;
  presence_state: string | null; location_state: string | null; location_reason: string | null;
  association_history: {alias_number: number; decision: string | null; reason: string; heuristic_score: number | null;
    candidates: {cluster_id: string; decision: string; heuristic_score: number | null; pair_reasons: string[]}[]}[];
  state_history: {t_s: number; from_state: string | null; to_state: string | null; reason: string}[];
};
type DashboardData = {
  source_id: string; source: 'LIVE' | 'REPLAY' | 'DEMO' | null; status: string; connection: string;
  t_s: number; calibration_status: string | null; location_ready?: boolean; truncated: boolean;
  metrics: Metrics; history: Sample[]; clusters: Cluster[];
};

const DISPLAY: Record<string, string> = {
  CANDIDATE: 'Ứng viên', CONFIRMED: 'Đã xác nhận', STALE: 'Thiếu quan sát', ABSENT: 'Hết hạn quan sát',
  in_room_confirmed: 'Ước lượng trong phòng', outside_likely: 'Có khả năng ở ngoài', location_unknown: 'UNKNOWN',
  complete_link_match: 'Đủ bằng chứng với mọi alias', competing_candidates: 'Có ứng viên cạnh tranh',
  all_candidates_conflict: 'Mâu thuẫn với các cụm ứng viên', insufficient_pair_evidence: 'Thiếu bằng chứng liên kết',
  no_candidate_in_handoff_window: 'Không có ứng viên trong khoảng chuyển MAC', mac_only: 'Đối chứng MAC-only',
  overlapping_mac_activity: 'Quan sát MAC chồng lấn', incompatible_ie: 'Cấu trúc IE khác biệt',
  ie_time_rssi_channel_agree: 'IE, thời gian, RSSI và kênh phù hợp', below_match_threshold: 'Dưới ngưỡng liên kết',
  first_probe: 'Nhận Probe đầu tiên', independent_observations_reached: 'Đủ quan sát độc lập',
  no_recent_probe: 'Thiếu Probe gần đây', observed_again: 'Quan sát lại', heartbeat_gap: 'Mất heartbeat',
  observation_timeout: 'Hết thời hạn quan sát', candidate_window_expired: 'Hết thời hạn ứng viên',
  observed_after_timeout: 'Quan sát lại sau timeout', retention_expired: 'Thu hồi trạng thái đã hết hạn',
  missing_calibration: 'Chưa có dữ liệu tham chiếu vị trí',
  insufficient_calibration: 'Thiếu cửa sổ hoặc phiên tham chiếu vị trí',
  calibration_setup_mismatch: 'Cấu hình thu không khớp dữ liệu tham chiếu',
  overlapping_location_evidence: 'Mẫu trong và ngoài phòng chồng lấn',
};

function label(value: string | null | undefined) {
  return value ? DISPLAY[value] ?? value.replaceAll('_', ' ') : 'N/A';
}

function displayCount(value: number | null | undefined, unknown = 'N/A') {
  return typeof value === 'number' && Number.isFinite(value) ? value : unknown;
}

const SERIES = [
  {key: 'confirmed_count', color: '#65778c', name: 'Cụm đã xác nhận'},
  {key: 'estimated_in_room_count', color: '#13775c', name: 'Ước lượng trong phòng'},
] as const;

function HistoryChart({samples, end, span}: {samples: Sample[]; end: number; span: number}) {
  const rows = samples.filter(row => row.t_s >= end - span && row.t_s <= end);
  const ceiling = Math.max(1, ...rows.flatMap(row => SERIES.map(({key}) => row[key] ?? 0)));
  const x = (time: number) => 44 + ((time - (end - span)) / span) * 540;
  const y = (value: number) => 145 - (value / ceiling) * 120;
  if (!rows.some(row => SERIES.some(({key}) => row[key] != null))) {
    return <p className="cluster-empty">Chưa có mẫu hợp lệ trong cửa sổ hiển thị.</p>;
  }
  return <>
    <svg className="cluster-chart" viewBox="0 0 600 180" role="img" aria-label={`Số cụm và ước lượng trong phòng trong ${span} giây`}>
      {[0, ceiling].map((value) => <g key={value}>
        <line x1="44" x2="584" y1={y(value)} y2={y(value)} stroke="#dce7e1"/>
        <text x="34" y={y(value)+4} textAnchor="end">{value}</text>
      </g>)}
      {SERIES.map(({key, color}) => <g key={key} fill={color} stroke={color}>
        {rows.map((row, index) => {
          const count = row[key], previous = rows[index-1];
          if (count == null) return null;
          const before = previous?.[key];
          return <g key={row.t_s}>
            {before != null && row.t_s - previous.t_s <= span / 2 &&
              <line x1={x(previous.t_s)} y1={y(before)} x2={x(row.t_s)} y2={y(count)} strokeWidth="2"/>}
            <circle cx={x(row.t_s)} cy={y(count)} r="3"><title>{`${count} · ${row.t_s.toFixed(1)} s`}</title></circle>
          </g>;
        })}
      </g>)}
      <text x="44" y="169">−{span} s</text><text x="584" y="169" textAnchor="end">0 s</text>
    </svg>
    <ul className="cluster-legend">{SERIES.map(({key, color, name}) => <li key={key}><i style={{background: color}}/>{name}</li>)}</ul>
  </>;
}

function ClusterHistory({cluster}: {cluster: Cluster}) {
  return <details className="cluster-details">
    <summary>Lý do và lịch sử</summary>
    <div><strong>Liên kết MAC</strong>
      <ul>{cluster.association_history.map(entry => <li key={entry.alias_number}>
        Alias {entry.alias_number} · {entry.decision ?? 'N/A'} · {label(entry.reason)}
        {entry.heuristic_score != null && ` · ${entry.heuristic_score.toFixed(2)}`}
        {entry.candidates.map(candidate => <div key={candidate.cluster_id}>
          {candidate.cluster_id} · {candidate.decision} · {candidate.pair_reasons.map(label).join(', ')}
        </div>)}
      </li>)}</ul>
      <strong>Trạng thái hiện diện</strong>
      {cluster.state_history.length ? <ul>{cluster.state_history.map((event, index) => <li key={index}>
        {event.t_s.toFixed(1)} s · {label(event.from_state)} → {label(event.to_state)} · {label(event.reason)}
      </li>)}</ul> : <p className="hint">Chưa có sự kiện trong cửa sổ phân tích.</p>}
      {cluster.location_reason && <p>{label(cluster.location_reason)}</p>}
    </div>
  </details>;
}

export default function DeviceOverview({sourceId, connection, valid, observe}: {
  sourceId: string | undefined; connection: string | undefined; valid: boolean; observe: boolean;
}) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [failed, setFailed] = useState(false);
  const [span, setSpan] = useState(30);
  useEffect(() => {
    if (!sourceId) return;
    const controller = new AbortController();
    let polling = false;
    async function poll() {
      if (polling) return;
      polling = true;
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]);
        const response = await fetch('/api/probe/dashboard', {signal, cache: 'no-store'});
        if (!response.ok) throw new Error('Dashboard API');
        const snapshot: DashboardData = await response.json();
        if (!controller.signal.aborted) {setData(snapshot); setFailed(false);}
      } catch {
        if (!controller.signal.aborted) {setData(null); setFailed(true);}
      } finally {polling = false;}
    }
    void poll();
    const timer = window.setInterval(poll, 1000);
    return () => {controller.abort(); window.clearInterval(timer);};
  }, [sourceId]);

  const snapshot = data && data.source_id === sourceId && data.connection === connection ? data : null;
  const available = Boolean(snapshot && (valid || (snapshot.status === 'finished' && snapshot.metrics.confirmed_count != null)));
  const metrics = available ? snapshot?.metrics : undefined;
  const clusters = available ? snapshot?.clusters ?? [] : [];
  const estimate = metrics?.estimated_in_room_count;
  let status = 'Đang đợi dữ liệu phân tích từ máy chủ.';
  if (failed || snapshot?.status === 'error') status = 'Không đọc được dữ liệu phân tích từ máy chủ hoặc nguồn thu báo lỗi.';
  else if (snapshot?.status === 'disconnected' || connection === 'reconnecting' || connection === 'disconnected') status = 'Nguồn thu đã ngắt hoặc đang kết nối lại.';
  else if (snapshot?.status === 'waiting') status = 'Đang chờ heartbeat và dữ liệu quan sát hợp lệ.';
  else if (snapshot?.status === 'finished' && !available) status = 'Phát lại đã kết thúc, chưa có ảnh chụp quan sát hợp lệ.';
  else if (snapshot?.status === 'limited') status = 'Vượt giới hạn phân tích số alias trong cửa sổ.';
  else if (snapshot?.status === 'empty') status = 'Nguồn thu hợp lệ, chưa quan sát cụm nào trong cửa sổ phân tích.';
  else if (snapshot?.source === 'DEMO') status = 'DEMO dùng dữ liệu mô phỏng.';
  else if (snapshot?.truncated) status = 'Bộ đệm bị cắt bớt. Chưa đủ dữ liệu để công bố số thiết bị trong phòng.';
  else if (available && estimate == null) status = snapshot?.calibration_status !== 'ready'
    ? label(snapshot?.calibration_status) : snapshot?.location_ready
      ? 'Còn cụm chưa rõ vị trí.' : 'Chưa đủ thời gian quan sát liên tục.';
  else if (available) status = snapshot?.status === 'finished' ? 'Ảnh chụp cuối của phiên phát lại.' : 'Ước lượng từ các cụm đã xác nhận.';
  if (!sourceId && !connection) status = 'Chưa có kết nối đến dữ liệu máy chủ.';

  return <>
    <section className="cluster-hero panel" aria-label="Ước lượng thiết bị trong phòng">
      <div className="cluster-primary">
        <h2>Estimated physical WiFi devices in room</h2>
        <div className="cluster-estimate" data-testid="room-estimate">{displayCount(estimate, 'UNKNOWN')}</div>
        <p className="hint" role="status">{status}</p>
      </div>
      <dl className="cluster-metrics">
        {Object.entries(METRICS).filter(([key]) => key !== 'estimated_in_room_count').map(([key, name]) =>
          <div key={key}><dt>{name}</dt><dd>{displayCount(metrics?.[key as keyof Metrics])}</dd></div>)}
      </dl>
    </section>
    {observe && <>
      <section className="panel cluster-history-panel">
        <div className="cluster-heading"><h3>Diễn biến theo thời gian</h3>
          <label>Cửa sổ biểu đồ<select value={span} onChange={event => setSpan(Number(event.target.value))}>
            {[15, 30, 60, 120].map(seconds => <option key={seconds} value={seconds}>{seconds} giây</option>)}
          </select></label>
        </div>
        <HistoryChart samples={snapshot?.history ?? []} end={snapshot?.t_s ?? 0} span={span}/>
      </section>
      <section className="panel cluster-table-panel">
        <h3>Device Cluster</h3>
        {clusters.length ? <div className="table-scroll" role="region" aria-label="Bảng Device Cluster" tabIndex={0}>
          <table><thead><tr><th>Cụm</th><th>MAC alias</th><th>Fingerprint</th><th>RSSI theo kênh</th>
            <th>Đầu / cuối</th><th>Heuristic</th><th>Hiện diện</th><th>Vị trí</th><th>Chi tiết</th></tr></thead>
            <tbody>{clusters.map(cluster => <tr key={cluster.cluster_id}>
              <th scope="row" className="mono">{cluster.cluster_id}</th><td>{cluster.mac_alias_count}</td>
              <td className="cluster-fingerprint">{cluster.fingerprint_summary.length ? cluster.fingerprint_summary.join(' · ') : 'N/A'}</td>
              <td>{cluster.rssi_statistics.length ? cluster.rssi_statistics.map(stat =>
                <div key={stat.channel}>K{stat.channel} · {stat.median_dbm} dBm <small>Δ {stat.max_spread_db} dB</small></div>) : 'N/A'}</td>
              <td>{cluster.first_seen_s.toFixed(1)} / {cluster.last_seen_s.toFixed(1)} s</td>
              <td>{cluster.heuristic_score?.toFixed(2) ?? 'N/A'}</td>
              <td>{label(cluster.presence_state)}</td><td>{label(cluster.location_state)}</td>
              <td><ClusterHistory cluster={cluster}/></td>
            </tr>)}</tbody></table>
        </div> : <p className="cluster-empty">{available ? 'Chưa có cụm để hiển thị.' : 'Chưa có dữ liệu cụm hợp lệ.'}</p>}
        <p className="hint">Hết hạn quan sát cho biết cụm thiếu Probe trong thời gian cấu hình.</p>
      </section>
    </>}
  </>;
}
