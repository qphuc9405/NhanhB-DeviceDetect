import ProbePanel from './ProbePanel';
export default function Dashboard() {
  return <div className="detect-app">
    <header className="detect-header"><a href="#" className="detect-brand">S<span>SHERLOCK<small>PHÁT HIỆN THIẾT BỊ WIFI</small></span></a><span className="detect-board">ESP32-C3 · 2.4 GHz · 1 sniffer</span></header>
    <main className="detect-main"><div className="detect-title"><div className="eyebrow">NHÁNH PHÁT HIỆN THIẾT BỊ</div><h1>Quan sát WiFi, ghi nhận thực nghiệm.</h1><p>Kết nối board, theo dõi nguồn phát và đối chiếu với số thiết bị thực tế.</p></div><ProbePanel/></main>
    <footer className="detect-footer">Sherlock adaptation · Probe Request thụ động · Số nguồn MAC không tương đương số thiết bị hay số người.</footer>
  </div>;
}
