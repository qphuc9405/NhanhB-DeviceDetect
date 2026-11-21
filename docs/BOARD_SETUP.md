# Cấu hình board sniffer tại máy này

Ngày thiết lập: 2026-11-14. ESP32-C3 qua USB Serial CH340 tại `/dev/ttyUSB0`.

Firmware `firmware/sniffer` được build bằng ESP-IDF v5.5.4, UART0 GPIO21/20,
460800 baud. Thu thụ động Probe Request trên WiFi 2.4 GHz, country VN,
hopping kênh 1–13, dwell 3000 ms/kênh. Không cần kết nối board vào AP.

## Máy trạng thái đang dùng

Cấu hình lưu tại `configs/probe.json`:

| Tham số | Giá trị |
|---|---|
| Khe quan sát | 60 giây |
| AT | 2 khe có Probe để xác nhận |
| WT | 2 khe trống liên tiếp để hủy ứng viên |
| DT | 3 khe thiếu quan sát để hết hiệu lực xác nhận |
| RSSI tối thiểu | −127 dBm: tắt cắt RSSI bổ sung, có thể đổi trên dashboard |
| Heartbeat timeout | 5 giây |

Đây là cấu hình thử ban đầu, chưa hiệu chỉnh theo phòng. Một vòng nhảy kênh
mất khoảng 39 giây. AT=2 yêu cầu hai khe có Probe, không bảo đảm sẽ xác nhận
sau đúng hai phút. Khi mất heartbeat, số đếm không còn hợp lệ.

Luồng: Probe → chốt khe → chờ xác nhận → đã xác nhận → thiếu quan sát → hết hiệu lực.
Nguồn có Probe trở lại khi đang thiếu quan sát được chuyển về đã xác nhận.
Xem `DAC_TA_DU_AN.md` để biết quy ước đếm khe và sự kiện chính xác.

## Sử dụng

- Mở http://localhost:5173 (bản phát triển) hoặc http://127.0.0.1:8000 (bản đã build).
- Dashboard không tự bật demo; chỉ phát mô phỏng khi bấm Chạy demo nhanh.
- Sau khi khởi động lại backend: vào Kết nối & quan sát, chọn `/dev/ttyUSB0`, Kết nối USB.
- Xem bảng Nguồn đang theo dõi để kiểm tra trạng thái từng MAC.
- Muốn lưu thực nghiệm: nhập phòng, mô tả và số thiết bị thật tại Ghi phiên & nhãn,
  rồi Bắt đầu ghi. Không có nhãn thực tế được tạo tự động khi thiết lập board.
- Thay đổi AT/WT/DT: kết thúc phiên, ngắt nguồn trong giao diện, chỉnh cấu hình
  trong công cụ nâng cao rồi kết nối lại. Không cần nạp lại firmware cho AT/WT/DT.

## Bản sao lưu và firmware

Firmware cũ đã được đọc toàn bộ 4 MiB trước khi nạp:
`data/runtime/hardware-backups/esp32c3-before-sniffer-20261114.bin`.
SHA-256 nằm trong file `.sha256` cùng tên. Giữ bản sao này ở máy cục bộ.

Các binary sniffer đã build và sdkconfig được lưu tại `data/runtime/hardware-setup/`.
ESP-IDF gặp lỗi shell khi build trực tiếp trong đường dẫn dự án có dấu cách và
ngoặc `(1)`, nên bản build lần này dùng bản sao nguồn tại
`/tmp/sherlock-sniffer-build-20261114/sniffer`. Khi build lại, dùng đường dẫn
không có dấu cách/ngoặc; thư mục `/tmp` có thể bị dọn khi khởi động lại máy.

## Điều chỉnh phạm vi bằng RSSI

Trong Kết nối & quan sát, mở Điều chỉnh phạm vi bằng RSSI, chọn ngưỡng rồi Áp dụng bộ lọc. Không cần
ngắt USB hay nạp lại firmware. Khi đang ghi, chọn lưu phiên và tiếp tục phiên mới
để mỗi phiên có một cấu hình RSSI nhất quán. Đổi ngưỡng sẽ xóa suy luận cũ và
xác nhận lại các MAC; bộ đếm lọc bắt đầu lại. RSSI lọc Probe trước cả Sherlock,
unique-MAC và timeout; raw phiên vẫn giữ cả Probe yếu để đối chiếu.
