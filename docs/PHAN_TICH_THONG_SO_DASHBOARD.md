# Phân tích thông số Dashboard WiFi Device Sherlock

Dashboard theo dõi ba đại lượng. **MAC quan sát** là địa chỉ nguồn trong Probe Request. **Cụm suy luận** là một hoặc nhiều MAC được thuật toán liên kết. **Thiết bị thật trong phòng** là nhãn do người quan sát ghi. Thẻ **Estimated physical WiFi devices in room** là ước lượng từ dữ liệu thu và bộ tham chiếu RSSI của bố trí phòng.

## 1. Cấu hình LIVE tại thời điểm kiểm tra

Các giá trị dưới đây được đọc từ backend đang chạy ngày 20/11/2026. Khi chỉnh thông số hoặc phát lại phiên khác, giá trị trên dashboard có thể đổi.

| Thông số | Giá trị đã đọc | Ý nghĩa |
|---|---:|---|
| Nguồn và chế độ kênh | `LIVE`, `hopping` | ESP32-C3 đang nhảy kênh. Một radio chỉ nghe một kênh trong mỗi thời điểm. |
| Dwell và baud | 3 giây/kênh, 460800 baud | Dwell là thời gian nghe mỗi kênh. Baud là tốc độ UART giữa ESP32 và máy tính. |
| Độ dài khe Sherlock | 60 giây | Chốt bằng chứng theo từng khe thời gian. |
| AT / WT / DT | 3 / 2 / 3 khe | Lần lượt là số khe có Probe để xác nhận, số khe trống liên tiếp để hủy ứng viên, và số khe trống liên tiếp để hết hiệu lực xác nhận. |
| Ngưỡng RSSI | −65 dBm | Probe có RSSI từ −65 dBm trở lên đi qua bước lọc RSSI. Các điều kiện lọc khác vẫn được áp dụng. |
| Cửa sổ MAC thô | 60 giây | Cửa sổ của bộ đếm **MAC trong cửa sổ** ở tab Nâng cao. |
| Cửa sổ xác nhận Timeout | 2 gói trong 30 giây | Số gói hợp lệ tối thiểu để bộ đếm Timeout xác nhận một MAC. |
| Timeout baseline | 120 giây | Bộ đếm Timeout giữ MAC đã xác nhận dựa trên lần cuối có Probe hợp lệ. |
| Hết hạn MAC chẩn đoán | 120 giây | Bộ đệm trước bộ lọc loại mục MAC khi quá thời gian này kể từ lần quan sát cuối. |
| Hết hạn heartbeat | 5 giây | Khoảng thời gian từ heartbeat cuối mà backend còn coi nguồn quan sát là hợp lệ. |
| Giới hạn nguồn | 2.000 | Giới hạn số mục ở các bảng MAC. Khi đầy, một phần quan sát có thể bị từ chối. |
| Tham chiếu vị trí | `missing_calibration` | Phiên LIVE hiện thiếu bộ tham chiếu RSSI. Thẻ ước lượng trong phòng hiển thị `UNKNOWN`. |

## 2. Các thẻ ở trang chính

| Chỉ số | Cách đọc |
|---|---|
| **Estimated physical WiFi devices in room** | Số cụm `CONFIRMED` được ước lượng ở trong phòng. Dashboard cần dữ liệu hợp lệ, bố trí kênh cố định khớp calibration, đủ coverage và kết quả vị trí cho mọi cụm xác nhận tại mốc đó. `UNKNOWN` nghĩa là chưa đủ bằng chứng để công bố số. |
| **MAC quan sát** (`raw_mac_count`) | Số MAC phân biệt trong tối đa 4.096 bản ghi Probe riêng biệt gần nhất của tracker, gồm cả MAC có gói không qua lọc. Mốc này tính theo số bản ghi. |
| **MAC còn hiệu lực** (`active_mac_count`) | Số mục MAC trước bộ lọc còn trong bộ đệm chẩn đoán theo `mac_expiry_s`. |
| **Cụm suy luận** (`inferred_cluster_count`) | Số cụm được tạo từ bản ghi còn trong phạm vi phân tích. Có thể gồm ứng viên, cụm vừa hết hạn và cụm thiếu bằng chứng vị trí. |
| **Ứng viên** (`candidate_count`) | Cụm mới có quan sát hợp lệ, đang tích lũy bằng chứng xác nhận. |
| **Cụm đã xác nhận** (`confirmed_count`) | Cụm đạt điều kiện presence. Một phần các cụm này có thể ở ngoài phòng hoặc chưa rõ vị trí. |
| **Cụm thiếu quan sát** (`stale_count`) | Cụm từng được xác nhận nhưng thiếu Probe gần đây hoặc gặp gián đoạn thu. Có Probe hợp lệ trước khi hết hạn thì cụm có thể trở về `CONFIRMED`. |
| **Chưa rõ vị trí** (`location_unknown_count`) | Số cụm đã xác nhận mà bộ ước lượng chưa phân loại được trong/ngoài phòng. |
| **Nguồn MAC đã xác nhận** | Số địa chỉ MAC mà Sherlock theo MAC đang giữ ở trạng thái xác nhận hoặc thiếu quan sát nhưng chưa hết DT. Đây là bộ đếm theo địa chỉ. |
| **Thiết bị thật trong phòng** | Số thiết bị do người quan sát nhập trong tab **Ghi phiên & nhãn**. Hiển thị khi đang ghi phiên USB. |
| **Chênh lệch số đếm** | Nguồn MAC được Sherlock xác nhận trừ số thiết bị đã ghi nhãn. Dương là đếm dư, âm là đếm thiếu theo phép đối chiếu này. |

Ví dụ, nếu **Nguồn MAC đã xác nhận = 6** và **Thiết bị thật trong phòng = 3**, dashboard hiển thị chênh lệch **+3**. Một máy có thể đổi MAC, nhiều máy có thể trùng fingerprint, và sniffer có thể nghe nguồn phát ngoài phòng. Sự chênh lệch cần được đọc cùng điều kiện thí nghiệm.

## 3. Hai cách xác nhận hiện diện

**Sherlock theo MAC** dùng AT/WT/DT. Một địa chỉ có ít nhất một Probe qua lọc trong khe sẽ đóng góp một khe dương khi khe đóng. Ô **Thấy trong khe đang mở** đếm các MAC có Probe trong khe hiện tại, trước khi chốt xác nhận. Với khe 60 giây và DT = 3, một MAC đã xác nhận chỉ hết hiệu lực khi chốt ba khe trống liên tiếp sau khe cuối có Probe. Để quan sát bộ đếm giảm trong ca ra/vào, có thể cần gần 4 phút kể từ Probe cuối nếu Probe đến đầu khe.

**Presence theo cụm** dùng các quan sát cách nhau theo thời gian và giữ trạng thái theo ID cụm. Mặc định cần 3 quan sát cách nhau ít nhất 5 giây trong cửa sổ 30 giây. `STALE` mặc định sau 20 giây thiếu quan sát và `ABSENT` sau 60 giây kể từ Probe hợp lệ cuối, tính theo thời gian còn coverage. `ABSENT` biểu thị hết hạn bằng chứng quan sát, một thiết bị vẫn có thể ở trong phòng. [Máy trạng thái theo cụm](PRESENCE_STATE_MACHINE.md)

**Cửa sổ biểu đồ** mặc định 30 giây và có thể chọn 15, 30, 60 hoặc 120 giây. Đây là phạm vi hiển thị theo đồng hồ của nguồn. Cửa sổ xác nhận, Timeout, hết hạn MAC, cửa sổ RSSI và chân trời phân tích cụm 300 giây có chức năng riêng. [Hướng dẫn Dashboard](DASHBOARD_GUIDE.md)

## 4. Cách đọc bảng Device Cluster

| Cột | Cách đọc |
|---|---|
| **Cụm** | Mã tham chiếu trong nguồn hiện tại. Mã có thể đổi khi thuật toán phân cụm lại hoặc alias đầu tiên rời khỏi vùng dữ liệu phân tích. |
| **MAC alias** | Số địa chỉ MAC được liên kết vào cụm. |
| **Fingerprint** | Tóm tắt tối đa ba cấu trúc IE dạng mã–độ dài. Trùng cấu trúc là một dấu hiệu để liên kết. Nhiều thiết bị có thể có cùng cấu trúc. |
| **RSSI theo kênh** | `K` là kênh. dBm càng gần 0 thì tín hiệu thu càng mạnh. Median là đại diện trung tâm, còn `Δ` là độ dao động RSSI lớn nhất trong các alias trên kênh đó. |
| **Đầu / cuối** | Mốc thấy đầu và cuối tính theo giây của nguồn quan sát hoặc replay. |
| **Heuristic** | Điểm liên kết dựa trên IE, thời gian, RSSI và kênh. Điểm này chưa được hiệu chuẩn thành xác suất đúng. `N/A` có thể xuất hiện ở cụm đơn lẻ chưa có lần liên kết. |
| **Hiện diện / Vị trí** | Hiện diện dùng `CANDIDATE`, `CONFIRMED`, `STALE` và `ABSENT`. Vị trí của cụm xác nhận có thể là trong phòng, có khả năng ở ngoài hoặc `UNKNOWN`. |
| **Lý do và lịch sử** | Xem kết quả `MATCH`, `NON_MATCH`, `AMBIGUOUS` của các lần xem xét liên kết và lý do đổi trạng thái hiện diện. |

Giữ bố trí sniffer, kênh và tham chiếu RSSI nhất quán khi so sánh vị trí giữa các phiên. Với hopping hoặc cấu hình chưa có calibration phù hợp, dùng các bộ đếm MAC và cụm để quan sát luồng thu. [Cách tạo bộ tham chiếu](IN_ROOM_ESTIMATION.md)

## 5. Chất lượng thu và trạng thái thiếu dữ liệu

| Thông số hoặc trạng thái | Cách đọc |
|---|---|
| **LIVE / REPLAY / DEMO** | Thu trực tiếp / phát lại phiên đã lưu / phát dữ liệu mô phỏng. Dùng nhãn nguồn khi ghi chú kết quả. |
| **Heartbeat** | Tuổi của bản tin trạng thái hợp lệ gần nhất. Khi hết hạn, các số đo phụ thuộc nguồn có thể hiện dấu `—` hoặc `N/A`. |
| **Kênh / thời gian nghe** | Kênh hiện tại và dwell. Ở chế độ hopping, một thiết bị có thể phát trên kênh khác khi sniffer đang nghe kênh hiện tại. |
| **Probe board đã bắt / Gói rơi** | Bộ đếm firmware về Probe nhận và mục bị rơi tại hàng đợi thu. Xem mức tăng theo thời gian để đánh giá tải. |
| **Probe qua bộ lọc / Bị lọc RSSI / Bị loại theo MAC** | Bộ đếm của thuật toán theo các điều kiện lọc. Các bộ đếm này có thể bắt đầu tại mốc khác bộ đếm firmware. |
| **Lỗi serial / Dòng lỗi** | Lỗi xuất serial do firmware báo, hoặc dòng máy tính nhận nhưng parser không đọc được. |
| **Nối lại USB / Giới hạn bộ nhớ** | Số lần thử nối lại và số lượt quan sát bị từ chối vì bảng nguồn đầy. |
| **`0`, `UNKNOWN`, `N/A`** | `0` là số đếm tại mốc có đủ điều kiện công bố. `UNKNOWN` là chưa phân loại được vị trí hoặc chưa ước lượng được số trong phòng. `N/A` và `—` biểu thị dữ liệu thiếu hoặc chỉ số chưa áp dụng. |

## 6. Đọc báo cáo của phiên đã lưu

Tab **Kết quả đã lưu** hiện so sánh **MAC trong cửa sổ**, **Timeout** và **Sherlock theo MAC** với nhãn số thiết bị thực. Công cụ đánh giá offline A/B/C dùng lệnh replay riêng để so thêm clustering và in-room. [Quy trình đánh giá A/B/C](EXPERIMENT_PROTOCOL.md)

| Chỉ số | Cách tính và cách diễn giải |
|---|---|
| **Coverage** | Tỷ lệ mốc có dữ liệu hợp lệ và có nhãn. Khi so hai phiên, đọc coverage cùng sai số để biết mỗi báo cáo đã bỏ qua bao nhiêu mốc. |
| **MAE** | Trung bình giá trị tuyệt đối của `dự đoán − nhãn`, tính theo số thiết bị. Thấp hơn nghĩa là chênh lệch tuyệt đối trung bình nhỏ hơn. |
| **Đếm đúng** | Tỷ lệ mốc mà dự đoán bằng đúng nhãn. |
| **Bias** | Trung bình của `dự đoán − nhãn`. Dương là thiên về đếm dư, âm là thiên về đếm thiếu. Dư và thiếu có thể triệt tiêu nhau khi lấy trung bình. |
| **PCC** | Tương quan giữa hai chuỗi dự đoán và nhãn. Có thể không xác định nếu nhãn hoặc dự đoán giữ nguyên suốt phiên. |
| **MRE** | Trung bình sai số tuyệt đối chia cho nhãn trên các mốc có nhãn lớn hơn 0. Dashboard hiển thị theo phần trăm. |
| **MAE (nhãn 0)** | Sai số tuyệt đối trung bình ở các mốc phòng được ghi nhận có 0 thiết bị. Hữu ích khi phân tích đếm dư do nguồn nền hoặc thiết bị hành lang. |
| **Độ trễ chạm số đếm mới** | Thời gian từ lúc đổi nhãn đến mốc dự đoán đạt mức mới. Kiểm tra thêm cột **Chưa đạt mức mới** vì trung bình độ trễ chỉ tính trên các sự kiện đã đạt. |

Khi phân tích một lượt đo, đọc theo thứ tự **nguồn và heartbeat → RSSI và kênh → bộ đếm MAC và cụm → nhãn thực tế → coverage và sai số**. Giữ cùng cấu hình và kịch bản khi đối chiếu hai phiên.
