# Dashboard nhánh phát hiện thiết bị

Cơ sở: `Dac_ta_dinh_dang_du_lieu (2).md`, mục 3.3, 3.4, 4.3–4.5, 6 và 7; đối chiếu với PROTOCOL.md và ALGORITHM.md của bản hiện tại.

## Bố cục thao tác

- **Kết nối & quan sát:** USB, demo có chủ đích, phòng/bố trí, bộ lọc RSSI, thời gian khe và AT/WT/DT; nguồn trong khe đang mở, số nguồn xác nhận, có/không có nguồn xác nhận; trạng thái từng MAC, RSSI, lần thấy cuối, tiến độ; heartbeat, kênh, queue drop, lỗi parser/serial, nối lại.
- **Ghi phiên & nhãn:** số thiết bị thật, thông tin thiết bị/OS/WiFi/màn hình, số người tùy chọn, ghi chú; bắt đầu, ghi nhãn mới, kết thúc. Hiển thị nhãn đã lưu riêng với bản nháp đang nhập. Kết thúc tự chuyển sang kết quả.
- **Kết quả đã lưu:** thông tin phiên, raw/nhãn/metadata; đánh giá ba thuật toán, coverage, MAE/bias/tỷ lệ đúng/PCC/MRE/MAE nhãn 0; độ trễ và số sự kiện chưa đạt; báo cáo JSON, timeline CSV; tạo và tải heatmap/bảng khe.
- **Nâng cao:** giữ công cụ phát lại phiên, cấu hình đầy đủ (gồm danh sách loại trừ), chẩn đoán MAC, dấu mốc, nhật ký thuật toán và phân tích chi tiết.

Mặc định không tạo nguồn giả hay số đếm minh họa. Nguồn lỗi/mất heartbeat hiển thị “—”. Tổng xác nhận lấy từ backend, gồm cả `present` và `departing`. Số nguồn trong khe đang mở dùng `n_sources_seen`, được tính sau bộ lọc, không thay bằng unique-window. Khe đang mở chưa phải bản xuất khe đã chốt.

## Đối chiếu với đặc tả nháp v0.1

| Nội dung | Đặc tả nháp | Bản hiện tại |
|---|---|---|
| Serial | BOOT/PRB/STAT dạng CSV | Packet JSONL, status heartbeat |
| MAC lưu trữ | SHA-256 với salt, 12 ký tự | MAC đầy đủ trong raw; chưa có bước băm |
| Dữ liệu phiên | data/raw/ID/*.csv | data/runtime/experiments/ID/*.jsonl và metadata.json |
| Nhãn | COUNT +/- suy ra people_manual | device_count và people_count tùy chọn, ghi giá trị tuyệt đối |
| Đầu ra nhánh | data/device/ID.csv theo mục 6 | timeline đánh giá và CSV quan sát theo khe; chưa cùng hợp đồng mục 6 |
| So sánh | people_manual | Báo cáo hiện dùng device_count; people_count được lưu riêng |
| RSSI | Chỉ ghi log | Có bộ lọc mở rộng tùy chọn; -127 là không cắt bổ sung |

Thay đổi này thiết kế lại giao diện theo nội dung cần quan sát của nhánh thiết bị, giữ giao thức đang chạy. Chưa triển khai chuyển đổi firmware, logger hoặc xuất dữ liệu theo hợp đồng nháp v0.1. Không gắn nhãn “MAC đã băm” hoặc khẳng định đã tương thích CSV khi chưa có triển khai.

## Chạy

Tại thư mục gốc: `./run.sh`, mở http://127.0.0.1:8000. Sau khi đổi giao diện cần `npm run build`; bản thay đổi này đã build sẵn trong môi trường làm việc. Khởi động lại server để nhận trường snapshot mới.
