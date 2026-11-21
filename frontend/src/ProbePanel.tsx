import React, {useEffect, useState} from 'react';
import ResearchPanel from './ResearchPanel';
import ScopePanel from './ScopePanel';
import DeviceOverview from './DeviceOverview';

async function request(path:string, method='GET', body?:unknown) {
  const response=await fetch('/api/'+path, {method, headers:{'Content-Type':'application/json'}, body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();
  if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
  return data;
}

export default function ProbePanel() {
  const [tab,setTab]=useState('observe');
  const [search,setSearch]=useState(''), [sourceFilter,setSourceFilter]=useState('all');
  const [people,setPeople]=useState('');
  const [advanced,setAdvanced]=useState(false), [state,setState]=useState<any>(null);
  const [ports,setPorts]=useState<any[]>([]), [port,setPort]=useState('');
  const [config,setConfig]=useState<any>(null), [sessions,setSessions]=useState<any[]>([]);
  const [count,setCount]=useState<number>(0), [room,setRoom]=useState('Phòng học thử nghiệm');
  const [devices,setDevices]=useState(''), [notes,setNotes]=useState('');
  const [busy,setBusy]=useState(false), [error,setError]=useState(''), [message,setMessage]=useState('');
  const [loadError,setLoadError]=useState('');
  const [report,setReport]=useState<any>(null);
  const [inspection,setInspection]=useState('');

  async function refresh() {
    const [s,p,items]=await Promise.all([request('probe/state'),request('ports'),request('probe/sessions')]);
    setState(s);setPorts(p);setConfig(s.config);setSessions(items);setLoadError('');
    setPort(current=>p.some((v:any)=>v.device===current)?current:(p[0]?.device??''));
  }
  async function act(action:()=>Promise<void>) {
    setBusy(true);setError('');setMessage('');
    try {await action();await refresh();} catch(e) {setError(e instanceof Error?e.message:String(e));}
    finally {setBusy(false);}
  }
  useEffect(()=>{
    let active=true, polling=false;
    refresh().catch(e=>{if(active)setLoadError(String(e));});
    const timer=setInterval(async()=>{
      if(polling)return;polling=true;
      try {const s=await request('probe/state');if(active){setState(s);setConfig(s.config);setLoadError('');}}
      catch(e) {if(active){setState(null);setLoadError(String(e));}}
      finally {polling=false;}
    },1000);
    return()=>{active=false;clearInterval(timer);};
  },[]);

  const idle=state?.mode==='idle'&&!state?.session;
  const live=state?.mode==='serial', synthetic=state?.mode==='synthetic';
  const valid=Boolean(state?.valid), session=state?.session;
  const result=state?.result, confirmed=result?.sherlock?.count;
  const actual=session?(state.current_truth?.device_count??session.device_count):count;
  const connection=state?.connection;
  const status=!state?'Đang chờ máy chủ':connection==='finished'?'Đã phát xong':valid?'Đang nhận dữ liệu':connection==='reconnecting'?'Đang nối lại':connection==='connected'?'Đang chờ heartbeat':'Chưa kết nối';

  async function demo() {
    await request('probe/replay','POST',{name:'synthetic-probe-demo',speed:10});
    setReport(null);setMessage('Demo 10× · khe 5 giây · AT/WT/DT = 2/2/2 · không lọc RSSI.');
  }
  async function timing(fast:boolean) {
    await request('probe/config','PUT',{...config,slot_s:fast?15:60,arrival_slots:fast?2:6,withdrawal_slots:2,departure_slots:fast?2:6});
    setMessage(fast?'Đã chọn cấu hình thử nhanh, chưa hiệu chỉnh trên phòng thật.':'Đã chọn thời gian tham chiếu.');
  }
  const sources=(valid?result?.sherlock?.sources??[]:[]).filter((r:any)=>r.mac.includes(search.toLowerCase().trim())&&(sourceFilter==='all'||r.state===sourceFilter));
  const peopleOK=people===''||(Number.isInteger(Number(people))&&Number(people)>=0&&Number(people)<=200);
  const peopleCount=people===''?null:Number(people);
  const countOK=Number.isInteger(count)&&count>=0&&count<=200;

  return <>
    <nav className="detect-tabs" aria-label="Chức năng dashboard">{[['observe','1','Kết nối & quan sát'],['record','2','Ghi phiên & nhãn'],['results','3','Kết quả đã lưu']].map(([key,step,title])=><button key={key} aria-current={!advanced&&tab===key?'page':undefined} className={!advanced&&tab===key?'active':''} onClick={()=>{setAdvanced(false);setTab(key);}}><span>{step}</span>{title}</button>)}<button className={advanced?'active':''} onClick={()=>setAdvanced(true)}>Nâng cao</button></nav>
      <div className="source-strip" role="status"><span className={'status-dot '+(valid?'online':'')}/><strong>{status}</strong>{session&&<span>{session.layout} · {session.records} bản ghi</span>}<span>{synthetic?'DEMO · Mô phỏng':state?.mode==='replay'?'REPLAY · Phát lại':live?'LIVE · ESP32-C3':'Chọn USB hoặc demo bên dưới'}</span>{session&&<span className="recording">● Đang ghi phiên</span>}</div>
      {(error||loadError)&&<div className="alert error" role="alert">{error||loadError}</div>}
      {state?.error&&<div className="alert error" role="alert">{state.error}</div>}
      {message&&<div className="alert" role="status">{message}</div>}
      {synthetic&&<div className="alert amber">Dữ liệu mô phỏng để kiểm tra phần mềm. Số thiết bị thật bạn nhập không dùng để đánh giá demo này.</div>}

      {!advanced&&<>
      <DeviceOverview sourceId={state?.dashboard_source_id} connection={connection} valid={valid} observe={tab==='observe'}/>
      <div className="stats simple-stats">
        <section className="stat main-count"><div className="stat-label">Nguồn MAC đã xác nhận</div><h2>{valid?confirmed:'—'}</h2><p>{valid?'Sherlock · có thể khác số thiết bị thật':'Chưa có kết quả hợp lệ'}</p></section>
        <section className="stat"><div className="stat-label">Thiết bị thật trong phòng</div><h2>{!session||synthetic||state?.mode==='replay'?'—':actual}</h2><p>{session?'Nhãn đã ghi gần nhất':'Chưa ghi nhãn · nhập ở tab Ghi phiên'}</p></section>
        <section className="stat"><div className="stat-label">Chênh lệch số đếm</div><h2>{valid&&live&&session?(confirmed-actual>0?'+':'')+(confirmed-actual):'—'}</h2><p>{valid&&live&&session?'Nguồn MAC xác nhận − thiết bị thật':'Hiển thị khi đang thu phiên USB'}</p></section>
      </div>

      <div hidden={tab!=='observe'}>
      <div className="observation-summary"><span>Thấy trong khe đang mở <strong>{valid?result?.sherlock?.n_sources_seen??'—':'—'}</strong></span><span>Có nguồn được xác nhận <strong>{valid?(confirmed>=1?'Có':'Không'):'—'}</strong></span><span>Chờ xác nhận <strong>{valid?(result?.sherlock?.sources??[]).filter((r:any)=>r.state==='candidate').length:'—'}</strong></span><span>Thiếu quan sát, còn xác nhận <strong>{valid?(result?.sherlock?.sources??[]).filter((r:any)=>r.state==='departing').length:'—'}</strong></span></div>
      <div className="two-grid setup-grid">
        <section className="panel"><h3>Phòng & bộ lọc</h3>
          <p>RSSI lọc bớt tín hiệu yếu, không tạo ranh giới phòng. Thiết bị ngoài cửa hoặc phòng bên vẫn có thể được tính.</p>
          <label>Tên phòng / bố trí<input value={room} maxLength={1000} disabled={!!session} onChange={e=>setRoom(e.target.value)} placeholder="Ví dụ: A203 · board giữa phòng, cửa đóng"/></label>
          <details><summary>Điều chỉnh phạm vi bằng RSSI · {config?.rssi_min===-127?'đang tắt':config?`≥ ${config.rssi_min} dBm`:'đang tải'}</summary><ScopePanel compact onApplied={()=>{void refresh();}}/></details>
        </section>

        <section className="panel"><h3>Kết nối ESP32-C3</h3>
          <label>Cổng USB ESP32-C3<select value={port} disabled={busy||!!session} onChange={e=>setPort(e.target.value)}><option value="">{ports.length?'Chọn cổng':'Chưa tìm thấy cổng USB'}</option>{ports.map(p=><option key={p.device} value={p.device}>{p.device} · {p.description}</option>)}</select></label>
          <div className="button-row"><button className="primary" disabled={busy||!port||!idle} onClick={()=>act(async()=>{await request('probe/connect','POST',{port,baud:460800});})}>Kết nối USB</button><button className="secondary" disabled={busy||!!session||!state||idle} onClick={()=>act(async()=>{await request('probe/disconnect','POST');})}>Ngắt nguồn</button><button className="secondary" disabled={busy} onClick={()=>act(async()=>{await refresh();})}>Tìm lại cổng</button></div>
          <div className="demo-box"><strong>Chưa có board?</strong><p>Chạy dữ liệu mẫu khoảng 9 giây để thử số đếm. Demo tự dùng cấu hình nhanh và tắt lọc RSSI.</p><button className="secondary" disabled={busy||!idle||!config} onClick={()=>act(demo)}>Chạy demo nhanh</button></div>
          <p className="hint">Kênh {state?.firmware?.channel??'—'} · Gói hợp lệ {state?.counters?.valid??0} · Dòng lỗi {state?.counters?.invalid??0} · Gói rơi {state?.firmware?.probe_dropped??'—'}</p>
          <details><summary>Thời gian xác nhận · khe {config?.slot_s??'—'} s · AT/WT/DT {config?.arrival_slots??'—'}/{config?.withdrawal_slots??'—'}/{config?.departure_slots??'—'}</summary><p>Khe {config?.slot_s??'—'} giây · AT {config?.arrival_slots??'—'} · WT {config?.withdrawal_slots??'—'} · DT {config?.departure_slots??'—'}.</p><p>Cần đủ số khe có Probe để xác nhận; điện thoại phát thưa có thể phải chờ lâu hơn.</p><div className="button-row"><button className="secondary" disabled={busy||!idle||!config} onClick={()=>act(()=>timing(true))}>Thử nhanh: 15s, 2/2/2</button><button className="secondary" disabled={busy||!idle||!config} onClick={()=>act(()=>timing(false))}>Tham chiếu: 60s, 6/2/6</button></div></details>
        </section>
      </div>

      <section className="panel quality-panel"><h3>Chất lượng thu</h3><div className="quality-grid">{[['Heartbeat',state?.heartbeat_age_s==null?'—':state.heartbeat_age_s.toFixed(1)+' s trước'],['Chế độ kênh',state?.firmware?.scan_mode??'—'],['Kênh / thời gian nghe',state?.firmware?`${state.firmware.channel} / ${(state.firmware.dwell_ms??0)/1000} s`:'—'],['Lỗi serial',state?.firmware?.serial_errors??'—'],['Nối lại USB',state?.counters?.reconnects??'—'],['Giới hạn bộ nhớ',valid?result?.capacity_drops??0:'—']].map(([label,value])=><div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><p className="hint">Mất heartbeat: số đếm hiển thị “—”, không coi là 0. Một radio nghe một kênh tại mỗi thời điểm.</p></section>
      </div>

      <section hidden={tab!=='record'} className="panel"><h3>Ghi phiên kiểm thử</h3><p className="hint">Phòng / bố trí: {session?.layout??room}. {session?`Nhãn số người đã lưu: ${state.current_truth?.people_count??session.people_count??'chưa ghi'}.`:'Số thiết bị và số người được ghi riêng; báo cáo hiện đánh giá theo số thiết bị.'}</p><p>Đưa thiết bị vào phòng, nhập số lượng thật và bắt đầu. Khi thêm/bớt thiết bị, cập nhật số rồi bấm “Ghi số mới”.</p>
        <div className="session-fields"><label>Số thiết bị thật<input type="number" min="0" max="200" step="1" value={Number.isNaN(count)?'':count} onChange={e=>setCount(e.target.value===''?NaN:Number(e.target.value))}/></label><label>Thiết bị thử nghiệm<input value={devices} maxLength={2000} disabled={!!session} onChange={e=>setDevices(e.target.value)} placeholder="Ví dụ: Samsung A54 / Android / WiFi bật"/></label><label>Số người (tùy chọn)<input type="number" min="0" max="200" step="1" value={people} onChange={e=>setPeople(e.target.value)} placeholder="Chưa ghi nhãn"/></label><label>Ghi chú<input value={notes} maxLength={2000} onChange={e=>setNotes(e.target.value)} placeholder="Ví dụ: máy ra ngoài cửa, vẫn bật WiFi"/></label></div>
        {session&&count!==actual&&<p className="alert amber">Số đang nhập khác nhãn đã lưu ({actual} thiết bị). Bấm “Ghi số mới” để lưu thay đổi.</p>}
        {!session&&(!valid||!live)&&<p className="alert">Vào tab Kết nối & quan sát, kết nối USB và chờ heartbeat hợp lệ trước khi ghi phiên thật.</p>}
        <div className="button-row"><button className="primary" disabled={busy||!valid||!live||!!session||!room.trim()||!devices.trim()||!countOK||!peopleOK} onClick={()=>act(async()=>{setReport(null);await request('probe/sessions/start','POST',{device_count:count,people_count:peopleCount,devices,layout:room,notes});setMessage('Đã bắt đầu ghi dữ liệu và nhãn thực tế.');})}>Bắt đầu ghi</button><button className="secondary" disabled={busy||!session||!countOK||!peopleOK} onClick={()=>act(async()=>{await request('probe/truth','POST',{device_count:count,people_count:peopleCount,notes});setMessage(`Đã ghi nhãn ${count} thiết bị.`);})}>Ghi số mới</button><button className="secondary" disabled={busy||!session} onClick={()=>act(async()=>{await request('probe/sessions/stop','POST');setTab('results');setMessage('Đã lưu phiên. Bấm “Xem kết quả” để đánh giá.');})}>Kết thúc & lưu</button></div>
        <p className="hint">{session?`Đang thu · ${session.records} bản ghi · phòng: ${session.layout}`:'Chưa ghi phiên. Cần kết nối USB có heartbeat, điền phòng và thiết bị thử nghiệm để bắt đầu ghi.'}</p>
      </section>

      <section hidden={tab!=='observe'} className="panel"><h3>Probe vừa nhận · trước bộ lọc</h3><p className="hint">Hiển thị tối đa 50 MAC có Probe gần nhất. Một MAC rời bộ đệm sau hơn {config?.mac_expiry_s ?? "—"} giây không thấy Probe từ MAC đó.</p>
        <div className="observation-summary"><span>Probe board đã bắt<strong>{state?.firmware?.probe_seen??'—'}</strong></span><span>Probe qua bộ lọc<strong>{valid?result?.accepted??0:'—'}</strong></span><span>Bị lọc RSSI<strong>{valid?result?.filter_counts?.weak_rssi??0:'—'}</strong></span><span>Bị loại theo MAC<strong>{valid?result?.filter_counts?.excluded??0:'—'}</strong></span></div>
        {!valid?<p className="alert amber">Chưa có heartbeat hợp lệ. Kiểm tra kết nối USB, đúng firmware và baud 460800. Chưa thể kết luận có hay không có thiết bị.</p>:(state?.recent_sources??[]).length===0?<p className="alert amber">Heartbeat hợp lệ nhưng bộ đệm hiện không có MAC. Firmware chỉ lấy Probe Request, không lấy mọi gói từ thiết bị đang kết nối WiFi. Thử mở danh sách mạng WiFi trên một máy đặt gần board và quan sát qua vài vòng nhảy kênh.</p>:valid&&result?.accepted===0?<p className="alert amber">Laptop đã nhận Probe nhưng chưa có gói qua bộ lọc. Xem lý do bên dưới; nếu bị lọc RSSI, mở “Điều chỉnh phạm vi bằng RSSI” và tắt lọc để kiểm tra đường thu.</p>:<p className="hint">Đã có Probe tới thuật toán. Bảng trạng thái bên dưới cập nhật sau khi chốt khe {config?.slot_s??'—'} giây; xác nhận còn cần đủ AT. Điện thoại phát thưa có thể phải chờ lâu hơn.</p>}
        <div className="table-scroll"><table><thead><tr><th>MAC quan sát</th><th>RSSI</th><th>Lần cuối</th><th>Xử lý gói gần nhất</th></tr></thead><tbody>{(state?.recent_sources??[]).map((r:any)=><tr key={r.mac}><td className="mono">{r.mac}</td><td>{r.rssi} dBm</td><td>{r.age_s.toFixed(1)} s trước{!valid?' · dữ liệu cũ':''}</td><td>{({accepted:'Đưa vào thuật toán',weak_rssi:'Tín hiệu dưới ngưỡng RSSI',excluded:'MAC trong danh sách loại trừ',retry:'Gói retry trùng',no_valid_heartbeat:'Thiếu heartbeat hợp lệ',capacity:'Đạt giới hạn nguồn'} as Record<string,string>)[r.last_reason]??r.last_reason}</td></tr>)}{!state?.recent_sources?.length&&<tr><td colSpan={4} className="empty">Hiện không có MAC trong bộ đệm.</td></tr>}</tbody></table></div><p className="hint">Bộ đếm board tính từ lúc board khởi động; bộ đếm lọc tính từ lần khởi tạo thuật toán, không nhất thiết cùng mốc. ESP32-C3 chỉ thu WiFi 2.4 GHz.</p>
      </section>

      <section hidden={tab!=='observe'} className="panel"><h3>Nguồn đang theo dõi</h3><p className="hint">Số xác nhận gồm “Đã xác nhận” và “Thiếu quan sát”. AT tích lũy khe có Probe; WT hủy ứng viên khi đủ khe trống; DT kết thúc xác nhận khi đủ khe thiếu quan sát.</p><div className="detect-filters"><label>Tìm MAC<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Nhập một phần địa chỉ MAC"/></label><label>Trạng thái<select value={sourceFilter} onChange={e=>setSourceFilter(e.target.value)}><option value="all">Tất cả</option><option value="candidate">Chờ xác nhận</option><option value="present">Đã xác nhận</option><option value="departing">Thiếu quan sát</option></select></label><span>{sources.length} nguồn phù hợp</span></div><p>MAC trong cửa sổ: {valid?result?.unique_count:'—'} · Timeout: {valid?result?.timeout_count:'—'}. Số 0 chỉ hiển thị khi nguồn dữ liệu hợp lệ.</p><div className="table-scroll"><table><thead><tr><th>Địa chỉ MAC</th><th>Trạng thái</th><th>RSSI</th><th>Lần cuối</th><th>AT / WT / DT (khe)</th></tr></thead><tbody>{sources.map((r:any)=><tr key={r.mac}><td className="mono">{r.mac}</td><td>{({candidate:'Chờ xác nhận',present:'Đã xác nhận',departing:'Đang thiếu quan sát'} as Record<string,string>)[r.state]??r.state}</td><td>{r.rssi} dBm</td><td>{r.age_s.toFixed(1)} s</td><td>{r.positive_slots}/{config?.arrival_slots} · {r.missing_slots}/{config?.withdrawal_slots} · {r.departure_slots}/{config?.departure_slots}</td></tr>)}{!sources.length&&<tr><td colSpan={5} className="empty">Chưa có nguồn phù hợp. Kết nối nguồn và chờ chốt khe đầu tiên; kiểm tra bộ lọc nếu cần.</td></tr>}</tbody></table></div></section>

      <section hidden={tab!=='results'} className="panel"><h3>Phiên đã lưu</h3>{sessions.length===0?<p className="empty">Chưa có phiên. Demo không được lưu thành phiên thu thật.</p>:<div className="table-scroll"><table><thead><tr><th>Phòng / phiên</th><th>Thời gian</th><th>Bản ghi</th><th>Kết quả & dữ liệu</th></tr></thead><tbody>{sessions.map(m=><tr key={m.id}><td>{m.layout||m.id.slice(0,8)}{m.synthetic?' · Mô phỏng':''}</td><td>{new Date(m.started_at).toLocaleString('vi-VN')}</td><td>{m.records}</td><td><button className="secondary" disabled={busy||!m.ended_at} onClick={()=>act(async()=>{setReport(null);setReport(await request(`probe/sessions/${m.id}/evaluate`,'POST'));})}>{m.ended_at?'Xem kết quả':'Đang ghi'}</button>{m.ended_at&&<div className="session-downloads">{[['raw','Raw JSONL'],['truth','Nhãn'],['metadata','Thông tin phiên']].map(([kind,label])=><a key={kind} href={`/api/probe/sessions/${m.id}/files/${kind}`}>{label}</a>)}<button className="secondary" disabled={busy} onClick={()=>act(async()=>{await request(`probe/sessions/${m.id}/inspect`,'POST');setMessage('Đã tạo heatmap và bảng khe cho phiên '+m.id);setInspection(m.id);})}>Tạo heatmap / bảng khe</button></div>}</td></tr>)}</tbody></table></div>}
        {report&&<div className="report-box"><h3>{report.synthetic?'Kết quả mô phỏng':'Kết quả phiên'} · {report.session.slice(0,8)}</h3><p>Thời gian có dữ liệu hợp lệ và nhãn: {(report.coverage*100).toFixed(1)}%.</p><div className="table-scroll"><table><thead><tr><th>Phương pháp</th><th>Sai số MAE</th><th>Đếm đúng</th><th>Bias</th><th>PCC</th><th>MRE (nhãn &gt; 0)</th><th>MAE (nhãn 0)</th></tr></thead><tbody>{Object.entries(report.algorithms).map(([key,v]:[string,any])=><tr key={key}><td>{({sherlock:'Sherlock',unique:'MAC trong cửa sổ',timeout:'Timeout'} as Record<string,string>)[key]}</td><td>{v.mae?.toFixed(2)??'—'}</td><td>{v.exact_rate==null?'—':`${(v.exact_rate*100).toFixed(1)}%`}</td><td>{v.bias?.toFixed(2)??'—'}</td><td>{v.pcc?.toFixed(3)??'—'}</td><td>{v.mre_nonzero==null?'—':`${(v.mre_nonzero*100).toFixed(1)}%`}</td><td>{v.zero_truth_mae?.toFixed(2)??'—'}</td></tr>)}</tbody></table></div><div className="button-row"><a href={`/api/probe/sessions/${report.session}/files/report`}>Tải báo cáo JSON</a><a href={`/api/probe/sessions/${report.session}/files/timeline`}>Tải CSV theo thời gian</a></div></div>}
        {inspection&&<div className="alert">Đã phân tích phiên {inspection.slice(0,8)}. <a href={`/api/probe/sessions/${inspection}/files/heatmap`}>Mở heatmap</a> · <a href={`/api/probe/sessions/${inspection}/files/slots`}>Tải CSV theo khe</a></div>}
        {report&&<><p className="hint">MAE: sai số tuyệt đối trung bình · Bias: đếm dư (+) / thiếu (−) · PCC: tương quan, không phải độ chính xác. “—” nghĩa là không đủ dữ liệu.</p><h3>Độ trễ chạm số đếm mới</h3><div className="table-scroll"><table><thead><tr><th>Phương pháp</th><th>Số thay đổi nhãn</th><th>Chưa đạt mức mới</th><th>Trễ trung bình (đã đạt)</th></tr></thead><tbody>{Object.entries(report.events??{}).map(([key,rows]:[string,any])=>{const hits=rows.filter((r:any)=>r.delay_s!=null);return <tr key={key}><td>{key}</td><td>{rows.length}</td><td>{rows.filter((r:any)=>r.censored).length}</td><td>{hits.length?(hits.reduce((sum:number,r:any)=>sum+r.delay_s,0)/hits.length).toFixed(1)+' s':'—'}</td></tr>;})}</tbody></table></div><p className="hint">Độ trễ số đếm không đo việc nhận dạng từng thiết bị. Sự kiện chưa đạt (censored) được giữ trong báo cáo.</p></>}
      </section>
      <details className="panel detect-notes"><summary>Cách đọc kết quả</summary><p>MAC có thể thay đổi; không tự ghép hai MAC thành một thiết bị. RSSI không xác định chính xác ranh giới phòng. Không có Probe không chứng minh thiết bị đã rời.</p><p>Khe hiện tại hiển thị số nguồn đã qua lọc, chưa chốt; mặc định 60 giây. “MAC trong cửa sổ” bên trên là đối chứng với cửa sổ trượt, khác số nguồn trong khe.</p></details>
    </>}
    {advanced&&<div className="detect-advanced"><p className="alert">Công cụ chi tiết: cấu hình đầy đủ, phát lại phiên, chẩn đoán MAC và ghi dấu mốc. Kết thúc phiên trước khi đổi nguồn.</p><ResearchPanel/></div>}
  </>;
}
