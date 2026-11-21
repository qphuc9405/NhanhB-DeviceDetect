# Theo dõi MAC từ Probe Request

`research.stream.Stream` dùng lại bảng `audit` để theo dõi địa chỉ MAC nguồn đã chuẩn hóa. Live, demo, replay và đánh giá offline đi qua cùng `Stream`. Bảng chẩn đoán ghi nhận Probe ở đầu vào, kể cả gói yếu, gói RF retry và gói nhận lúc heartbeat gián đoạn. [Stream](../research/stream.py) · [Collector](../research/collector.py)

## Dữ liệu theo MAC

| Trường API | Ý nghĩa |
|---|---|
| `mac`, `first_seen_s`, `last_seen_s` | MAC nguồn và thời điểm quan sát đầu/cuối của mục đang được giữ, tính theo đồng hồ xử lý của nguồn. |
| `channel`, `rssi_last` | Kênh và RSSI dBm của Probe gần nhất. `rssi` vẫn là tên tương thích của `rssi_last`. |
| `rssi_history` | Tối đa 16 mẫu gần nhất, từ cũ đến mới. API chẩn đoán còn trả thời điểm xử lý, `ts_us` gốc, kênh và lý do xử lý từng mẫu. |
| `probe_count` | Số Probe riêng biệt đã cập nhật mục trong vòng đời hiện tại. `received` trong API chẩn đoán có cùng giá trị. |
| `fingerprint_id` | Chuỗi IE đã chuẩn hóa gần nhất có thể sử dụng. Giá trị là `null` khi chưa có chữ ký dùng được. Hai MAC cùng chữ ký vẫn có hai mục riêng. Xem [thiết kế IE fingerprint](IE_FINGERPRINT_DESIGN.md) để biết quy tắc chuẩn hóa. |

`GET /api/probe/state` trả tối đa 50 mục mới nhất trong `recent_sources`. `GET /api/probe/diagnostics?mac=<địa-chỉ>` trả chi tiết của một mục trong bộ đệm.

## Bản sao và thời gian

- Bản sao JSONL được nhận diện bằng MAC, `boot_id`, `seq`, `ts_us`, kênh, RSSI, `frame_seq`, cờ `retry` và IE sau khi parse. Bộ nhớ giữ tối đa 4.096 bản ghi Probe riêng biệt gần nhất. Bản sao tìm thấy trong cửa sổ này chỉ tăng `quality.duplicate_probe_records`. Cờ `retry` hoặc trùng `frame_seq` riêng lẻ vẫn có thể là quan sát RF hợp lệ.
- File `raw.jsonl` lưu đầu vào đã qua parser để đối chiếu. Tracker, CLI fingerprint và báo cáo RSSI/heatmap bỏ bản sao trong cửa sổ trên khi tính thống kê. Các bản ghi có dữ liệu RF riêng vẫn có thể dùng để phân tích IE, RSSI và burst.
- Live dùng thời điểm laptop nhận trên đồng hồ monotonic. Replay và offline dùng `host_elapsed_s` khi có. Probe đến trễ được xử lý tại mốc hiện tại nếu thời gian ghi thấp hơn mốc đã xử lý. Log UART kiểu cũ dùng `ts_us` tương đối theo lần khởi động và giữ thứ tự bản ghi. Timestamp trên board vẫn có trong gói để phân tích burst. Timestamp board sai định dạng và thời gian host âm hoặc không hữu hạn bị bỏ qua khi đọc.

## Hết hạn và thống kê

`mac_expiry_s` mặc định **120 giây**, nhận giá trị 1–3.600 giây. Đổi trong mục **Nâng cao → Tham số nghiên cứu** khi nguồn đang ngắt, hoặc trong `configs/probe.json`. Khi xử lý bản ghi tiếp theo hoặc đọc trạng thái, tracker giải phóng các mục có thời gian kể từ lần thấy cuối vượt ngưỡng, cùng lịch sử RSSI của chúng. Một Probe mới sau đó bắt đầu vòng đời mới. `max_sources` giới hạn số mục còn hiệu lực. Nếu bảng vẫn đầy sau khi dọn, `quality.audit_capacity_drops` ghi nhận lượt không thể thêm mục.

| Chỉ số trong `/api/probe/state` | Phạm vi |
|---|---|
| `raw_mac_count` | Số MAC phân biệt trong tối đa 4.096 Probe riêng biệt gần nhất mà tracker đã đọc, gồm cả MAC bị lọc hoặc không được thêm do bảng đầy. Chỉ số theo cửa sổ bản ghi này có thể giảm khi nhận thêm Probe. |
| `active_mac_count` | Số mục còn giữ trong bộ đệm theo TTL tại thời điểm truy vấn. |
| `expired_mac_count` | Tổng lượt thu hồi vì TTL trong vòng đời của `Stream`. Nếu một MAC hết hạn, quay lại rồi hết hạn lần nữa, bộ đếm tăng hai lần. |

Mỗi `Stream` mới bắt đầu với các chỉ số bằng 0. Các số này mô tả quan sát địa chỉ. **MAC hết hạn chỉ cho biết bộ đệm đã vượt thời gian chờ. Thiết bị vật lý có thể vẫn ở trong phòng.**

Thiết kế tham khảo thao tác upsert MAC, cập nhật RSSI/thời điểm thấy cuối, thu hồi theo TTL và thống kê số mục hiện hành từ `stalss/passive-wifi-crowd-counter`. PBL3 dùng bảng có thứ tự theo `last_seen_s` để thu hồi mục cũ nhất trước. [Bảng băm tham chiếu](https://github.com/stalss/passive-wifi-crowd-counter/blob/9547d93be6a6cb56bdb4bd34796ac78f56dea633/main/hash_table.c) · [Thống kê tham chiếu](https://github.com/stalss/passive-wifi-crowd-counter/blob/9547d93be6a6cb56bdb4bd34796ac78f56dea633/main/stats.c)

## Chạy kiểm thử

Từ thư mục `wifi-device-sherlock`, dùng Python 3.12.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q tests/test_mac_tracking.py
.venv/bin/python -m pytest -q
```

Bộ test tracker dùng Probe tổng hợp và kiểm tra cập nhật MAC, MAC mới, MAC quay lại, chữ ký trùng, bản sao, timestamp đến trễ và giới hạn bộ nhớ. Bộ test đầy đủ có ca UART ảo dùng POSIX PTY trên Linux.
