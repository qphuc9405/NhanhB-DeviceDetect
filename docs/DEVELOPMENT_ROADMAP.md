# Roadmap phát triển WiFi Device Sherlock

Đề xuất dựa trên [audit cây làm việc ngày 20/11/2026](CURRENT_SYSTEM_AUDIT.md). Baseline hiện tại là các bộ đếm **nguồn MAC**. Mục tiêu của phần mở rộng là đo xem có thể ước lượng số **thiết bị thử nghiệm** tốt hơn trong những điều kiện đã kiểm chứng. Mỗi giai đoạn có đầu ra dùng để quyết định có tiếp tục hay chưa.

## 0. Xác minh replay và chốt hợp đồng dữ liệu — P1

Thực hiện song song với chuẩn bị board.

- Sửa cách tiến đồng hồ thuật toán trong replay qua khoảng dài giữa các bản ghi. Xác định rõ mốc đóng khe, hết hạn heartbeat, reset khi kết nối lại và khi đến cuối file. Dùng quy ước causal hiện hành của Sherlock. [Replay loop](../research/collector.py#L116) · [Stream](../research/stream.py#L16) · [Timeline](../research/evaluate.py#L39)
- Thêm hồi quy cho ca status 0 s → Probe 0,1 s → status 8 s, khe 2 s, AT 1 và heartbeat 5 s. Đối chiếu journal tại mốc 2 s, 4 s và 8 s giữa offline và replay ở nhiều tốc độ, với và không có polling. Kiểm tra thêm reboot, reconnect và khoảng im lặng đi qua ranh giới khe. [Các test hiện có](../tests/test_v2.py) · [Kiểm thử API replay](../tests/test_api_protocol.py#L58)
- Cập nhật bảng record `probe` trong giao thức theo schema hiện tại. Ghi rõ số phiên bản firmware/cấu hình, baud 460800, giới hạn 24 IE, timestamp capture và timestamp quan sát của laptop. Giữ manifest 921600 làm hồ sơ lịch sử và tạo hồ sơ build mới khi có bản firmware dùng để thu. [Giao thức](PROTOCOL.md) · [Schema](packet.schema.json) · [Manifest](build-manifest.json)

**Nghiệm thu.** Sự kiện thuật toán replay qua ca gap tái hiện được và độc lập với tần suất đọc API. Dữ liệu phiên còn đọc được với firmware cũ thiếu trường IE. Bộ test, build và smoke dashboard đạt.

## 1. Kiểm chứng ESP32-C3 và thu dữ liệu chuẩn — P0

**Cần có.** Một ESP32-C3 với đường USB/UART phù hợp và quyền truy cập cổng, các điện thoại thử nghiệm được đánh nhãn, khả năng ghi mốc vào/ra có người quan sát. Để đối chứng khung IE theo từng gói, cần capture tham chiếu trên kênh cố định bằng thiết bị thu độc lập nếu có.

| Việc | Đầu ra và điều kiện nghiệm thu |
|---|---|
| Build và chạy hai cấu hình | Lưu phiên bản ESP-IDF, hash binary và cấu hình build. Thu một log thật cho fixed kênh 6 và một log cho hopping. Xác nhận heartbeat, Probe Request, cờ retry và IE qua parser tới dashboard. |
| Đo chất lượng capture/UART | Đối chiếu kênh từng Probe với nguồn tham chiếu; ghi kênh, thời gian chuyển kênh, dwell thực, tốc độ Probe, `probe_dropped`, `serial_errors`, dòng parse lỗi và khoảng mất heartbeat. So cùng điều kiện qua nhiều lượt vì một board chỉ nghe một kênh tại một thời điểm. |
| Thu phiên để đánh giá số lượng | Ghi nhãn số thiết bị cùng mốc thời gian. Thu phòng trống, 1 máy, nhiều máy, máy cùng model, máy bên ngoài phòng, màn hình khóa/mở và các mốc vào/ra. Ghi model/OS, vị trí, trạng thái WiFi, loại board, cấu hình và nguồn nền. |
| Thu phiên để đánh giá ghép tách | Thu riêng từng máy trước. Gán nhãn burst hoặc cặp burst khi có căn cứ kiểm soát; có cả cặp cùng máy qua hai MAC quan sát và cặp khác máy trùng chữ ký. Để trạng thái chưa biết khi không gán được. |
| Chia dữ liệu | Tách theo buổi trước khi chọn tham số và tránh để các đoạn liền nhau thuộc hai tập. Nếu cần kết luận về model mới, giữ một nhóm model hoặc thiết bị ngoài tập phát triển. |

Bộ hồ sơ gồm `raw.jsonl`, `truth.jsonl`, `metadata.json`, ghi chú mốc, chất lượng thu và phần nhãn burst dùng ID thiết bị thử nghiệm trong từng đợt. Raw giữ MAC đầy đủ, nên xác định cách lưu, quyền truy cập và bản dữ liệu được phép chia sẻ trước khi thu. Chỉ xác nhận độ chính xác sau khi có kết quả đo từ những phiên này. [Thiết kế buổi thu](PLAN.md) · [Lưu phiên](../research/collector.py#L131) · [Split mẫu](../configs/split.example.json)

## 2. Hoàn thiện fingerprint offline — P1

- Lấy `research.ie_fingerprint` làm baseline chữ ký chính xác. Định nghĩa phiên bản chữ ký và chính sách đối với IE thiếu, chữ ký rỗng sau khi bỏ SSID, chuỗi không hợp lệ và dữ liệu chạm giới hạn 24 cặp. Chỉ mở rộng wire schema nếu phần đo cho thấy cần phân biệt IE bị cắt từ firmware. [CLI](../research/ie_fingerprint.py) · [Parser](../backend/app/protocol.py#L19)
- Sửa tổng MAC duy nhất theo toàn phiên. Thống kê MAC theo nhóm vẫn giữ riêng. Xuất số mẫu IE thiếu/rỗng, số burst đủ dữ liệu, kênh, tỷ lệ trùng chữ ký giữa máy và độ thay đổi chữ ký trong cùng máy. Giữ `ts_us` từ board cho đặc trưng burst và `host_elapsed_s` cho mốc phiên.
- Kiểm tra ảnh hưởng của chọn khung đầu, nhảy kênh, retry, sequence quay vòng và dữ liệu cắt. So biến thể chỉ dựa trên dữ liệu phát triển. Lưu kết quả dạng JSON có phiên bản để dùng lại khi đánh giá.

**Nghiệm thu.** Cùng đầu vào và cấu hình sinh cùng chữ ký/nhóm. Có fixture tái hiện hai lỗi CLI trong audit và có báo cáo độ ổn định/trùng chữ ký trên phiên thật với số mẫu, dữ liệu thiếu và cấu hình thu.

## 3. Thử nghiệm device clustering offline — P1

- Đơn vị đầu vào là burst có chữ ký và thông tin chất lượng. So baseline gom theo IE với một ứng viên dùng thêm khoảng cách thời gian, tốc độ sequence và đặc trưng RSSI. DBSCAN là một phương án để thử trên tập phát triển. Chọn phương pháp sau khi so dữ liệu. Giữ trường hợp thiếu bằng chứng ở trạng thái chưa gán và giới hạn ID suy luận trong phiên.
- Đo **precision/recall theo cặp ghép**, tỷ lệ nhập nhầm hai máy, tỷ lệ tách nhầm burst cùng máy và tỷ lệ bỏ ngỏ trên phần dữ liệu có nhãn liên kết. Đo **MAE, bias, tỷ lệ đếm đúng, sai số khi nhãn 0, coverage và độ trễ** với nhãn số lượng riêng. Báo các tình huống cùng model, đổi MAC, thưa Probe, nguồn phòng bên và gap heartbeat.
- Đối chiếu cùng phiên với unique-MAC, timeout và Sherlock theo MAC. Khóa phương pháp, RSSI, tham số và tiêu chí chấp nhận trước khi mở tập test. Lấy ngưỡng chấp nhận từ mục tiêu thí nghiệm và chi phí ghép nhầm của nhóm. [Báo cáo hiện tại](../research/evaluate.py#L85) · [Sweep development/test](../research/sweep.py)

**Nghiệm thu.** Kết quả test độc lập có thể chạy lại, kèm số phiên, độ phủ nhãn và trường hợp thất bại. Chỉ đưa ước lượng cluster lên luồng live khi lợi ích so với baseline được thể hiện theo các chỉ số đã chốt. Nếu chưa đạt, giữ phân cụm ở chế độ nghiên cứu và ghi rõ hạn chế.

## 4. Tích hợp API, tracking và dashboard — P2

1. Hiển thị báo cáo offline theo phiên trước. Thêm đầu ra có phiên bản cho số burst, chữ ký IE, trạng thái chất lượng, cluster ước lượng và tỷ lệ chưa gán. Ghi đơn vị và cửa sổ quan sát trong API và UI.
2. Nếu đạt nghiệm thu offline, chạy tracking cluster thử nghiệm song song với MAC/Sherlock. Thiết kế ID theo phiên, điểm chất lượng và quy tắc khi heartbeat mất/board reboot. Kiểm thử MAC đổi, hai máy trùng chữ ký đồng thời, giới hạn bộ nhớ, reconnect, replay và đường lui khi thiếu IE.
3. Giữ các nhãn riêng trên giao diện gồm **nguồn MAC**, **nhóm IE**, **cluster ước lượng** và **số thiết bị nhập tay**. Đo thời gian xử lý live, khả năng tái lập offline và cách hiển thị khi nguồn không hợp lệ. [API](../backend/app/probe_api.py) · [Dashboard](../frontend/src/ProbePanel.tsx) · [State machine](../research/detectors.py#L44)
4. Nếu nhóm cần nối với logger/Streamlit cấp dự án, chốt hợp đồng xuất hoặc adapter có phiên bản, trường thời gian/nhãn, loại số đếm và cách xử lý MAC. Thử với dữ liệu mẫu của cả hai pipeline. Giữ việc kiểm chứng CSI/Empty–Occupied trong kế hoạch riêng. [Đặc tả CSV cấp dự án](../../Dac_ta_dinh_dang_du_lieu.md) · [Logger CSV](../../laptop/logger.py)

**Nghiệm thu.** Dashboard ghi rõ đơn vị từng số, phân biệt live/replay/demo và hiển thị đúng khi thiếu dữ liệu. API và báo cáo cho phép đối chiếu phiên thật với nhật ký và cấu hình. Việc báo cáo số thiết bị ước lượng đi kèm phạm vi thử nghiệm và sai số đã đo.

## Thứ tự thực hiện

| Mức | Việc có thể mở tiếp | Phụ thuộc |
|---|---|---|
| **P0** | Chuẩn bị board, thu log thật và các phiên có nhãn | Board, điện thoại thử nghiệm, người ghi nhãn |
| **P1** | Sửa timing replay và chuẩn hóa hợp đồng JSONL | Ca kiểm thử tổng hợp đã tái hiện |
| **P1** | Sửa đầu ra fingerprint và đo độ ổn định | Fixture ngay, dữ liệu RF cho phần đánh giá |
| **P1** | Thử phân cụm và đo ghép nhầm/tách nhầm | Phiên gán nhãn burst và tập test độc lập |
| **P2** | Báo cáo offline trên API/UI, sau đó thử live | Kết quả phân cụm offline đã nghiệm thu |
| **P2** | Adapter hoặc xuất dữ liệu cho pipeline CSI cấp dự án | Nhu cầu tích hợp được nhóm chốt |
