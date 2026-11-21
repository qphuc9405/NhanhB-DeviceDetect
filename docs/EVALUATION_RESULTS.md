# Kết quả kiểm chứng pipeline phát hiện thiết bị vật lý

## Tình trạng kiểm chứng

**Chưa có bộ phiên RF có ground truth để kết luận độ chính xác.** Khi kiểm tra, FastAPI trả 0 phiên đã lưu. Công cụ đo đã chạy được trên fixture tổng hợp và đường thu phần cứng đang có heartbeat. MAE, RMSE, độ trễ và lỗi gộp/tách trên thiết bị thật vẫn chờ bộ phiên giữ lại có nhãn. [Quy trình thu và replay](EXPERIMENT_PROTOCOL.md)

| Kiểm tra | Kết quả tại máy kiểm tra ngày 20/11/2026 |
|---|---|
| Môi trường | Ubuntu 22.04.5 LTS, Python 3.12.16, Node.js 22.23.4, ESP-IDF v5.5.4. |
| Build ESP32-C3 | Bản hopping và bản fixed kênh 6 đều build thành công trong bản sao nguồn ở thư mục tạm. Firmware ứng dụng lần lượt `0xb98f0` và `0xb97f0` byte. |
| USB và backend | Có CH340 tại `/dev/ttyUSB0`; backend đang dùng serial và báo heartbeat hợp lệ, hopping với dwell 3.000 ms và 460800 baud. Ảnh chụp lúc 22:05:10 (UTC+7) báo kênh 5, `probe_seen=59`, `probe_dropped=0`, `serial_errors=0`. Đây là bộ đếm tại một thời điểm, chưa có nhãn thiết bị và chưa phải phép đo tỷ lệ rơi trong điều kiện tải. |
| Fixed kênh 6 | Đã kiểm chứng build. Snapshot board đang chạy thuộc chế độ hopping. |

Binary build kiểm chứng ở máy này có SHA-256 lần lượt `76586b49436e10916510803f8f05025d52f454aed5ed400bbc6322f3203a4e62` (hopping) và `47f60f496d0b28661f0d8f39b75d7282ab751cc315e96ff5d592b8eef0e1bee7` (fixed). Các hash chỉ dùng nhận diện hai artifact build này. Phiên RF thực tế nên ghi hash của binary đã nạp.

## Smoke test SYNTHETIC

Một fixture test 89 mốc, `step_s=1`, `unique_window_s=12`, đánh giá việc khóa split, phát lại, tính sai số và xuất artifact. Fixture có hai MAC khác nhau phát chồng lấn và không có calibration. Nó được tạo bằng lệnh `synthetic` trong hướng dẫn.

| Phương pháp | Mốc có dự đoán | MAE | RMSE | Overcount | Undercount | Median vào / ra |
|---|---:|---:|---:|---:|---:|---|
| A. MAC-only | 89/89 | 0,292 | 0,540 | 25,8% | 3,4% | 1,5 s / 11,5 s |
| B. IE + clustering | 89/89 | 0,292 | 0,540 | 25,8% | 3,4% | 1,5 s / 11,5 s |
| C. Clustering + presence + in-room | 0/89 | N/A | N/A | N/A | N/A | N/A |

Hai phương pháp A/B đạt ngưỡng của 2/2 sự kiện vào và 2/2 sự kiện ra trong fixture. C để trống vì thiếu tham chiếu. Tập mốc chung A/B/C rỗng. Fixture này thiếu nhãn alias, nên không cho điểm over-merge/over-split. Unit test riêng kiểm tra phép tính lỗi cặp và một trường hợp C có tham chiếu tổng hợp. Các số trong bảng chỉ xác minh công cụ tính toán.

Artifact smoke local nằm ở `data/results/physical-evaluation-smoke/report/`. Lệnh tái tạo và schema CSV nằm trong [quy trình thí nghiệm](EXPERIMENT_PROTOCOL.md#5-schema-csv-và-artifact).

## Kết luận và giới hạn

| Phần dự án | Trạng thái |
|---|---|
| Sniffer, serial, parser, lưu phiên và replay | Có triển khai. Đường thu hopping đang có heartbeat và Probe. Cả cấu hình firmware hopping/fixed đã build. |
| MAC Tracker, IE fingerprint, clustering và presence | Có triển khai và có test cho dữ liệu tổng hợp. Độ ổn định alias, over-merge và over-split trên RF thật cần nhãn độc lập. |
| Ước lượng trong phòng và dashboard | Có đường chạy từ dữ liệu backend với abstention. Định lượng trong/ngoài phòng cần một bố trí fixed khớp bộ tham chiếu và dữ liệu test giữ lại. |
| Bộ đánh giá A/B/C | Có lưu Test ID, timestamp, checksum, cấu hình, replay theo mốc, coverage, CSV và biểu đồ. Hỗ trợ nhãn count và nhãn alias riêng. |

Sniffer chỉ quan sát một kênh tại từng thời điểm. Thiết bị có thể im lặng, phát ngoài kênh đang nghe hoặc đổi MAC. Nhiều thiết bị có thể cùng cấu trúc IE. Một vị trí RSSI có thể không phân tách được trong và ngoài phòng. Các nguồn sai số đó ảnh hưởng trực tiếp đến coverage và đến khả năng diễn giải một mốc thiếu Probe. Độ trễ tổng đếm còn phụ thuộc bước lấy mẫu, cấu hình timeout và thời điểm người quan sát ghi nhãn.

Ưu tiên tiếp theo là thu các phiên fixed có nhãn gần, xa và hành lang để tạo tập tham chiếu development. Sau đó khóa cấu hình, chạy đủ các kịch bản trên batch giữ lại và báo MAE/RMSE cùng coverage, phép đo độ trễ có kiểm duyệt, và lỗi cặp trên các alias đã xác minh. Chỉ khi có bảng giữ lại mới có căn cứ kết luận phương pháp nào giảm đếm sai trong bố trí đã đo.
