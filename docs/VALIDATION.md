# Kiểm thử v1.1 — bản chỉ phát hiện thiết bị — 09/11/2026

| Hạng mục | Kết quả |
|---|---|
| Unit/integration Python | 48 passed |
| JSONL đúng node, MAC, RSSI, channel, sequence, timestamp; log/dòng lỗi | Đạt |
| AT/WT/DT, khe đầu, burst không tăng số khe, quay lại trước hết hạn | Đạt |
| Giới hạn nguồn, im lặng dài, triệt retry, RSSI/exclusion tùy chọn | Đạt |
| Không có heartbeat / radio inactive / reboot | Đạt; không trả số0 giả |
| Thu serial và ghi phiên/nhãn qua UART ảo POSIX PTY | Đạt |
| API guards, lưu cấu hình, replay gắn nhãn synthetic | Đạt |
| Evaluate, inspect, tải CSV/JSON/SVG, chống đường dẫn tùy ý | Đạt |
| Cùng input, cùng clock: online engine và offline timeline | Đạt |
| Manifest development/test trùng bị từ chối | Đạt |
| Đối chiếu bộ đếm PHP bằng oracle độc lập | 1000 khe ngẫu nhiên × 4 cấu hình; đạt |
| Chẩn đoán MAC, marker AP, journal, retry flag và reconnect cùng boot | Đạt |
| TypeScript + Vite build | Đạt |
| Shell setup/run/flash | bash -n đạt |
| Firmware ESP-IDF5.5.4 / ESP32-C3 | Giữ nguyên từ bản trước; build/link trước đó 757488 bytes, không build lại trong cập nhật này |
| Giao diện trực quan trên trình duyệt | Chưa xác nhận trong môi trường này |
| Flash và thu điện thoại thật | Chưa thực hiện cho bản này |

Firmware dùng countryVN, hopping1–13, dwell3000ms, UART921600; CMake3.30.9,
riscv32-esp-elf14.2.0. Build chạy COMPONENTS=main, IDF_COMPONENT_MANAGER=0 vì chỉ
có component tích hợp, không sửa mã SDK. Hash/cấu hình: build-manifest.json.

Dữ liệu trong data/synthetic-probe-demo do script tạo để kiểm tra phần mềm.
Chỉ số của nó không đo độ chính xác RF hay thiết bị thật. Không có mô hình học
máy hoặc kết quả đếm người. Không suy rộng hiệu quả Sherlock từ test tổng hợp.

Cần người triển khai hoàn thành các phép đo trong PLAN.md trước khi báo cáo
khả năng phát hiện, độ trễ và sai số trên phần cứng thật.
