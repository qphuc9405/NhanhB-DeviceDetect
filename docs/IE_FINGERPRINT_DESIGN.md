# Thiết kế IE fingerprint cho Probe Request

## Dữ liệu đầu vào

Firmware ESP32-C3 ghi trường `ie` dưới dạng dãy `mã:độ_dài` theo thứ tự trong khung Probe Request, tối đa 24 cặp. JSONL còn có MAC nguồn, RSSI, kênh và timestamp để phục vụ các luồng thu và phân tích riêng. Firmware dừng đọc ở cuối phần dữ liệu hoặc khi gặp IE khai báo dài hơn phần khung còn lại. Log hiện hành chỉ có danh sách cặp đã đọc, nên từ JSONL không xác định được khung đã bị cắt ở đâu. [Firmware](../firmware/sniffer/main/main.c#L41) · [Parser JSONL](../backend/app/protocol.py#L19)

Workspace hiện chưa có JSONL hoặc PCAP thu RF gốc để xác nhận IE nào xuất hiện trên thiết bị thật. Demo tổng hợp hiện hành tạo Probe thiếu trường `ie`. Các cặp trong ví dụ và test là dữ liệu tổng hợp. Khi có log, dùng `--report` để đo số Probe chứa từng ID, số lần xuất hiện và phân bố độ dài quan sát được.

| Đặc trưng | ID | Phần có thể sử dụng từ JSONL hiện tại |
|---|---:|---|
| Supported Rates | 1 | Sự hiện diện, độ dài danh sách và vị trí. Từng giá trị tốc độ và cờ Basic Rate nằm trong payload. |
| Extended Supported Rates | 50 | Sự hiện diện, độ dài và vị trí của danh sách mở rộng. |
| HT Capabilities | 45 | Sự hiện diện, độ dài và vị trí. Bit capability và MCS nằm trong payload. |
| Extended Capabilities | 127 | Sự hiện diện, độ dài và vị trí. Các bit capability nằm trong payload. |
| Vendor Specific | 221 | Số lần xuất hiện, độ dài từng mục và thứ tự. OUI, loại và nội dung vendor nằm trong payload. |
| DS Parameter Set, VHT Capabilities và các ID khác | 3, 191, … | Giữ mã và độ dài quan sát được. ID chưa đặt tên vẫn giữ nguyên dạng số. |
| SSID, SSID List và Element ID Extension | 0, 84, 255 | Kiểm kê sự hiện diện và số lần xuất hiện. Bỏ độ dài khỏi đầu ra fingerprint. ID 255 có thể chứa Short SSID List và wire hiện tại không có subtype để phân biệt. |

Cách gọi tên ID đối chiếu với định nghĩa IEEE 802.11 trong Linux. [Bảng mã IE và mã mở rộng](https://github.com/torvalds/linux/blob/master/include/linux/ieee80211.h)

## Chuẩn hóa và chất lượng

- Phiên bản **`ie-id-length-v1`** đọc ID và độ dài dưới dạng byte thập phân `0..255`, rồi ghi lại không có số 0 ở đầu. Giữ thứ tự và số lần lặp của các cặp còn lại. Nhiều Vendor Specific IE có thể cùng mã và độ dài dù payload khác nhau. `duplicate_ids` giúp kiểm tra các ID lặp.
- Một IE thiếu được để thiếu. Nếu cả trường rỗng, trạng thái là `missing`. Nếu chỉ có các ID bị loại, trạng thái là `no_usable_ie`. Cặp sai cú pháp, vượt miền byte hoặc danh sách vượt 24 mục có trạng thái `malformed`. Ba trạng thái này không sinh hash hoặc điểm tương đồng. Parser JSONL vẫn từ chối dòng sai cú pháp wire như trước. Báo cáo chất lượng tính trên các Probe đã qua parser và khử bản sao.
- Đủ 24 cặp được đánh dấu `possibly_truncated`. Danh sách ngắn hơn cũng có thể thiếu IE. Các điểm số chỉ dùng cấu trúc có mặt trong log. Phiên bản này kiểm tra cấu trúc cặp mã–độ dài. Việc kiểm tra đầy đủ ý nghĩa của payload cần thêm dữ liệu từ firmware.
- Hash là SHA-256 của chuỗi ASCII `ie-id-length-v1:<chuỗi_chuẩn>`. Dữ liệu đầu vào của hash chỉ gồm cặp IE đã chuẩn hóa. Các đầu ra CLI không ghi MAC nguồn, nội dung SSID hoặc payload. Chẩn đoán MAC và raw JSONL tiếp tục dùng hợp đồng lưu trữ của dự án.
- Mỗi Probe có profile riêng. CLI giữ mọi biến thể quan sát được trong burst, kể cả khi Probe cùng MAC đổi IE. Tổng MAC phân biệt trong báo cáo chỉ tính mỗi MAC một lần dù có nhiều profile. Nhóm trên CLI là thống kê cấu trúc IE. Số MAC trong nhóm có thể lớn hơn một ngay cả khi các mẫu đến từ nhiều thiết bị giống nhau.

MAC Tracking tiếp tục trả trường chuỗi `fingerprint_id` như trước, lấy từ cấu trúc chuẩn khác rỗng gần nhất của MAC. Chuỗi được chuẩn hóa theo quy tắc mới, nên có thể khác ở log cũ từng giữ ID 84 hoặc 255. CLI công bố digest riêng trong `fingerprint_hash` cùng phiên bản. `--json` tiếp tục xuất danh sách nhóm và giữ tên các trường thống kê hiện có. [MAC Tracking](MAC_TRACKING.md)

## Điểm tương đồng

Chỉ so sánh khi cả hai profile có trạng thái `usable`. CLI giải thích điểm bằng hai thành phần trên thang 0–1.

1. **Thành phần IE**, trọng số 70%. Chia số cặp chung cho tổng hợp hai danh sách, có tính số lần lặp từng cặp. Cặp đổi độ dài được tính là cặp khác.
2. **Thứ tự**, trọng số 30%. Chia độ dài dãy con chung dài nhất cho số cặp của danh sách dài hơn. Các cặp trong dãy con giữ nguyên thứ tự tương đối.

Các trọng số là quy ước nghiên cứu, chưa hiệu chỉnh trên RF có nhãn. Điểm `1` hoặc hash bằng nhau chỉ cho biết cấu trúc được giữ lại giống nhau. Nhiều thiết bị có thể cùng cấu trúc và một thiết bị có thể phát nhiều biến thể. Bước này dùng điểm để so sánh từng cặp, chưa đặt ngưỡng gán thiết bị.

## Ví dụ và lệnh chạy

```bash
.venv/bin/python -m research.ie_fingerprint --describe-ie '0:7,1:8,50:4,45:26,127:8,221:6'
.venv/bin/python -m research.ie_fingerprint --compare-ie \
  '0:7,1:8,50:4,45:26,127:8,221:6' '0:0,1:8,45:26,127:8,221:6'
.venv/bin/python -m research.ie_fingerprint path/to/raw.jsonl --report ie-report.json
.venv/bin/python -m pytest -q tests/test_ie_fingerprint.py tests/test_mac_tracking.py
```

Probe đầu tạo chữ ký `1:8,50:4,45:26,127:8,221:6` và hash `b91e8bd8374a149dfaf221fcfd106c40b8ee60dd3b2584fb8431e54d122a7f07`. Probe thứ hai thiếu IE 50. Hai profile có 4 cặp chung trên 5, giữ cùng thứ tự tương đối và đạt điểm **0,80**.

`ie-report.json` chứa kiểm kê IE trước ngưỡng RSSI. Danh sách nhóm trong báo cáo áp dụng ngưỡng RSSI đã chọn. Một IE vắng trong báo cáo chỉ cho biết nó không được quan sát trong tập Probe đã đọc.
