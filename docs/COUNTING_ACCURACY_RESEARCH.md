# Độ chính xác đếm thiết bị Wi-Fi trong phòng

## Phát hiện từ quan sát 52 / 44 / 11

| Chỉ số | Quan sát | Phạm vi của phép đếm |
|---|---:|---|
| MAC trong cửa sổ | 52 | MAC có Probe hợp lệ trong cửa sổ `unique_window_s`. |
| RSSI + timeout | 44 | MAC vượt ngưỡng lọc, đạt số Probe yêu cầu trong cửa sổ ngắn và còn hạn timeout. |
| Sherlock | 11 | MAC đã xác nhận hoặc tạm thiếu quan sát nhưng chưa hết hạn theo AT/WT/DT. |

Quan sát do người đo cung cấp. Workspace chưa có `raw.jsonl` tương ứng hoặc timeline ground truth đã xác minh cho lượt này. Cảm nhận tại chỗ gần 44 hơn 11 là giả thuyết cần đối chiếu. Cả ba số đều có đơn vị là **MAC nguồn**. Chênh lệch 33 là chênh lệch hai tổng. Số MAC chỉ hiện diện trong baseline timeout cần đối chiếu tập giao, vì một số MAC có thể còn được Sherlock giữ sau khi timeout đã hết.

### Vì sao Sherlock có thể đếm thiếu

- **Đơn vị theo dõi.** `Comparison` chuyển từng MAC đã qua lọc vào `Sherlock`. Cả hai bảng đều dùng địa chỉ nguồn, trong khi Device Cluster là pipeline riêng. Một thiết bị đổi MAC có thể để lại nhiều ứng viên dưới ngưỡng AT. [Detector](../research/detectors.py) · [Dashboard guide](DASHBOARD_GUIDE.md)
- **AT, WT và DT.** Một MAC đóng góp tối đa một lần cho mỗi khe. AT tích lũy các khe dương đã chốt. Chúng có thể cách nhau nếu số khe trống liên tiếp chưa đạt WT. WT hủy ứng viên và bằng chứng của nó. Một nguồn đã xác nhận tiếp tục được đếm trong trạng thái `departing` đến khi đủ DT khe trống. Khe đang mở chưa đóng góp vào AT.
- **Cùng burst, khác kết quả.** Với cấu hình tham chiếu cho lượt khảo sát là khe 60 s, AT/WT/DT = 2/2/3, hai Probe của cùng MAC trong một khe giúp baseline timeout đạt `confirm_hits=2` trong 30 s nhưng chỉ tạo một khe dương cho Sherlock. Timeout giữ xác nhận đến 120 s sau Probe cuối. Khi thay đổi tham số trên giao diện, dùng cấu hình lưu trong `metadata.json` của từng phiên để xác định điều kiện thật.
- **Điều kiện reset.** Replay baseline dùng `Stream` của production. Mất heartbeat làm mẫu thiếu dữ liệu và heartbeat hợp lệ kế tiếp khởi tạo lại suy luận. Đổi boot, capture inactive và bản ghi control kết thúc hoặc đổi kết nối cũng reset. Bắt đầu phiên thu tạo bộ đếm mới. Đổi ngưỡng RSSI tạo bộ đếm mới và khi đang ghi cần cắt phiên theo luồng hiện hành. Queue drop và lỗi serial có thể làm mất khe dương. Bộ đếm lỗi tăng riêng lẻ không reset Sherlock MAC. [Stream](../research/stream.py) · [Collector](../research/collector.py)
- **Tần suất và hopping.** Khoảng giữa hai Probe *thu được* có thể dài vì thiết bị phát thưa, đổi MAC, đổi kênh, sniffer đang nghe kênh khác hoặc bản ghi bị mất. Báo cáo lưu median, p90 và max khoảng thu được ở cả đồng hồ host và đồng hồ radio, thời gian nghe suy ra từ status/channel và các lần bộ đếm rơi hoặc lỗi tăng. Tín hiệu chưa thu nằm ngoài log. Thời gian nghe kênh là bằng chứng về cơ hội thu, còn kết luận về hopping cần đối chiếu lượt fixed và hopping có cùng bố trí. [Định dạng bản ghi](PROTOCOL.md)
- **IE và kết hợp MAC.** Bộ ghép dùng profile IE ổn định, khoảng chuyển giao, chồng lấn thời gian, RSSI so được trên cùng kênh và ngưỡng mơ hồ. Các cụm chỉ nối khi ứng viên phù hợp với toàn bộ alias hiện có và không có đối thủ gần điểm. Cùng IE chỉ cung cấp một phần bằng chứng. Trường hợp nhiều máy cùng model giúp đo over-merge. MAC quay vòng với profile yếu, ít mẫu hoặc thiếu kênh chung giúp đo over-split. Nếu có nhãn alias xác minh thủ công, báo cáo dùng cặp cùng hoặc khác thiết bị đã quan sát để tính hai lỗi này. [Thiết kế cụm](DEVICE_CLUSTERING.md)

Trong `diagnose`, bốn cột `timeout_*` cộng thành số MAC dương tính theo timeout ở mỗi mốc hợp lệ. Chúng lần lượt chỉ ra MAC cũng được tính bởi Sherlock, đang chờ thêm khe dương, mới xuất hiện trong khe mở, hoặc hiện thiếu track. `diagnostics.json` bổ sung các lần hủy ứng viên, reset, bộ đếm rơi và phân bố khoảng quan sát. Điều này cho phép kiểm tra trực tiếp giả thuyết về 44 và 11 khi có bản ghi gốc.

## Thu dữ liệu thật trên Ubuntu

1. Mở repository đúng nhánh `feature/probe-ie-fingerprint`, chạy `bash scripts/setup.sh` nếu thiếu môi trường, rồi chạy `./run.sh`. Mở địa chỉ script in ra. Dùng `ls /dev/serial/by-id/ /dev/ttyUSB* /dev/ttyACM*` để tìm ESP32. Nếu bị từ chối quyền truy cập serial, thêm tài khoản vào nhóm `dialout` theo hướng dẫn rồi đăng xuất, đăng nhập lại. [Hướng dẫn chạy Ubuntu](../HUONG_DAN_CHAY_VSCODE.md)
2. Trong **Kết nối & quan sát**, kết nối ESP32-C3 ở 460800, xem heartbeat, chế độ kênh, dwell, gói rơi và lỗi serial. Giữ vị trí board, cách bố trí phòng và trạng thái cửa. Dùng firmware đang hoạt động. Nếu đã có board hoặc profile fixed được kiểm chứng, ghi các lượt fixed thành nhóm riêng cùng các lượt hopping.
3. Trong **Ghi phiên**, điền số thiết bị đã kiểm đếm và tên bố trí, bấm **Bắt đầu ghi**. Thu tối thiểu khoảng 5 phút cho lượt phòng trống, 1, 3 và 5 thiết bị. Dành lượt riêng cho màn hình khóa, hai thiết bị cùng mẫu, đi qua hành lang và ra/vào theo mốc. Bấm **Ghi số mới** ở lần đếm thay đổi. Kết thúc từng phiên để có `raw.jsonl`, `metadata.json` và `truth.jsonl`. Ghi nhận việc thay đổi kênh, bật màn hình hoặc lỗi thu bằng mốc và ghi chú.
4. Đặt trước batch theo ngày hoặc đợt thu độc lập. Dữ liệu cùng đợt, kể cả khi chia thành nhiều phiên, thuộc cùng một partition. Development dùng để thử ngưỡng và thu tham chiếu vị trí. Test giữ lại để chấm cấu hình đã khóa. Các vị trí tham chiếu nên gồm gần, xa, sát cửa phía trong và phía ngoài, cùng hành lang. [Quy trình chia tập](EXPERIMENT_PROTOCOL.md) · [Hiệu chuẩn vị trí](IN_ROOM_ESTIMATION.md)

### Chẩn đoán trước khi có nhãn đáng tin cậy

Thay `SESSION_ID` bằng ID phiên đã kết thúc. Lệnh lấy cấu hình đã lưu của phiên nếu bỏ `--config`, và chạy được khi chưa có timeline ground truth đủ tin cậy.

```bash
.venv/bin/python -m research.counting_accuracy diagnose \
  --session data/runtime/experiments/SESSION_ID \
  --output data/results/counting-diagnostics-SESSION_ID
```

Khi có nhãn, đóng gói capture theo từng đợt. Bản sao giữ nguyên từng byte log Probe và metadata, gồm `host_elapsed_s`, `host_time`, `ts_us`, boot, kênh, RSSI, IE và trạng thái sniffer.

```bash
.venv/bin/python -m research.experiment package \
  --session data/runtime/experiments/SESSION_ID \
  --root data/runtime/counting-captures \
  --test-id R5-D1 --batch-id day1 --scenario room_5 --setup-id room-a-fixed-6
```

Nếu người quan sát ghi timeline độc lập, thêm `--truth /duong/dan/observer.jsonl` khi đóng gói. Mỗi dòng có dạng `{"t_s":0,"device_count":5}`. Nhãn bắt đầu từ giây 0 và tăng nghiêm ngặt theo thời gian phiên. Bản log nguồn được giữ nguyên. Dùng `--alias-truth` riêng cho alias đã được xác minh, nếu có. Bộ dự đoán chỉ nhận các bản ghi đến thời điểm hiện tại và cấu hình. Chương trình chấm mới gắn timeline nhãn, sau khi replay đã hoàn thành.

### Chạy A/B offline

Cấu hình mẫu `configs/counting-research.json` chọn hai baseline, hai biến thể timing và các phương pháp theo cụm. Sao chép ra một tệp nghiên cứu riêng nếu cần thử ngưỡng khác. Trường `methods` cho phép chọn baseline và biến thể. Các mục `sherlock_variants` tạo cột Sherlock MAC riêng trên cùng bản ghi. Dùng đúng các ID đã đóng gói trong `split.json` và ghi SHA-256 của cấu hình.

```json
{
  "development": ["R5-D1"],
  "test": ["R5-D2"],
  "config_sha256": "THAY_BANG_SHA256_CUA_CAU_HINH"
}
```

```bash
sha256sum configs/counting-research.json

.venv/bin/python -m research.counting_accuracy compare \
  --root data/runtime/counting-captures --split data/runtime/counting-split.json \
  --config configs/counting-research.json --phase development \
  --output data/results/counting-development

.venv/bin/python -m research.counting_accuracy compare \
  --root data/runtime/counting-captures --split data/runtime/counting-split.json \
  --config configs/counting-research.json --phase test \
  --output data/results/counting-test
```

Chạy test sau khi đã chọn cấu hình từ development. Thiết lập lại hash nếu sửa cấu hình ở bước development. Công cụ kiểm tra hash, phiên trùng, batch giao nhau và nguồn gốc synthetic. Cấu hình tham chiếu vị trí chỉ nhận cửa sổ đúng setup từ development. Nếu muốn thử nhiều ngưỡng RSSI hoặc timeout, chạy cấu hình riêng trên cùng danh sách phiên và khóa cấu hình chọn được trước khi mở test.

## Các biến thể thử nghiệm

| Phương pháp | Cách đếm |
|---|---|
| `rssi_timeout`, `sherlock_mac` | Hai baseline dùng nguyên `Stream` và bộ đếm hiện hành. |
| `sherlock_mac__*` | Một cấu hình AT/WT/DT và độ dài khe cho mỗi tên; ngưỡng và luồng Probe còn lại giữ chung. |
| `sherlock_cluster` | Giữ máy trạng thái Sherlock, đổi khóa theo dõi thành cụm đã suy luận từ prefix hiện có. Tái dựng từ đoạn thu còn giữ tối đa 300 s nên có thể mất bằng chứng lâu hơn đoạn này. |
| `proposed_30s`, `proposed_60s` | Đếm cụm `PROBABLE + CONFIRMED` trong cửa sổ trượt. Mặc định một quan sát là `CANDIDATE`, hai quan sát là `PROBABLE`, ba quan sát trở lên là `CONFIRMED`. Các quan sát tính bằng chứng phải cách nhau ít nhất 5 s trên đồng hồ host và radio. Trạng thái giảm khi bằng chứng rời cửa sổ. |
| `proposed_room_30s`, `proposed_room_60s` | Trong các cụm do Proposed chọn, đếm cụm được bộ phân loại vị trí hiện hành xác nhận trong phòng. Cần hiệu chuẩn tương thích và vị trí có kết quả cho mọi cụm đã chọn. Cụm probable chưa đủ tín hiệu vị trí khiến kết quả trong phòng là `UNKNOWN`. |

Các trạng thái Proposed biểu thị mức bằng chứng định tính. Khi thêm xác suất cần hiệu chuẩn và kiểm định trên các đợt có nhãn độc lập. Mất heartbeat, đổi boot, tăng bộ đếm rơi/lỗi, đổi chế độ hoặc đổi kênh fixed đã ghi nhận đều có thể khởi động lại cửa sổ hợp lệ của biến thể. Hopping vẫn có thể làm thiếu Probe. Khi quá giới hạn alias hoặc log bị cắt do đầy bộ đệm replay, các kết quả theo cụm thiếu dữ liệu và có cờ `cluster_capacity_limited`. Cấu hình mẫu cho phép tối đa 384 alias trong replay offline. Dashboard production vẫn giữ giới hạn vận hành riêng.

## Đọc kết quả

- `timeline.csv` chứa mỗi mốc dự đoán, số thực, cờ coverage, phần chênh lệch timeout/Sherlock và trạng thái theo cụm. Ô trống thể hiện thiếu dự đoán. Giá trị 0 là một kết quả ở mốc đủ điều kiện.
- `windows.csv` có các khối đầy đủ 30 s và 60 s. Mỗi dòng xuất trung bình số đếm của các mốc có kết quả và số mốc tương ứng cho từng phương pháp. Cửa sổ theo khối này dùng để tổng hợp, còn `proposed_30s/60s` dùng cửa sổ trượt để tạo dự đoán.
- `report.json` có MAE, RMSE, tỷ lệ overcount/undercount, tổng đơn vị đếm dư và thiếu, coverage và các lỗi cặp alias nếu có nhãn. Báo cáo tính thêm false positive khi phòng trống mà dự đoán có thiết bị, và false negative khi phòng có thiết bị mà dự đoán bằng 0. Hai tỷ lệ này dùng các mốc có dự đoán của từng nhóm. Nhận diện đúng hay sai từng máy cần nhãn danh tính và hiện diện từng máy.
- `event-delays.csv` đo thời gian vượt mức count sau thay đổi nhãn, kèm lý do như mất coverage, đã vượt ngưỡng trước sự kiện hoặc chưa phát hiện. Đây là độ trễ theo tổng số đếm.
- `timeline-<ID>.svg` so sánh ground truth, RSSI + timeout, Sherlock và Proposed theo những phương pháp đã chọn. `comparisons.csv` ghi từng ca trên các mốc hai bên có kết quả. `method_worse` đếm số mốc phương pháp mới có sai số tuyệt đối lớn hơn baseline, `mae_difference > 0` cho thấy kém hơn trên tập mốc chung. `method_unavailable_with_baseline` ghi số mốc phương pháp mới để trống trong khi baseline vẫn có kết quả.

### Những ca cần xem riêng

- Hai thiết bị cùng model thay nhau xuất hiện ở cùng vị trí có thể trông giống một lần đổi MAC. Xem lỗi over-merge và mức đếm thiếu ở các lượt nối tiếp.
- Hai burst từ hành lang lọt qua cửa có thể tạo `PROBABLE` và làm số cụm quan sát tăng. Xem MAE ở phòng trống và so bài hành lang với baseline RSSI + timeout.
- Một máy phát thưa hoặc di chuyển qua cửa nhanh có thể hết cửa sổ Proposed hoặc vào sau baseline timeout. Xem chênh lệch 30 s với 60 s, khả năng phát hiện sự kiện và độ trễ.
- Thiếu hiệu chuẩn đúng phòng, thiếu coverage, rơi gói hoặc vượt sức chứa có thể làm phương pháp mới thiếu kết quả trong khi baseline còn có số. Báo cùng coverage và kết quả trên các mốc chung.

Workspace chưa có capture có nhãn cho quan sát 52/44/11. MAE, RMSE, tỷ lệ đếm dư/thiếu và độ trễ trên phần cứng còn chờ đo. Dữ liệu tổng hợp trong kiểm thử chỉ xác minh hành vi của công cụ và có nhãn `SYNTHETIC` trong đầu ra.

## Tệp triển khai và kiểm thử

- [counting_accuracy.py](../research/counting_accuracy.py) chạy chẩn đoán và replay A/B, rồi chấm so với timeline nhãn.
- [cluster_counting.py](../research/cluster_counting.py) triển khai Sherlock theo cụm và quy tắc tích lũy bằng chứng.
- [counting_report.py](../research/counting_report.py) xuất bảng theo mốc, cửa sổ, độ trễ, so sánh và biểu đồ.
- [experiment.py](../research/experiment.py) đóng gói timeline độc lập, khóa tập dữ liệu và chấm lỗi cặp alias.
- [counting-research.json](../configs/counting-research.json) cấu hình A/B mẫu.
- [test_counting_accuracy.py](../tests/evaluation/test_counting_accuracy.py) kiểm tra các ca phát thưa, MAC rotation, IE giống nhau, hopping, mất gói, tách ground truth, giới hạn cụm, hiệu chuẩn vị trí và xuất báo cáo.

```bash
.venv/bin/python -m pytest -q
```

Kết quả trên workspace của nhánh `feature/probe-ie-fingerprint` là **142 PASS, 0 FAIL**. Trong đó có 10 ca cho công cụ mới. Starlette báo một cảnh báo deprecation liên quan đến AnyIO.
