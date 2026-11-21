# Ước lượng thiết bị WiFi từ Probe Request

`research.device_clustering` chạy offline trên một phiên JSONL. Nó dùng cấu trúc `MacObservation` và bộ khử bản sao của MAC Tracker, cùng profile và similarity `ie-id-length-v1`. Phiên bản đầu ra là `device-clustering-v1`. Danh sách nhãn thiết bị chỉ được dùng để chấm kết quả kiểm thử sau khi thuật toán đã trả báo cáo. [MAC Tracking](MAC_TRACKING.md) · [IE Fingerprint](IE_FINGERPRINT_DESIGN.md)

## Đầu vào và đầu ra

Mỗi địa chỉ MAC xuất hiện trong Probe hợp lệ và qua `rssi_min` tạo một alias ứng viên. Báo cáo giữ thời điểm quan sát đầu và cuối, thống kê RSSI theo kênh, profile IE trội nếu đủ mẫu và lịch sử quyết định. `cluster_id` được cấp theo thứ tự capture và giữ khi alias mới được thêm vào cụm. Các ID có phạm vi một lượt phân tích. Thêm dữ liệu vào phiên rồi chạy lại có thể thay đổi kết quả, vì các Probe đến sau được dùng để phát hiện chồng lấn.

| Trường | Ý nghĩa |
|---|---|
| `raw_mac_count` | Số MAC phân biệt trong cả phiên, sau parser, khử bản sao và ngưỡng RSSI. Đây là tổng theo phiên. API MAC Tracking sử dụng cửa sổ 4.096 Probe cho chỉ số cùng tên. |
| `inferred_cluster_count` | Số cụm ước lượng trong cả phiên. Mỗi alias chưa đủ bằng chứng ghép vẫn đóng góp một cụm riêng. |
| `clusters[].mac_aliases` | Danh sách MAC được gán vào cụm. Các báo cáo có chứa MAC nguồn, nên dùng cùng quy tắc lưu trữ và chia sẻ như log raw. |
| `first_seen_s`, `last_seen_s` | Thời điểm xử lý sớm nhất và muộn nhất của các alias. Thứ tự association và tính gap dựa trên `ts_us` capture trong cùng đoạn thu, nên Probe đến trễ vẫn góp phần phát hiện chồng lấn. |
| `fingerprint_profile`, `rssi_statistics` | Profile IE trội và số mẫu, median, biên độ RSSI theo kênh của từng alias. |
| `confidence` | `uncalibrated_heuristic`. Score của cụm là điểm thấp nhất của các lần ghép được chấp nhận, hoặc `null` khi cụm chỉ có một MAC. |
| `association_history` | Quyết định cho từng alias, bằng chứng và lý do theo từng cụm ứng viên, cùng ứng viên kế tiếp cạnh tranh khi có. |

## Quy tắc association

1. Tìm ứng viên trong cùng đoạn thu, cách nhau tối đa **30 giây** hoặc có thời gian quan sát chồng lấn. Đổi `boot_id` hoặc bản ghi điều khiển bắt đầu đoạn mới. Association dùng `ts_us` trong từng đoạn. Khoảng quan sát của một alias chạy từ Probe đầu đến Probe cuối trong đoạn đó, nên phát xen kẽ cũng có thể tạo bằng chứng chồng lấn.
2. **NON_MATCH** khi khoảng quan sát chồng nhau quá **50 ms** hoặc hai profile có đủ mẫu nhưng IE similarity dưới **0,55**. Chồng lấn nhỏ hơn vẫn chặn ghép. Quy tắc thời gian này ưu tiên tránh gộp nhầm và có thể tách các alias thực sự thuộc cùng thiết bị nếu chúng hoạt động xen kẽ.
3. **AMBIGUOUS** khi thiếu dữ liệu hoặc có cạnh tranh. Mặc định mỗi alias cần ít nhất **3 Probe** mang profile trội, profile đó chiếm ít nhất **60%** các Probe của alias và có ít nhất **3 ID IE phân biệt**. Profile có dấu hiệu bị cắt không được tính vào hỗ trợ này. Cần một kênh chung có ít nhất 2 mẫu RSSI mỗi alias. Chênh median trên kênh chung lớn hơn **12 dB** hoặc biên độ nội bộ lớn hơn **18 dB** giữ quyết định ở `AMBIGUOUS`.
4. **MATCH** khi có một handoff theo thời gian, IE similarity ít nhất **0,85**, điểm tổng ít nhất **0,82**, và mọi cặp giữa alias mới với các alias trong cụm đều đạt `MATCH`. Cụm lấy điểm cặp thấp nhất. Một cụm cạnh tranh hoặc alias kế tiếp chồng lấn có điểm cách dưới **0,06** giữ quyết định ở `AMBIGUOUS`. Chuỗi A–B–C phải kiểm tra cả A–C.

Điểm tổng gồm **55% IE similarity**, **20% gần nhau theo thời gian**, **20% mức nhất quán RSSI trên kênh chung**, **5% độ trùng tập kênh**. Điểm thời gian giảm tuyến tính theo gap. Điểm RSSI giảm tuyến tính theo chênh median lớn nhất trên các kênh đủ mẫu. Các trọng số và ngưỡng là heuristic chưa hiệu chuẩn. Điểm không phải xác suất hoặc độ chính xác đo được trên RF thật.

## Bảng kiểm thử over-merge và over-split

Đơn vị là **cặp alias** có nhãn trong fixture tổng hợp. Over-merge đếm cặp thuộc hai thiết bị nhưng cùng cụm. Over-split đếm cặp thuộc cùng thiết bị nhưng khác cụm. Định nghĩa ca và nhãn nằm trong [test_device_clustering.py](../tests/test_device_clustering.py).

| Tình huống tổng hợp | Clustering over-merge | Clustering over-split | MAC-only over-merge | MAC-only over-split |
|---|---:|---:|---:|---:|
| Một thiết bị đổi qua 3 MAC, handoff rõ | 0 | 0 | 0 | 3 |
| Hai thiết bị cùng fingerprint, quan sát chồng lấn | 0 | 0 | 0 | 0 |
| Một thiết bị đổi MAC sau khoảng vắng 12 giây | 0 | 0 | 0 | 1 |
| Một thiết bị đổi MAC sau khoảng vắng 40 giây | 0 | 1 | 0 | 1 |
| Hai thiết bị phát nối tiếp, IE, RSSI và kênh giống nhau | 1 | 0 | 0 | 0 |
| Hai ứng viên tiền nhiệm cạnh tranh | 0 | 1 | 0 | 1 |
| Hai ứng viên kế tiếp chồng lấn | 0 | 1 | 0 | 1 |

Các ca khác kiểm tra RSSI dao động, IE thiếu hoặc lặp, bản ghi đến trễ, trùng JSONL, đổi boot, và chuỗi A–B–C. Bảng này xác nhận hành vi trên fixture. Hiệu quả ngoài thực tế cần tập RF gán nhãn độc lập. Trường hợp hai thiết bị phát nối tiếp trong điều kiện giống nhau vẫn có thể bị gộp nhầm. Tần suất Probe thấp hoặc nhảy kênh cũng có thể làm một thiết bị bị tách thành nhiều cụm.

## Chạy clustering và đối chứng MAC-only

```bash
.venv/bin/python -m research.device_clustering path/to/raw.jsonl --output clusters.json
.venv/bin/python -m research.device_clustering path/to/raw.jsonl --mac-only --output mac-only.json
.venv/bin/python -m pytest -q tests/test_device_clustering.py
```

`--config path/to/clustering.json` đọc các tham số từ JSON. Ví dụ `{"enabled": true, "rssi_min": -65, "max_gap_s": 20, "match_threshold": 0.88}`. Dùng `"enabled": false` hoặc `--mac-only` để mỗi MAC có một cụm baseline. Chạy hai chế độ trên cùng log và cùng `rssi_min` để so sánh. Bước này chỉ tạo báo cáo offline. Count theo phiên không đại diện cho số thiết bị đồng thời trong phòng.
