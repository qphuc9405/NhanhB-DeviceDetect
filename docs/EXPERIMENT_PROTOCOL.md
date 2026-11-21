# Quy trình kiểm chứng phát hiện thiết bị WiFi vật lý

Đơn vị ground truth là **thiết bị thử nghiệm thực sự ở trong phòng tại thời điểm quan sát**. Đếm theo mốc ra/vào của người quan sát độc lập. Ghi riêng người, MAC, Presence và nhãn vị trí nếu có. Công cụ tính các dự đoán từ Probe Request, sau đó mới so với nhãn.

## 1. Chuẩn bị trên Ubuntu và ESP-IDF

1. Dùng Python 3.12, Node.js từ 22 và môi trường ESP-IDF 5.5.4 của dự án. Cài bằng `bash scripts/setup.sh` rồi chạy `bash run.sh`. Trong dashboard `http://127.0.0.1:8000`, chọn `/dev/ttyUSB0` hoặc cổng ESP32 thực tế, 460800 baud và chờ `LIVE` có heartbeat. Kiểm tra `GET /api/probe/state` cho `scan_mode`, `channel`, `dwell_ms`, `probe_dropped` và `serial_errors`. [Dashboard](DASHBOARD_GUIDE.md) · [Board](BOARD_SETUP.md)
2. Ghi mã bố trí `setup_id`, phiên bản firmware/ESP-IDF, vị trí và độ cao sniffer, kênh, điều kiện cửa, vật cản và model/OS thiết bị. Lưu các điều kiện cùng ghi chú phiên. Để so cả A/B/C trên cùng tập, thu bằng một sniffer cố định trên kênh đã dùng cho tham chiếu trong phòng. Thu hopping thành nhóm cấu hình riêng. C có thể trả `N/A` với hopping hoặc khi không có tham chiếu phù hợp. [Tham chiếu vị trí](IN_ROOM_ESTIMATION.md)
3. Đặt `batch_id` theo đợt thu độc lập trước khi ghi. Các lần cắt, lặp liền nhau hoặc các đoạn trong cùng buổi theo cùng bố trí và người tham gia nên ở cùng batch. Chia batch thành `development` và `test` trước khi chọn tham số. Giữ cả các ca im lặng, lỗi thu hoặc thiếu quan sát để coverage phản ánh điều kiện đã định.

Nếu đã có `.venv` từ phiên bản trước, chạy `.venv/bin/python -m pip install -r requirements-dev.txt` để thêm Matplotlib dùng khi xuất biểu đồ.

Có thể kiểm tra build hai cấu hình trong hai thư mục build độc lập. Chạy cấu hình lệnh dưới đây từ `firmware/sniffer` sau khi source môi trường ESP-IDF. Đổi hậu tố đường dẫn cấu hình nếu đã có file cũ.

```bash
source ~/esp/esp-idf/export.sh
idf.py --version
idf.py -B build-hopping -D SDKCONFIG=/tmp/pbl3-hopping.config build
idf.py -B build-fixed -D SDKCONFIG=/tmp/pbl3-fixed.config \
  -D 'SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.fixed' build
```

## 2. Chạy từng kịch bản

Với bài thử tĩnh, chuẩn bị số thiết bị trước khi bấm **Bắt đầu ghi**. Nhập đúng nhãn ban đầu để backend ghi `t_s=0`. Với bài thử động, bố trí người quan sát sát cửa và nhập **Ghi số mới** ngay sau mỗi lần qua cửa. Dùng dấu mốc thủ công cho thay đổi hành vi không làm đổi số lượng. Ghi từ trước hành động đầu đến sau hành động cuối, đủ dài để chờ `observation_window_s`, `departure_timeout_s` và ít nhất một vòng quét nếu dùng hopping. Với mặc định, có thể bắt đầu bằng khoảng 180 giây ổn định mỗi ca tĩnh và ít nhất 90 giây theo dõi sau lần ra cuối. Quy định trước thời lượng và số lượt lặp cho cả hai tập.

| Mã `--scenario` | Thao tác thực tế | Ground truth cần ghi |
|---|---|---|
| `room_0` | Để 0 thiết bị thử nghiệm trong phòng. Quan sát viên làm việc ngoài phòng hoặc dùng ghi chép giấy. Ghi các nguồn nền có thể nghe được. | `device_count=0` suốt phiên. |
| `room_1` | Đặt 1 thiết bị trong phòng, lặp ở gần và xa sniffer, với trạng thái màn hình đã chốt. | `1` suốt phiên. |
| `room_2` | Đặt 2 thiết bị, thử cùng model và khác model ở các lượt riêng nếu có. | `2` suốt phiên. |
| `room_3` | Đặt 3 thiết bị ở các vị trí khác nhau, kể cả góc xa. | `3` suốt phiên. |
| `room_5` | Đặt 5 thiết bị và trải các vị trí. | `5` suốt phiên. |
| `entry_exit` | Bắt đầu với số đã biết. Cho từng thiết bị qua cửa, chờ ổn định rồi cho thiết bị kế tiếp ra/vào. | Mốc bước thang, ví dụ `0 → 1 → 2 → 1 → 0`. |
| `hallway` | Giữ số thiết bị thật trong phòng cố định. Đưa thiết bị đối chứng qua hành lang và gần cửa, cả lúc cửa mở và đóng. | Chỉ đếm thiết bị trong phòng. Ghi dấu mốc hành lang riêng. |
| `mac_rotation` | Giữ thiết bị thử nghiệm trong một vị trí, quan sát đổi MAC hoặc thực hiện thao tác trên máy thử đã định. Thu riêng máy đó để xác minh ánh xạ alias khi có thể. | Count giữ nguyên. Ghi dấu mốc và nhãn alias độc lập khi chắc chắn quan sát được đổi MAC. |
| `quiet_probe` | Để thiết bị thật trong phòng, thử màn hình khóa hoặc chế độ có ít Probe. Ghi điều kiện chính xác và thời lượng. | Count vẫn gồm thiết bị ở trong phòng dù số Probe bằng 0. |
| `calibration` | Thu gần, xa, sát tường/cửa phía trong, hành lang và sát tường/cửa phía ngoài. Dùng bộ quy tắc đo cửa sổ của ước lượng vị trí. | Nhãn vùng thực của lượt đo, dùng thuộc `development`. |

Khi thu, ghi lại chính sách WiFi/màn hình, thời điểm thao tác và sự cố ngoài kịch bản. Định nghĩa trước thiết bị nào thuộc ground truth, ghi riêng các thiết bị của người quan sát và nguồn nền. Nếu đứng ở cửa và khó xác định thời điểm bước vào, dùng một đường mốc cố định. Lưu thời điểm và sai số phản ứng dự kiến của người ghi nhãn. Kết thúc phiên để backend đóng `metadata.json`, `raw.jsonl` và `truth.jsonl`.

## 3. Đóng gói phiên và khóa cấu hình

Capture dùng bộ ghi Probe hiện có của FastAPI và dashboard. Các phiên thật nằm trong `data/runtime/experiments/<id>`. `package` sao chép log và nhãn sang thư mục thử nghiệm mới, kiểm tra timestamp, nhãn đầu và trạng thái đã kết thúc. `experiment.json` gắn Test ID với SHA-256 đầu vào. Các bản gốc tiếp tục là dữ liệu đối chiếu.

```bash
.venv/bin/python -m research.experiment package \
  --session data/runtime/experiments/SESSION_ID --root data/runtime/physical-study \
  --test-id R5-01 --batch-id day2-round1 --scenario room_5 --setup-id room-a-fixed-6
```

Lặp lệnh với `--scenario` tương ứng trong bảng. Với `mac_rotation` hoặc bài tách cụm, đặt thêm `--alias-truth alias_truth.json`. File này ánh xạ MAC quan sát của thiết bị thử nghiệm sang ID ẩn danh **trong cùng một phiên**, ví dụ `{"02:00:00:00:00:01":"phone-01","02:00:00:00:00:02":"phone-01"}`. Chỉ ghi liên kết đã xác minh bằng thiết kế thu. Các alias chưa biết, hoặc có thể bị trùng giữa hai thiết bị, để ngoài file. Bảo quản file này và log raw như dữ liệu hạn chế chia sẻ.

Tạo `evaluation.json`, ví dụ `{"step_s":1,"probe":{"unique_window_s":60,"rssi_min":-127}}`. Có thể thêm khối `clustering`, `presence`, `location`, `calibration` theo schema các mô-đun. Presence và clustering dùng `heartbeat_s` và `rssi_min` của cấu hình `probe` để giữ cùng các điều kiện chính. Nếu đính kèm `calibration`, `samples[].session_id` phải là Test ID thuộc development cùng bố trí. Cửa sổ tham chiếu phải nằm trong phiên và cách nhau ít nhất một cửa sổ trong mỗi phiên. Dùng lệnh trích xuất feature của ước lượng vị trí trên chính các phiên đó. [Thiết kế location](IN_ROOM_ESTIMATION.md)

Tạo `split.json` với `development`, `test` là các danh sách Test ID, và `config_sha256` lấy từ `sha256sum evaluation.json`. Ví dụ:

```json
{
  "development": ["DEV-NEAR-01", "DEV-FAR-01", "DEV-HALL-01"],
  "test": ["R5-01", "EXIT-01", "HALL-02"],
  "config_sha256": "thay-bang-sha256-cua-evaluation.json"
}
```

Chạy `--phase development` để lựa chọn cấu hình. Trước lần chạy giữ lại, lưu file cấu hình cuối và checksum. Công cụ từ chối trùng Test ID, nguồn capture, checksum raw hoặc batch giữa hai tập, cũng như các mẫu tham chiếu mang ID test. Chạy `--phase test` một lần cho kết luận chính. Nếu đổi ngưỡng sau khi nhìn kết quả test, dùng một tập giữ lại mới cho kết luận tiếp theo.

```bash
.venv/bin/python -m research.experiment replay \
  --root data/runtime/physical-study --split split.json --config evaluation.json \
  --phase test --output data/results/physical-test-v1
```

## 4. Phương pháp so sánh và cách đọc độ trễ

| Phương pháp | Số đếm tại mốc lấy mẫu |
|---|---|
| **A. MAC-only tracking** | Số MAC nguồn phân biệt hợp lệ theo bộ đếm unique-MAC và `unique_window_s`. |
| **B. IE Fingerprint + clustering** | Số cụm suy luận có ít nhất một alias thuộc cùng cửa sổ MAC đang hoạt động của A. `fingerprint_count` ghi riêng số cấu trúc IE có thể sử dụng, nên hai máy trùng IE vẫn có thể là hai cụm. |
| **C. Clustering + Sherlock + in-room** | Presence theo `cluster_id` và bộ ước lượng trong phòng. Thiếu tham chiếu, coverage liên tục hoặc còn cụm xác nhận chưa rõ vị trí thì kết quả C là `N/A`. |

Replay sử dụng `host_elapsed_s`, bỏ qua phần đầu vào sau từng mốc lấy mẫu khi tính A/B/C và dựng lại association trên dữ liệu đến mốc đó. Nó dùng tối đa 300 giây và 12.000 record gần nhất cho B/C. Giới hạn 128 alias đủ điều kiện giữ chi phí hữu hạn, với `capacity_limited=true` và B/C trống nếu vượt. A dùng MAC Tracker trên replay. Khoảng đánh giá bắt đầu ở 0 và kết thúc trước timestamp của bản ghi hợp lệ cuối. Hết heartbeat là thiếu số liệu. Sai số trên từng phương pháp dùng các mốc có dự đoán. Báo cáo thêm coverage và tập giao các mốc cả ba phương pháp đều có dự đoán.

`events.csv` đo **độ trễ vượt ngưỡng số đếm**. Sau lần vào, tìm mẫu đầu có dự đoán ít nhất bằng số mới. Sau lần ra, tìm mẫu đầu có dự đoán tối đa bằng số mới. Tìm đến lần đổi nhãn kế tiếp hoặc hết log. Nếu trước sự kiện đã vượt ngưỡng, mất coverage trước khi đạt ngưỡng hoặc thiếu mẫu đối chiếu, độ trễ để trống và ghi lý do. Vì đây là ngưỡng trên tổng đếm, độ trễ không khẳng định đúng alias nào ra/vào. Độ phân giải bị giới hạn bởi `step_s` và sai số thao tác ghi nhãn.

Over-merge dùng mẫu số là số cặp alias đã quan sát có nhãn **khác thiết bị**. Over-split dùng mẫu số là số cặp alias đã quan sát có nhãn **cùng thiết bị**. Phần này tính trên association offline cuối phiên, tách khỏi đánh giá độ trễ. B/C dùng chung assignment. A mặc định mỗi MAC riêng. Báo cả số alias đã gán nhãn và số alias có thể đối chiếu. Thiếu nhãn hoặc mẫu số bằng 0 cho kết quả `N/A` ở tỷ lệ tương ứng.

## 5. Schema CSV và artifact

| File | Cột hoặc nội dung |
|---|---|
| `timeline.csv` | `test_id`, `timestamp_utc`, `t_s`, `synthetic`, `scenario`, `config_sha256`, `ground_truth_device_count`, `capture_valid`, `capacity_limited`, `raw_mac_count`, `fingerprint_count`, `cluster_count`, `confirmed_count`, `estimated_in_room_count`, `location_unknown_count` và ba cột `A_mac_only`, `B_ie_clustering`, `C_cluster_presence_room`. `raw_mac_count` là thống kê MAC raw tối đa 4.096 bản ghi gần theo tracker, khác cửa sổ của A. |
| `summary.csv` | Điểm từng Test ID và `POOLED`, với `phase`, `synthetic`, `slice`, `method`, số mẫu, coverage, MAE, RMSE, overcount/undercount, số sự kiện phát hiện và median độ trễ vào/ra. Sai số identity và độ trễ nằm ở hàng `available_case`. |
| `events.csv` | `test_id`, `synthetic`, `method`, `event_t_s`, `direction`, `old_count`, `target_count`, `followup_s`, `delay_s`, `status`. |
| `report.json` | Cấu hình đánh giá, checksum cấu hình/split/raw/truth, cấu hình thu đã lưu, chế độ kênh, thống kê từng phiên và thống kê gộp. Các bản báo cáo bỏ MAC cấu hình và vector tham chiếu chi tiết. |
| `summary.md`, `overview.svg`, `timeline-<test-id>.svg` | Bảng tổng hợp, MAE/coverage và diễn biến so với nhãn. Đường dự đoán có thể đứt tại mốc thiếu dữ liệu. |

Số đếm thiếu ghi ô trống trong CSV và `null` trong JSON. `coverage = số mốc có dự đoán / số mốc đánh giá`. Rates từ 0 đến 1, và MAE/RMSE tính theo thiết bị. Kết quả `POOLED` gộp các mốc của tất cả phiên trong phân vùng, nên phiên dài góp nhiều mốc hơn. Biểu đồ và bảng synthetic mang nhãn `SYNTHETIC`, còn CSV/JSON có trường `synthetic`. Các báo cáo đếm không đưa MAC alias hay dữ liệu Probe raw vào đầu ra chia sẻ.

```bash
.venv/bin/python -m research.experiment synthetic --output data/results/smoke/study
.venv/bin/python -m research.experiment replay \
  --root data/results/smoke/study/captures --split data/results/smoke/study/split.json \
  --config data/results/smoke/study/evaluation.json --phase test --allow-synthetic \
  --output data/results/smoke/report
.venv/bin/python -m pytest -q tests/evaluation
```

Lệnh synthetic tạo hai phiên mô phỏng riêng cho kiểm tra phần mềm. Công cụ yêu cầu cờ `--allow-synthetic` và giữ các bộ dữ liệu RF với synthetic ở suite riêng.
