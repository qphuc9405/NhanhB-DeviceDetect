import React, {useEffect, useState} from 'react';

async function request(path:string,method='GET',body?:unknown){
  const r=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await r.json();if(!r.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;
}
function CountChart({rows}:{rows:any[]}){
  const max=Math.max(1,...rows.flatMap(r=>[r.unique,r.timeout,r.sherlock]));
  const first=rows[0]?.t??0,last=rows.at(-1)?.t??1;
  return <svg viewBox="0 0 800 210" role="img" aria-label="Số nguồn MAC theo thời gian, ba phương pháp">
    {[0,1,2,3].map(i=><g key={i}><line x1="40" x2="780" y1={170-i*50} y2={170-i*50} stroke="#dde5ed"/><text x="5" y={175-i*50} fontSize="12">{(max*i/3).toFixed(1)}</text></g>)}
    {(['unique','timeout','sherlock'] as const).map((key,i)=><polyline key={key} fill="none" stroke={['#94a3b8','#8b5cf6','#0d9488'][i]} strokeWidth="2" points={rows.map(r=>`${40+(r.t-first)/Math.max(1,last-first)*740},${170-r[key]/max*150}`).join(' ')}/>)}
    <text x="40" y="202" fontSize="12">{Math.max(0,last-first).toFixed(0)} giây gần đây · MAC thô / Timeout / Sherlock</text>
  </svg>
}
export default function ResearchPanel(){
  const [target,setTarget]=useState(''),[diag,setDiag]=useState<any>(null),[mark,setMark]=useState('ap_disconnect');
  const [s,setS]=useState<any>(null),[ports,setPorts]=useState<any[]>([]),[port,setPort]=useState('');
  const [cfg,setCfg]=useState<any>(null),[sessions,setSessions]=useState<any[]>([]),[replays,setReplays]=useState<any[]>([]);
  const [replay,setReplay]=useState('synthetic-probe-demo'),[speed,setSpeed]=useState(10),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [devices,setDevices]=useState('Điện thoại A: mẫu máy / hệ điều hành / trạng thái WiFi'),[layout,setLayout]=useState('Sniffer giữa phòng; ghi khoảng cách và vị trí'),[notes,setNotes]=useState('');
  const [count,setCount]=useState(0),[report,setReport]=useState<any>(null);
  async function refresh(){const [p,c,e,r]=await Promise.all([request('ports'),request('probe/config'),request('probe/sessions'),request('probe/replays')]);setPorts(p);setCfg(c);setSessions(e);setReplays(r);}
  async function act(fn:()=>Promise<any>){setBusy(true);setError('');try{await fn();await refresh();}catch(e){setError(String(e));}finally{setBusy(false);}}
  useEffect(()=>{let alive=true;let running=false;
    refresh().catch(e=>setError(String(e)));
    const poll=async()=>{if(running)return;running=true;try{const state=await request('probe/state');if(alive)setS(state);}catch(e){if(alive){setS(null);setError(String(e));}}finally{running=false;}};
    poll();const timer=setInterval(poll,1000);return()=>{alive=false;clearInterval(timer);};},[]);
  const result=s?.result;
  const reasons:Record<string,string>={accepted:'Đã đưa vào thuật toán',weak_rssi:'Bị lọc RSSI',excluded:'Nằm trong danh sách loại trừ',retry:'Probe retry bị triệt',capacity:'Đạt giới hạn nguồn',no_valid_heartbeat:'Chưa có heartbeat hợp lệ'};
  const events:Record<string,string>={candidate_started:'Bắt đầu theo dõi nguồn',source_confirmed:'Xác nhận quan sát nguồn',observation_gap_started:'Thiếu quan sát qua khe',source_observed_again:'Quan sát nguồn trở lại',source_expired_no_observation:'Hết hiệu lực xác nhận nguồn',candidate_cancelled_no_observation:'Hủy ứng viên do thiếu quan sát',inference_reset:'Reset suy luận do nguồn dữ liệu',queue_drop:'Queue mất gói'};
  return <>
    <div className={'alert '+(s?.mode==='synthetic'?'amber':'')}>{s?.mode==='synthetic'?'DỮ LIỆU MÔ PHỎNG — chỉ kiểm tra luồng xử lý.':s?.mode==='replay'?'REPLAY — dữ liệu đã ghi.':'Nguồn trực tiếp: ESP32-C3 sniffer, chỉ thu Probe Request.'} Số nguồn MAC không tương đương số thiết bị vật lý hoặc số người.</div>
    {error&&<div role="alert" className="alert error">{error}</div>}
    <div className="stats">
      {[['MAC trong cửa sổ',result?.unique_count],['RSSI + timeout',result?.timeout_count],['Sherlock xác nhận',result?.sherlock.count]].map(([name,value])=><section className="stat" key={name}><div className="stat-label">{name}</div><h2>{s?.valid?value:'—'}</h2><p>{s?.valid?'Số nguồn MAC':'Chưa có nguồn dữ liệu hợp lệ'}</p></section>)}
    </div>
    <div className="two-grid">
      <section className="panel"><h3>Kết nối ESP32-C3 sniffer</h3><p>Một board nối USB với laptop. Baud: 460800. Không cần kết nối AP.</p>
        <label>Cổng sniffer<select value={port} onChange={e=>setPort(e.target.value)}><option value="">Chọn cổng</option>{ports.map(p=><option key={p.device} value={p.device}>{p.device} · {p.description}</option>)}</select></label>
        <div className="button-row"><button className="primary" disabled={busy||!port} onClick={()=>act(()=>request('probe/connect','POST',{port,baud:460800}))}>Kết nối</button><button className="secondary" disabled={busy} onClick={()=>act(()=>request('probe/disconnect','POST'))}>Ngắt</button><button className="secondary" onClick={()=>act(refresh)}>Làm mới cổng</button></div>
        <p>Kết nối: {s?.connection??'Chờ backend'} · Kênh: {s?.firmware?.channel??'—'} · {s?.firmware?.scan_mode??'—'}</p>
        <p>Gói hợp lệ: {s?.counters?.valid??0} · Dòng lỗi: {s?.counters?.invalid??0} · Queue drop: {s?.firmware?.probe_dropped??'—'}</p>
        {s?.error&&<div className="alert error">{s.error}</div>}
        <label>Replay<select value={replay} onChange={e=>setReplay(e.target.value)}>{replays.map(r=><option key={r.name}>{r.name}</option>)}</select></label>
        <label>Tốc độ<select value={speed} onChange={e=>setSpeed(Number(e.target.value))}>{[1,4,10,50,100].map(v=><option value={v} key={v}>{v}×</option>)}</select></label>
        <button className="secondary" disabled={busy||!!s?.session} onClick={()=>act(()=>request('probe/replay','POST',{name:replay,speed}))}>Phát lại</button>
        <p className="hint">Phiên phát lại dùng cấu hình đã lưu khi thu. Demo dùng cấu hình riêng với khe 5 giây và AT/WT/DT = 2/2/2.</p>
      </section>
      <section className="panel"><h3>So sánh trực tiếp</h3><p className="hint">{s?.algorithm_version} · Khe đầu được tính vào AT/DT. Không ghi lùi thời điểm xác nhận.</p><CountChart rows={s?.history??[]}/><p className="hint">Xám: MAC khác nhau · Tím: timeout · Xanh: Sherlock. Không có dữ liệu mới: dừng cập nhật, không kết luận thiết bị đã rời.</p>
        <div className="table-scroll"><table><thead><tr><th>MAC rút gọn</th><th>Trạng thái</th><th>RSSI</th><th>Gần nhất</th><th>AT / WT / DT</th></tr></thead><tbody>{(result?.sherlock.sources??[]).slice(0,30).map((r:any)=><tr key={r.mac}><td className="mono">{r.mac.slice(0,8)}:…:{r.mac.slice(-2)}</td><td>{{candidate:'Chờ xác nhận',present:'Đã xác nhận',departing:'Thiếu quan sát · còn giữ xác nhận'}[r.state as string]??r.state}</td><td>{r.rssi} dBm</td><td>{r.age_s.toFixed(1)} s</td><td>{r.positive_slots}/{s?.config.arrival_slots} · {r.missing_slots}/{s?.config.withdrawal_slots} · {r.departure_slots}/{s?.config.departure_slots}</td></tr>)}</tbody></table></div>
      </section>
    </div>
    <section className="panel"><h3>Chẩn đoán MAC khi ngắt AP</h3><p>Đây là kiểm tra quan sát của một địa chỉ. Không kết luận MAC mới là cùng thiết bị, không tự khôi phục danh tính.</p>
      <label>MAC đầy đủ cần kiểm tra<input value={target} placeholder="aa:bb:cc:dd:ee:ff" onChange={e=>{setTarget(e.target.value);setDiag(null);}}/></label>
      <div className="button-row"><button className="primary" disabled={busy||!target} onClick={()=>act(async()=>setDiag(await request('probe/diagnostics?mac='+encodeURIComponent(target))))}>Tra cứu quan sát</button>
      <select aria-label="Loại dấu mốc" value={mark} onChange={e=>setMark(e.target.value)}>{Object.entries({ap_disconnect:'Vừa ngắt AP',ap_connect:'Vừa kết nối AP',scan_requested:'Vừa yêu cầu quét',screen_lock:'Vừa khóa màn hình',screen_unlock:'Vừa mở màn hình',note:'Ghi chú'}).map(([v,n])=><option key={v} value={v}>{n}</option>)}</select>
      <button className="secondary" disabled={busy||!s?.session} onClick={()=>act(()=>request('probe/markers','POST',{kind:mark,mac:target||null,notes}))}>Ghi dấu mốc vừa thao tác</button></div>
      <p className="hint">Bắt đầu một phiên, thao tác trên máy thử nghiệm rồi ghi dấu mốc. Dấu mốc không tự đổi nhãn số thiết bị. Tra cứu trước và sau ngắt AP để so sánh số gói và thời gian.</p>
      {diag&&<div className="alert">{!diag.source_valid&&'Nguồn dữ liệu hiện không hợp lệ. '}{diag.observed?`MAC này đã có ${diag.received} Probe; ${diag.accepted} gói được đưa vào thuật toán; lần gần nhất ${diag.age_s.toFixed(1)}s. ${reasons[diag.last_reason]??diag.last_reason}.`:'Chưa có quan sát MAC này trong bộ đệm hiện tại. Không chứng minh thiết bị vắng mặt.'}</div>}
      {diag?.observed&&<div className="table-scroll"><table><thead><tr><th>t tương đối (s)</th><th>Kênh</th><th>RSSI</th><th>Sequence</th><th>Xử lý</th></tr></thead><tbody>{diag.recent.map((r:any,i:number)=><tr key={i}><td>{r.t_s.toFixed(3)}</td><td>{r.channel}</td><td>{r.rssi}</td><td>{r.frame_seq}</td><td>{reasons[r.reason]??r.reason}</td></tr>)}</tbody></table></div>}
      <h3>Nhật ký thuật toán gần đây</h3><div className="table-scroll"><table><thead><tr><th>Thời điểm (s)</th><th>MAC</th><th>Sự kiện</th></tr></thead><tbody>{(s?.events??[]).slice(-12).reverse().map((e:any)=><tr key={e.event_seq}><td>{e.t_s.toFixed(1)}</td><td>{e.mac??'—'}</td><td>{events[e.kind]??e.kind}{e.reason?' · '+e.reason:''}</td></tr>)}</tbody></table></div>
      <p>Thời gian nghe từng kênh ước tính từ heartbeat: {Object.entries(s?.channel_observation_s??{}).map(([c,t])=>`CH${c}: ${Number(t).toFixed(1)}s`).join(' · ')||'Chưa có'}. Queue drop tăng: {s?.quality?.queue_drop_increase??0}.</p>
      <p className="hint">Thời gian nghe không chứng minh đã bắt mọi gói. Cùng một radio không thể nghe đồng thời 13 kênh. Hãy thử fixed channel để đối chứng riêng; không tự giảm AT/DT để che mất dữ liệu.</p>
    </section>
    <div className="two-grid">
      <section className="panel"><h3>Thu phiên và ghi nhãn thực tế</h3><p>Ghi số thiết bị thử nghiệm thực sự trong vùng. Cập nhật nhãn ngay khi có thay đổi.</p>
        <label>Số thiết bị thật<input type="number" min="0" max="200" value={count} onChange={e=>setCount(Number(e.target.value))}/></label>
        <label>Thiết bị / hệ điều hành / trạng thái<textarea value={devices} onChange={e=>setDevices(e.target.value)}/></label>
        <label>Bố trí<textarea value={layout} onChange={e=>setLayout(e.target.value)}/></label>
        <label>Ghi chú sự kiện<textarea value={notes} onChange={e=>setNotes(e.target.value)}/></label>
        <div className="button-row"><button className="primary" disabled={busy||!s?.valid||s.mode!=='serial'||!!s.session} onClick={()=>act(()=>request('probe/sessions/start','POST',{device_count:count,devices,layout,notes}))}>Bắt đầu phiên</button>
        <button className="secondary" disabled={busy||!s?.session} onClick={()=>act(()=>request('probe/truth','POST',{device_count:count,notes}))}>Ghi thay đổi nhãn</button>
        <button className="secondary" disabled={busy||!s?.session} onClick={()=>act(()=>request('probe/sessions/stop','POST'))}>Kết thúc</button></div>
        <p>{s?.session?`ĐANG THU ${s.session.id.slice(0,8)} · ${s.session.records} bản ghi`:'Chưa có phiên đang thu'}</p>
      </section>
      <section className="panel"><h3>Tham số nghiên cứu</h3><div className="button-row"><button className="secondary" disabled={busy||s?.mode!=='idle'} onClick={()=>setCfg({...cfg,slot_s:60,arrival_slots:6,withdrawal_slots:2,departure_slots:6,rssi_min:-127})}>Điền cấu hình tham chiếu</button><button className="secondary" disabled={busy||s?.mode!=='idle'} onClick={()=>setCfg({...cfg,slot_s:5,arrival_slots:2,withdrawal_slots:2,departure_slots:2,rssi_min:-127})}>Điền cấu hình demo nhanh</button></div><p>Kết thúc phiên và ngắt sniffer trước khi lưu. Cấu hình lưu cùng từng phiên.</p>
        {cfg&&<><div className="settings-grid">{Object.entries({slot_s:'Độ dài khe (s)',arrival_slots:'AT: số khe dương (gồm khe đầu)',withdrawal_slots:'WT: khe trống liên tiếp',departure_slots:'DT: số khe trống (gồm khe đầu)',rssi_min:'RSSI tối thiểu (dBm)',unique_window_s:'Cửa sổ MAC thô (s)',timeout_s:'Timeout baseline (s)',mac_expiry_s:'Giữ MAC chẩn đoán (s)',confirm_window_s:'Cửa sổ xác nhận baseline (s)',confirm_hits:'Số gói baseline'}).map(([key,name])=><label key={key}>{name}<input type="number" value={cfg[key]} onChange={e=>setCfg({...cfg,[key]:Number(e.target.value)})}/></label>)}</div>
        <label>MAC nguồn nền loại trừ (dấu phẩy)<input value={cfg.excluded_macs.join(',')} onChange={e=>setCfg({...cfg,excluded_macs:e.target.value.split(',').map(v=>v.trim()).filter(Boolean)})}/></label>
        <button className="primary" disabled={busy||s?.mode!=='idle'} onClick={()=>act(()=>request('probe/config','PUT',cfg))}>Lưu cấu hình</button></>}
        <p className="hint">Thay channel/dwell trong idf.py menuconfig của firmware/sniffer rồi flash lại. AT/WT/DT có quy ước khe đầu tiên được mô tả trong DAC_TA_DU_AN.md.</p>
      </section>
    </div>
    <section className="panel"><h3>Phiên đã lưu và đánh giá</h3><div className="table-scroll"><table><thead><tr><th>Phiên</th><th>Bắt đầu</th><th>Bản ghi</th><th>Đánh giá</th></tr></thead><tbody>{sessions.map(m=><tr key={m.id}><td>{m.id.slice(0,8)}</td><td>{m.started_at}</td><td>{m.records}</td><td><button className="secondary" disabled={busy||!m.ended_at} onClick={()=>act(async()=>{setReport(await request(`probe/sessions/${m.id}/evaluate`,'POST'));await request(`probe/sessions/${m.id}/inspect`,'POST');})}>Tính kết quả</button> {m.ended_at&&<><a href={`/api/probe/sessions/${m.id}/files/raw`}>Raw JSONL</a><button className="secondary" disabled={busy||!target} onClick={()=>act(async()=>{await request(`probe/sessions/${m.id}/diagnose`,'POST',{mac:target});})}>Phân tích MAC đã nhập</button><a href={`/api/probe/sessions/${m.id}/files/diagnosis`}>Báo cáo MAC</a><a href={`/api/probe/sessions/${m.id}/files/probe-trace`}>Trace MAC</a></>}</td></tr>)}</tbody></table></div>
    {report&&<><p>{report.synthetic?'KẾT QUẢ MÔ PHỎNG':'Kết quả phiên thu'} · Coverage {(100*report.coverage).toFixed(1)}% · Không tính khoảng mất heartbeat.</p><table><thead><tr><th>Phương pháp</th><th>MAE</th><th>Bias</th><th>Đúng số lượng</th><th>PCC</th></tr></thead><tbody>{Object.entries(report.algorithms).map(([k,v]:[string,any])=><tr key={k}><td>{k}</td><td>{v.mae?.toFixed(2)??'—'}</td><td>{v.bias?.toFixed(2)??'—'}</td><td>{v.exact_rate===undefined?'—':(v.exact_rate*100).toFixed(1)+'%'}</td><td>{v.pcc?.toFixed(3)??'Không xác định'}</td></tr>)}</tbody></table><div className="button-row"><a href={`/api/probe/sessions/${report.session}/files/report`}>Tải report.json</a><a href={`/api/probe/sessions/${report.session}/files/timeline`}>Tải timeline.csv</a><a href={`/api/probe/sessions/${report.session}/files/heatmap`}>Tải heatmap Probe</a><a href={`/api/probe/sessions/${report.session}/files/slots`}>Tải bảng khe</a><a href={`/api/probe/sessions/${report.session}/files/events`}>Nhật ký đánh giá causal</a><a href={`/api/probe/sessions/${report.session}/files/markers`}>Dấu mốc thử nghiệm</a></div><p className="hint">MAE/Bias so với số thiết bị thật. PCC không phải độ chính xác. timeline.csv và report.json lưu trong thư mục evaluation của phiên. Độ trễ sự kiện là lần vượt mức đếm mới, không phải theo dõi danh tính.</p></>}
    </section>
  </>
}
