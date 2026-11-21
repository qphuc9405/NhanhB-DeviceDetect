# Cập nhật v1.1 — sửa hạn chế sau khi đối chiếu repo gốc

## Cách cài không mất dữ liệu

1. Dừng dashboard/backend cũ (Ctrl+C), đóng mọi serial monitor.
2. Giải nén bản mới vào **thư mục khác**, ví dụ ~/Downloads/sherlock-v2/wifi-device-sherlock.
   Không ghi đè dự án đang chỉnh sửa bằng Codex và không xóa data/runtime cũ.
3. Chạy bash scripts/setup.sh ở thư mục mới. Chỉ dùng một backend mở cổng USB.
4. Nếu cần đọc dữ liệu cũ, sao chép thư mục data/runtime cũ vào data/runtime mới
   khi cả hai backend đều dừng. Sao chép cả metadata.sqlite3 và các file phụ
   SQLite nếu có. Giữ bản cũ nguyên trạng để quay lại.
5. So lại configs/probe.json và danh sách MAC loại trừ. Các trường cấu hình cũ
   vẫn dùng được. Thay đổi quy tắc khe làm kết quả khác dù con số AT/DT giữ nguyên.
6. Chạy bash scripts/run.sh. Làm một phiên mới để kiểm tra trước khi đánh giá lại
   dữ liệu cũ. Báo cáo mới ghi recorded_algorithm_version và algorithm_version.

Firmware không thay đổi trong bản cập nhật này: không cần nạp lại nếu board
đang dùng firmware sniffer của bản WiFi_Device_Sherlock_Source.zip trước đó,
xuất JSON node=sniffer, type=status/probe/channel, capture_active và scan_mode.
Nếu board đang chạy firmware khác, hãy đối chiếu schema trước khi kết nối.

## Những gì đã sửa

- Tính khe dương đầu tiên vào AT và khe trống đầu tiên vào DT như vòng lặp PHP
  quantifyPeopleBySlots.php ở upstream commit738a896.
- Giữ thời điểm phát hiện và thời điểm xác nhận riêng; không ghi lùi kết quả live.
- Các nhãn thiếu quan sát/hết hiệu lực không khẳng định máy đã rời phòng.
- Live/replay/evaluate dùng chung Stream để xử lý boot, heartbeat và radio state.
- Reconnect serial được ghi như **control record của laptop**, không giả gói
  heartbeat của board. Offline reset tại cùng thời điểm, kể cả boot_id không đổi.
- Thời gian nghe từng kênh được ước tính từ channel/status và heartbeat. Không
  coi đó là số gói phát thực tế hay chứng minh phủ toàn bộ kênh.
- Triệt trùng chỉ khi retry flag được bật và cùng sequence/channel trong100ms.
- Chẩn đoán MAC lưu số gói trước lọc, sau lọc và lý do; kiểm tra chính xác MAC cũ
  khi ngắt AP. Không tự gán MAC mới cho cùng máy.
- Có dấu mốc thí nghiệm, nhật ký sự kiện causal và phân tích trước/sau mốc.

## Các file cần hợp nhất nếu bạn đã chỉnh sửa riêng bằng Codex

research/detectors.py, research/stream.py (mới), research/collector.py,
research/evaluate.py, research/diagnose.py (mới), backend/app/probe_api.py,
frontend/src/ProbePanel.tsx, frontend/vite.config.ts, tests/test_v2.py,
tests/test_algorithms.py và tài liệu liên quan. Không tự ghi đè giao diện bạn
đã sửa; đưa thay đổi vào code đang dùng rồi chạy toàn bộ test/build.

Mã này được cập nhật trên bản ZIP đã bàn giao. Những thay đổi bạn làm trên máy
sau đó chưa có trong workspace này, vì vậy cần hợp nhất thay vì thay toàn bộ.

## Phép thử Ubuntu sau khi cập nhật

1. Kết nối sniffer, bắt đầu phiên; nhập đủ MAC hiện biết vào ô chẩn đoán.
2. Bấm Tra cứu quan sát khi máy thử còn nối AP; ghi received/accepted/last_seen.
3. Ngắt AP trên **máy thử**, vẫn bật WiFi, rồi ngay lập tức bấm Ghi dấu mốc với
   loại Vừa ngắt AP. Dấu mốc không thay đổi ground truth số thiết bị.
4. Yêu cầu quét trên máy thử nếu muốn; ghi thêm mốc Vừa yêu cầu quét.
5. Tra cứu lại MAC cũ, xem packet time/channel/RSSI/reason và nhật ký AT/DT.
6. Kết thúc phiên, bấm Phân tích MAC đã nhập, tải Báo cáo MAC và Trace MAC.

CLI tương đương:

```bash
.venv/bin/python -m research.diagnose --session data/runtime/experiments/ID --mac aa:bb:cc:dd:ee:ff
```

Báo cáo cửa sổ60s trước/sau mốc còn có seconds_available_after, để không nhầm
phiên kết thúc sớm với không có Probe cả phút. Các gói đánh accepted không
nhất thiết đủ khe AT. Tìm candidate/confirmed/gap/expired ở nhật ký thuật toán.

## Giới hạn không thể xóa chỉ bằng sửa bộ đếm

- MAC đổi, scan passive, phát thưa và sniffer ở kênh khác có thể cho cùng một
  kết quả “không thấy MAC A”. Không có dữ liệu tham chiếu thì không phân biệt chắc.
- RSSI không xác định chính xác ranh giới phòng; không ghép MAC chỉ vì RSSI giống.
- Một radio không thu đồng thời13 kênh; muốn tăng thời gian nghe cần đối chứng
  fixed channel hoặc thêm sniffer, chưa được triển khai đa sniffer trong bản này.
- Không dùng giảm AT/DT để chứng minh đã khắc phục MAC randomization. Thử các
  cấu hình trên development và test độc lập, báo thêm coverage và queue drop.
