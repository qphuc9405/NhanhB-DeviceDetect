# Ước lượng cụm trong phòng từ RSSI

## Phần cứng và phạm vi

Lần kiểm tra này, `lsusb` và `serial.tools.list_ports` không thấy ESP32 qua USB/UART. Workspace cũng chưa có log RF gốc có nhãn. Điều này chỉ xác nhận những gì máy đang truy cập được. Sơ đồ dự án liệt kê ba vai trò ESP32, gồm TX/SoftAP, RX CSI và Probe sniffer. Pipeline Probe JSONL hiện dùng một sniffer mỗi phiên. Firmware Probe mặc định hopping kênh 1–13, dwell 3 giây, với cấu hình tùy chọn fixed kênh 6. Log thật cho biết `own_mac`, `scan_mode`, `channel` qua bản ghi `status` và RSSI theo từng Probe. Cấu hình đã nạp trên board thật cần đối chiếu với các trường này. [Firmware dự án](../../firmware/README.md) · [Cấu hình Probe](../firmware/sniffer/main/Kconfig.projbuild) · [Fixed kênh 6](../firmware/sniffer/sdkconfig.fixed)

Một vị trí thu chỉ cung cấp dấu hiệu cường độ và tính ổn định theo thời gian. Tường, cửa, hướng điện thoại và công suất phát có thể làm RSSI hành lang cao hơn RSSI trong phòng. Module xuất đặc trưng với log hopping, nhưng chỉ đánh giá trong/ngoài phòng với phiên **một sniffer, một kênh fixed**, có cửa sổ tham chiếu tương thích. Công cụ đọc Probe JSONL offline, dùng được với buổi đo Probe chạy song song CSI khi bố trí và kênh thu phù hợp. Định dạng CSI và cấu hình radio do pipeline CSI hiện tại quản lý.

## Đặc trưng và quyết định

Báo cáo chỉ phân loại các cụm đang `CONFIRMED` trong presence replay. Cụm dùng lại `cluster_id` từ association offline. Các phép tính đọc các Probe đã được presence chấp nhận, gồm kiểm tra heartbeat, RSSI đầu vào, bản sao và gói đến muộn. Tại mốc báo cáo, lịch sử clustering vẫn là nguồn association. [Presence replay](PRESENCE_STATE_MACHINE.md) · [Mã ước lượng](../research/in_room.py)

| Trường | Cách tính mặc định |
|---|---|
| `median_rssi_dbm` | Median của các median RSSI trong từng bin 5 giây ở cửa sổ 30 giây gần nhất. Mỗi bin đóng góp một giá trị. |
| `rssi_mad_db` | Median độ lệch tuyệt đối của median từng bin so với median toàn cửa sổ. |
| `observation_count`, `observation_ratio` | Số bin có Probe và tỷ lệ trên tổng số bin theo thời gian. `probe_count` ghi riêng số Probe hợp lệ để kiểm tra burst. |
| `last_seen_s` | Thời điểm Probe gần nhất trong cửa sổ, theo giây của phiên replay. |
| `recent_shift_db` | Mức đổi lớn nhất khi so median nửa đầu với median nửa gần và với bin có Probe mới nhất. Cần ít nhất hai bin có Probe ở mỗi nửa. |

Mặc định yêu cầu đủ 30 giây heartbeat liên tục, ít nhất 4/6 bin có Probe, Probe cuối trong 7 giây, MAD tối đa 6 dB và dịch chuyển tối đa 8 dB. Số đếm queue drop hoặc serial error tăng trong `status` bắt đầu lại cửa sổ tin cậy. Thiếu coverage, đổi kênh, ít mẫu, nhiễu hoặc đổi vị trí đều có thể dẫn đến `location_unknown`.

Sau kiểm tra chất lượng, so sánh vector gồm median, MAD và tỷ lệ quan sát với các cửa sổ tham chiếu. Khoảng cách là trung bình ba sai khác tuyệt đối đã chuẩn hóa theo `rssi_scale_db`, `mad_scale_db` và `ratio_scale`, mặc định lần lượt là 8 dB, 4 dB và 0,25. Kết quả cần ít nhất hai phiên tham chiếu gần thuộc phía được chọn, một khoảng cách gần nhất tối đa `0.50`, phía đối lập nằm ngoài vùng bảo vệ `0.65` và độ chênh điểm tối thiểu `0.25`. Khi hai phía có vùng bằng chứng chồng lấn, giữ `location_unknown`. Score `1 / (1 + inside_distance)` là **heuristic tương đồng**, chưa hiệu chuẩn thành xác suất.

| Nhãn cho cụm `CONFIRMED` | Bộ đếm |
|---|---|
| `in_room_confirmed` | `estimated_in_room_count`, số cụm được heuristic chấp nhận là trong phòng. |
| `outside_likely` | `outside_likely_count`, số cụm có mẫu gần phía ngoài. |
| `location_unknown` | `location_unknown_count`, số cụm thiếu điều kiện hoặc có bằng chứng không phân tách được. |

Ba bộ đếm cộng thành `confirmed_count` của báo cáo. Ưu tiên độ chính xác có thể làm giảm số cụm trong phòng được chấp nhận. Nếu `observation_valid` là `false`, giá trị 0 không chứng minh phòng trống.

## Thu ground truth và tạo dữ liệu tham chiếu

1. **Cố định bố trí.** Chọn `setup_id` cho phòng, vị trí, độ cao và hướng sniffer. Ghi kênh fixed, MAC của sniffer theo `status`, trạng thái cửa, vật cản và phiên bản firmware. Nếu thu cùng CSI, giữ cấu hình kênh theo kế hoạch đo CSI. Bố trí hoặc kênh đổi cần một bộ tham chiếu tương ứng.
2. **Đánh nhãn từng vị trí.** Mỗi lượt dùng một thiết bị thử nghiệm đã biết và ghi vùng thật theo đồng hồ người quan sát. Thu đủ `inside_near`, `inside_far`, `inside_boundary` (phía trong sát cửa/tường), `hallway`, và `outside_boundary` (sát cửa/tường phía ngoài). Thử nhiều model, hướng đặt, trạng thái cửa và lượt thu riêng. Ghi các đoạn di chuyển để kiểm thử abstention. Chỉ đưa đoạn nằm ổn định hoàn toàn trong một vùng vào bộ tham chiếu.
3. **Xuất cửa sổ cùng quy tắc.** Dùng CLI dưới đây với `--until` ở cuối từng đoạn ổn định. Chọn cụm đã đối chiếu với thiết bị thử nghiệm và chỉ dùng hàng có `reference_eligible: true`. Mỗi vùng cần ít nhất ba cửa sổ không chồng lấn từ ít nhất hai phiên độc lập theo mặc định. Gán `session_id`, `window_end_s`, `zone` và chép ba giá trị từ `features` vào file tham chiếu. Giữ cùng cấu hình cửa sổ, lọc RSSI, presence và clustering khi thu tham chiếu và khi đánh giá.
4. **Đánh giá bằng phiên giữ lại.** Chốt ngưỡng trên tập phát triển rồi chạy trên phiên và thiết bị giữ lại. Báo số cụm ngoài bị tính nhầm vào phòng, precision của `in_room_confirmed`, tỷ lệ phát hiện cụm thật trong phòng và tỷ lệ `UNKNOWN`. Đối chiếu với việc đếm mọi cụm `CONFIRMED` và đếm theo một ngưỡng RSSI trên cùng phiên. So theo nhóm gần, xa, sát cửa và hành lang. Tăng vùng bảo vệ hoặc biên độ phân tách khi tỷ lệ false positive vượt yêu cầu của buổi thử.

Ví dụ định dạng `calibration.json` với một hàng minh họa. Cần bổ sung đủ các vùng và phiên trước khi module gán nhãn.

```json
{
  "version": "in-room-reference-v1",
  "setup_id": "room-a-fixed-6",
  "sniffer_mac": "02:00:00:00:00:ff",
  "channel": 6,
  "window_s": 30,
  "bin_s": 5,
  "rssi_min": -127,
  "samples": [
    {
      "session_id": "near-trial-01",
      "window_end_s": 60,
      "zone": "inside_near",
      "features": {"median_rssi_dbm": -53, "rssi_mad_db": 2, "observation_ratio": 1}
    }
  ]
}
```

## Chạy kiểm tra và báo cáo

```bash
.venv/bin/python -m research.in_room path/to/raw.jsonl --setup-id room-a-fixed-6 --until 60 --output features.json
.venv/bin/python -m research.in_room path/to/raw.jsonl --setup-id room-a-fixed-6 --calibration calibration.json --until 60 --output in-room.json
.venv/bin/python -m pytest -q tests/test_in_room.py
```

Nếu bỏ `--until`, lệnh lấy mốc capture cuối trước `session_stopped`, hoặc bản ghi cuối khi file không có mốc dừng. `--config` đọc JSON với các trường trong `InRoomConfig`, ví dụ `{"min_observation_ratio": 0.8, "min_class_margin": 0.35}`. `--presence-config` và `--clustering-config` chọn ngưỡng tương ứng. Khi thiếu tham chiếu hoặc bố trí không khớp, có thể dùng báo cáo để thu đặc trưng, với kết quả vị trí `location_unknown`.
