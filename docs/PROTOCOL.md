# Giao thức dữ liệu

UTF-8 JSON Lines, một object/dòng. Serial460800baud, firmware không thêm prefix
log vào JSON. Boot log bị parser bỏ qua và đếm dòng lỗi, không coi như Probe.

Mọi gói: v=1, type, node=sniffer, boot_id, ts_us (microseconds từ boot), seq.

| type | Nội dung |
|---|---|
| probe | source_mac, rssi(dBm), channel, frame_seq, retry |
| status | capture_active, own_mac, channel, probe_seen/dropped, invalid, serial_errors, bytes_written, serial_baud, sniffer_enabled, scan_mode, dwell_ms |
| channel | channel, dwell_ms, timestamp sau khi đổi kênh |

Chỉ sao chép header cần thiết trong callback WiFi. Task riêng xuất serial và
đổi kênh. Probe được xếp hàng trước đổi kênh có thể được xuất sau channel event;
channel trong từng Probe là metadata nhận thực tế, không suy ra từ thứ tự serial.
seq tăng lúc output, không phải sequence number của riêng một thiết bị.
frame_seq là 12-bit của frame 802.11, không phải danh tính ổn định.

Laptop ghi wrapper: packet, host_time (UTC ISO8601), host_elapsed_s (monotonic
so với đầu phiên), source=serial. Replay không sửa đồng hồ board. Truth là
step function: t_s, device_count, people_count(optional), notes. Giá trị hiện
hành kéo dài đến mốc tiếp theo. Không dùng count của thuật toán để tự gán truth.

Metadata lưu config, firmware heartbeat ban đầu, layout, devices, notes,
started_at, ended_at và số records. File chưa ended_at không được replay/evaluate
qua API. Thu có gap vẫn giữ raw, đánh giá ghi coverage và reset xác nhận khi gap.

Schema máy đọc: packet.schema.json. API tại /docs:

- GET /api/ports, /api/health
- GET /api/probe/state, /config, /sessions, /replays
- PUT /api/probe/config (chỉ idle)
- POST /api/probe/connect, /disconnect, /replay
- POST /api/probe/sessions/start, /sessions/stop, /truth
- POST /api/probe/sessions/{id}/evaluate, /inspect
- GET /api/probe/sessions/{id}/files/{kind}, whitelist: raw/truth/metadata/report/timeline/inspection/slots/heatmap

Backend chỉ bind127.0.0.1. Chưa có auth nhiều người dùng. Không công khai server.

## v1.1 — host control và chẩn đoán

Raw có thể có wrapper control={kind:serial_connected/serial_disconnected/session_stopped},
host_elapsed_s, host_time, source. Đây là sự kiện của laptop, không phải packet
của ESP32. Marker thao tác người dùng lưu markers.jsonl; thuật toán causal live
lưu algorithm-events.jsonl; bản tính lại lưu evaluation/algorithm-events.jsonl.
GET diagnostics và POST markers/diagnose được mô tả trong OpenAPI.
