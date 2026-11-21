# Xác nhận hiện diện theo Device Cluster

## Đối chiếu Sherlock

Sherlock gốc tạo bảng Probe theo MAC với khe 60 giây. Một khe có Probe đóng góp một lần cho bộ đếm xác nhận. Khe trống liên tiếp có thể hủy ứng viên hoặc xác nhận kết thúc quan sát. Mã PHP của thí nghiệm dùng 7 khe xác nhận vào, 4 khe trống hủy ứng viên và 7 khe trống xác nhận ra. Sự kiện lưu khe bắt đầu nghi ngờ và khe đủ bằng chứng. Các giá trị đó thuộc cấu hình của thí nghiệm tham chiếu. [Tạo bảng khe](https://github.com/luizsoliveira/sherlock/blob/738a896258d9446717c5035bb8b5faae18f2adc4/05-04-2018-Exp01/ranking.php#L46) · [Xác nhận hiện diện trong PHP](https://github.com/luizsoliveira/sherlock/blob/738a896258d9446717c5035bb8b5faae18f2adc4/05-04-2018-Exp01/quantifyPeopleBySlots.php#L7)

`Sherlock` trong PBL3 đã có AT/WT/DT theo MAC, chốt ở cuối khe và báo sự kiện tại mốc đủ bằng chứng. Bước này thêm replay offline riêng theo `cluster_id`. Nó dùng nguyên kết quả association của `device_clustering`, đặt ngưỡng theo giây và tiếp tục cung cấp `--mac-only` để so sánh. [Máy trạng thái theo MAC](ALGORITHM.md) · [Clustering](DEVICE_CLUSTERING.md) · [Mã replay](../research/presence.py)

## Trạng thái và sự kiện

| Trạng thái | Điều kiện và ý nghĩa |
|---|---|
| `CANDIDATE` | Probe hợp lệ đầu tiên tạo ứng viên. Cần đủ quan sát cách nhau theo `min_observation_spacing_s` trong `observation_window_s` để xác nhận. |
| `CONFIRMED` | Đủ quan sát trong cửa sổ, hoặc có Probe hợp lệ khi đang `STALE`. Một burst dày chỉ đóng góp một quan sát trong khoảng cách tối thiểu. |
| `STALE` | Cụm từng được xác nhận nhưng vượt `stale_timeout_s` từ Probe cuối hoặc bị gián đoạn thu. Probe hợp lệ trước khi hết hạn đưa cụm về `CONFIRMED`. |
| `ABSENT` | Hết `departure_timeout_s` kể từ Probe cuối đã xác nhận, hoặc ứng viên im lặng hết `observation_window_s`. Đây là hết thời hạn bằng chứng quan sát. Một thiết bị thực có thể vẫn ở trong phòng. Probe sau khi hết hạn bắt đầu lại ở `CANDIDATE`. |

Các timeout đến hạn được xử lý trước Probe ở cùng timestamp. Xác nhận lần đầu được ghi khi nhận đủ quan sát. Các Probe hợp lệ đến dày có thể cập nhật mốc thấy cuối dù chưa đủ khoảng cách để đóng góp thêm một quan sát xác nhận. Để tránh burst bị chia thành nhiều lần do hàng đợi, khoảng cách phải đạt ngưỡng cả theo `ts_us` trên board lẫn đồng hồ quan sát của replay.

MAC đổi địa chỉ vẫn tiếp tục trạng thái và lịch sử xác nhận nếu hai alias cùng `cluster_id` trong kết quả clustering. Alias ở cụm khác có cửa sổ riêng. `mac_expiry_s` quản lý bộ đệm chẩn đoán theo MAC. Presence quản lý vòng đời bằng chứng theo cụm bằng các ngưỡng dưới đây.

## Replay và giới hạn quan sát

- Báo cáo có hai đồng hồ. `t_s` là thời điểm của replay. `observation_t_s` chỉ tăng trong phạm vi heartbeat `status` báo radio hoạt động. Khi heartbeat quá hạn, board đổi boot, radio ngừng hoặc nhận control record, các cụm đã xác nhận chuyển `STALE`; cửa sổ xác nhận đang chờ bị xóa. Thời gian mất coverage không cộng vào timeout. Sau khi có heartbeat trở lại, `STALE` cần Probe mới để khôi phục.
- Bản sao JSONL được lọc theo khóa bản ghi của MAC Tracker. Probe phải thuộc alias đã biết, qua RSSI dùng cho clustering, và khác MAC của board. Probe cũ hơn watermark capture quá `late_tolerance_s`, hoặc có timestamp capture không mới hơn Probe đã dùng của cùng cụm trong đoạn thu, chỉ tăng `late_observation_count`. Nó không khôi phục `STALE` hoặc gia hạn timeout.
- Log chỉ có Probe và thiếu `status` trả `observation_valid: false`. `probes_without_coverage` cho biết số Probe đủ điều kiện đầu vào nhưng thiếu coverage. Khi `observation_valid` là `false`, các bộ đếm mô tả trạng thái lưu giữ của replay. Coverage heartbeat là suy luận từ tín hiệu sniffer, vẫn có thể bỏ sót Probe do thiết bị im lặng hoặc do nhảy kênh.
- CLI chạy clustering trên toàn bộ file, rồi phát lại theo ánh xạ alias đã cố định. `--until` cắt replay theo mốc giây và không tạo thêm thời gian sau EOF. Ánh xạ đó có thể dùng bằng chứng xuất hiện sau mốc `--until`; vì vậy dùng kết quả để phân tích offline. Để kiểm tra timeout, log cần các heartbeat thực sự sau Probe cuối.
- `events` ghi `cluster_id`, trạng thái trước/sau, hai mốc thời gian và `reason`. Thu hồi mục hết thời gian lưu xuất sự kiện `retention_expired` với `to_state: null`. `candidate_count`, `confirmed_count`, `stale_count` và `absent_count` là số mục còn giữ ở mốc báo cáo. Chúng là số cụm quan sát được, chưa phải số thiết bị vật lý đã được đối chứng.

## Ngưỡng cấu hình

| Khóa JSON | Mặc định | Cách dùng |
|---|---:|---|
| `observation_window_s` | 30 s | Cửa sổ xác nhận trượt và hạn im lặng của ứng viên. |
| `min_observation_spacing_s` | 5 s | Khoảng cách tối thiểu giữa hai quan sát đóng góp xác nhận. |
| `confirmation_threshold` | 3 | Số quan sát cần thiết, tối thiểu 2. Cửa sổ phải dài hơn `(threshold − 1) × spacing`. |
| `stale_timeout_s` | 20 s | Thời gian quan sát kể từ Probe cuối trước khi đánh dấu `STALE`. |
| `departure_timeout_s` | 60 s | Tổng thời gian quan sát kể từ Probe cuối trước khi hết hạn. Phải lớn hơn `stale_timeout_s`. |
| `heartbeat_timeout_s` | 5 s | Hạn coverage tính từ `status` hợp lệ cuối. |
| `late_tolerance_s` | 0,25 s | Mức lệch tối đa so với watermark capture trong cùng đoạn thu. |
| `absent_retention_s` | 120 s | Thời gian quan sát giữ mục `ABSENT` trước khi thu hồi. |
| `max_clusters`, `max_recent_events` | 2000, 512 | Giới hạn mục được giữ và lịch sử gần trong tracker. CLI offline thu toàn bộ sự kiện vào báo cáo. `capacity_drops` đếm lượt không thể mở mục khi đầy. |

Các mặc định là giá trị khởi đầu kỹ thuật, chưa được hiệu chuẩn trên RF. Chọn khoảng cách quan sát theo phân bố burst và vòng quét kênh của buổi thu, rồi đo độ trễ xác nhận và số timeout nhầm trên các phiên có nhãn độc lập. `cleaned_up_count` theo dõi số mục đã thu hồi.

## Vận hành

Từ thư mục `wifi-device-sherlock`, với Python 3.12 và các gói trong `requirements-dev.txt`:

```bash
.venv/bin/python -m research.presence path/to/raw.jsonl --output presence.json
.venv/bin/python -m research.presence path/to/raw.jsonl --mac-only --output presence-mac.json
.venv/bin/python -m research.presence path/to/raw.jsonl --config presence-config.json --until 45
.venv/bin/python -m pytest -q tests/test_presence.py
```

Ví dụ `presence-config.json` có thể chứa `{"observation_window_s": 45, "min_observation_spacing_s": 8, "confirmation_threshold": 3, "stale_timeout_s": 30, "departure_timeout_s": 90}`. Dùng `--clustering-config` để chọn cùng cấu hình association với báo cáo clustering. Dùng cùng file và ngưỡng khi đối chiếu `--mac-only` để xem hiệu ứng của việc giữ `cluster_id` qua đổi MAC.
