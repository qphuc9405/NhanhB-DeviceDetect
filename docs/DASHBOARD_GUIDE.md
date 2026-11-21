# Dashboard phát hiện thiết bị WiFi

## Chạy trên Ubuntu

Tại thư mục `wifi-device-sherlock`, dùng Python 3.12 và Node.js từ 22. Lần đầu cài môi trường và build giao diện, sau đó mở `http://127.0.0.1:8000`.

```bash
bash scripts/setup.sh
bash run.sh
```

Nếu thiếu `venv`, cài `python3.12-venv` theo hướng dẫn trong README. Khi vừa sửa frontend, chạy `npm --prefix frontend run build` rồi tải lại trang. [README](../README.md)

Trong tab **Kết nối & quan sát**, chọn cổng ESP32-C3, kết nối UART 460800 và chờ heartbeat. Thanh trạng thái hiển thị `LIVE` khi kết nối board, `DEMO` khi chạy dữ liệu mô phỏng từ nút **Chạy demo nhanh**, hoặc `REPLAY` khi phát lại một phiên thật đã lưu từ tab **Nâng cao**. **Ngắt nguồn** đưa dashboard về trạng thái chưa kết nối. Ghi nhãn và báo cáo thực nghiệm tiếp tục ở các tab hiện có.

## Đọc số liệu

- **Estimated physical WiFi devices in room** lấy từ các cụm `CONFIRMED` có kết quả vị trí. `UNKNOWN` xuất hiện khi thiếu tham chiếu, cửa sổ vị trí chưa đủ coverage, còn cụm xác nhận chưa rõ vị trí, nguồn mất dữ liệu hoặc đang chạy demo. Số 0 có ý nghĩa khi có coverage và bộ ước lượng đủ dữ liệu để trả kết quả.
- Bảng **Device Cluster** cho biết số alias, cấu trúc IE, RSSI theo kênh, thời điểm thấy đầu/cuối, heuristic liên kết, trạng thái hiện diện và vị trí. Mở **Lý do và lịch sử** để xem bằng chứng liên kết và các lần chuyển trạng thái. `ABSENT` nghĩa là hết hạn quan sát. Thiết bị vật lý có thể vẫn ở trong phòng.
- Biểu đồ mặc định **30 giây** theo đồng hồ của nguồn, với các lựa chọn 15, 30, 60 và 120 giây. Đây là phạm vi của trục hiển thị. Các bộ đếm presence sử dụng `stale_timeout_s` và `departure_timeout_s` từ cấu hình thuật toán. Mẫu thiếu dữ liệu tạo khoảng trống trên biểu đồ.
- `inferred_cluster_count` đếm các cụm có alias trong cửa sổ phân tích, bao gồm cả cụm vừa hết hạn. `confirmed_count` chỉ đếm cụm đang `CONFIRMED`. Các giá trị này phục vụ các câu hỏi khác nhau khi xem phiên thu.

## Bật tham chiếu trong phòng

Dùng quy trình thu nhãn và định dạng tham chiếu trong tài liệu ước lượng. Backend tùy chọn đọc một file JSON qua `WIFI_DASHBOARD_CONFIG`. Đặt cùng `setup_id` trong cấu hình dashboard và đối tượng `calibration`. `calibration` chứa toàn bộ nội dung `calibration.json`. [Thu dữ liệu tham chiếu](IN_ROOM_ESTIMATION.md)

Ví dụ tạo file cấu hình từ bộ tham chiếu đã thu, kèm cấu hình presence và clustering mặc định của mô-đun:

```bash
.venv/bin/python -c 'import json,sys; c=json.load(open(sys.argv[1])); print(json.dumps({"setup_id":c["setup_id"],"calibration":c}))' calibration.json > dashboard-config.json
WIFI_DASHBOARD_CONFIG=dashboard-config.json bash run.sh
```

Các trường tùy chọn `presence`, `clustering` và `location` nhận các khóa của những mô-đun tương ứng. Dashboard dùng ngưỡng RSSI và heartbeat của nguồn hiện tại để đồng bộ với collector. Các phiên thu mới lưu `dashboard_setup_id` khi có cấu hình bố trí. Replay chỉ dùng tham chiếu vị trí nếu bố trí đã lưu khớp với dữ liệu tham chiếu. Phiên cũ thiếu `dashboard_setup_id` vẫn xem được MAC, cluster và trạng thái, với vị trí `UNKNOWN`. [Ngưỡng presence](PRESENCE_STATE_MACHINE.md) · [Ngưỡng clustering](DEVICE_CLUSTERING.md)

## API và schema dữ liệu

`GET /api/probe/dashboard` trả JSON `probe-dashboard-v1`. Dashboard đối chiếu `source_id` với `dashboard_source_id` từ `GET /api/probe/state` để bỏ ảnh chụp của một nguồn đã đổi.

| Trường | Kiểu và ý nghĩa |
|---|---|
| `version`, `source_id` | Chuỗi phiên bản và ID nguồn trong bộ nhớ backend. |
| `source` | `LIVE`, `REPLAY`, `DEMO` hoặc `null`. |
| `connection`, `status` | Trạng thái vận chuyển và trạng thái phân tích. `status` gồm `waiting`, `empty`, `ready`, `finished`, `disconnected`, `limited`, `error`. |
| `t_s`, `analysis_window_s`, `truncated` | Mốc giờ của nguồn, chân trời phân tích và cờ quá dung lượng bản ghi. |
| `calibration_status`, `location_ready` | Chất lượng tham chiếu và khả năng dùng cửa sổ location hiện tại. `location_ready` có mặt khi đã xử lý được coverage. |
| `metrics` | Các bộ đếm có kiểu `integer` hoặc `null`. |
| `history` | Danh sách ảnh chụp cùng schema metrics, mỗi phần tử có `t_s`. |
| `clusters` | Danh sách cấu trúc cụm đã giảm thiểu dữ liệu. |

| Metric | Đơn vị |
|---|---|
| `raw_mac_count` | Số MAC phân biệt trong tối đa 4.096 bản ghi Probe mà MAC Tracker còn giữ cho thống kê raw. |
| `active_mac_count` | Số MAC còn hiệu lực trong bộ đệm chẩn đoán. |
| `inferred_cluster_count` | Số cụm suy luận từ bản ghi hiện còn trong cửa sổ phân tích. |
| `candidate_count`, `confirmed_count`, `stale_count`, `absent_count` | Số cụm đang ở từng trạng thái presence ở mốc báo cáo. |
| `estimated_in_room_count` | Ước lượng trong phòng, hoặc `null` khi chưa thể công bố. |
| `location_unknown_count`, `outside_likely_count` | Số cụm xác nhận chưa rõ vị trí và số cụm có khả năng ở ngoài. |

Một mục `clusters` có `cluster_id`, `mac_alias_count`, `fingerprint_summary` (tối đa ba cấu trúc mã–độ dài), `rssi_statistics` (mỗi kênh có median của các median theo alias, độ dao động lớn nhất và số Probe), `first_seen_s`, `last_seen_s`, `heuristic_score`, `presence_state`, `location_state`, `location_reason`, `association_history` và `state_history`. Lịch sử được giới hạn ở 12 mục gần nhất theo từng loại. Trạng thái vị trí `null` biểu thị chưa áp dụng cho cụm hiện tại. `location_unknown` biểu thị cụm đã xác nhận nhưng chưa đủ bằng chứng vị trí. Mã cụm dùng khóa ngẫu nhiên của nguồn và alias đầu tiên. Mã có thể thay đổi khi phân cụm lại hoặc alias đầu tiên trượt khỏi bộ đệm.

Backend phân tích lại tối đa 300 giây và 12.000 bản ghi gần nhất để phản hồi trong phạm vi hữu hạn. Quá 128 alias đủ điều kiện sẽ trả `limited` cùng các số đếm MAC khả dụng. Khi bộ đệm mất bản ghi trong chân trời phân tích, số trong phòng trả `null`. Lịch sử biểu đồ lưu ảnh chụp khi dashboard truy vấn API, theo thời gian của nguồn, với tối đa một mẫu mỗi giây nguồn. Một phiên REPLAY hoàn tất có thể hiện ảnh chụp cuối trước mốc dừng đã lưu. Các file raw và công cụ nghiên cứu ở tab cũ có thể chứa MAC đầy đủ. Endpoint dashboard chỉ công bố số alias và mã cụm theo nguồn. Dashboard này không thêm chức năng xuất CSV.

## Kiểm thử

```bash
.venv/bin/python -m pytest -q tests/test_dashboard_api.py
npm --prefix frontend run build
```

Smoke test trình duyệt dùng FastAPI thật cùng fixture tạm, Chrome và Playwright cài ngoài repo:

```bash
npm install --prefix /tmp/pbl3-dashboard-browser playwright
DASHBOARD_PLAYWRIGHT_MODULE=/tmp/pbl3-dashboard-browser/node_modules/playwright/index.mjs \
  node --test tests/dashboard_browser.mjs
```

Có thể đặt `DASHBOARD_TEST_CHROME` nếu Chrome nằm ngoài `/usr/bin/google-chrome` và `DASHBOARD_TEST_PYTHON` nếu dùng môi trường Python khác. Bộ test API bao gồm nguồn không dữ liệu, nguồn hợp lệ trống, nhiều alias trong một cụm, timeout, mất serial và replay. Bộ test trình duyệt kiểm tra nhãn nguồn, lỗi API, thay đổi cửa sổ biểu đồ, mở chi tiết và bố cục mobile/desktop.
