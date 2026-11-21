# Kế hoạch triển khai nhánh phát hiện thiết bị WiFi bằng Probe Request

## Thông tin và mục tiêu

Phạm vi: một ESP32-C3 sniffer và laptop, tham khảo máy trạng thái Sherlock của
Oliveira et al. (2019). Đầu ra trực tiếp là số nguồn MAC đã xác nhận và hiện diện
quan sát gần đây. Đánh giá khả năng ước lượng số thiết bị bằng ground truth riêng.
Không triển khai CSI, học máy phát hiện người, tìm MAC thật hay nhận dạng người.

Thời gian đề xuất: **4 tuần**, có thể kéo dài phần thu nếu điện thoại phát probe
thưa hoặc cần bổ sung buổi test. Không đặt trước con số độ chính xác.

## Tổng tiến độ

| Giai đoạn | Thời gian dự kiến | Đầu ra bắt buộc |
|---|---|---|
| 1. Cài đặt và nạp | Ngày 1–2 | Một board chạy sniffer, dashboard chạy |
| 2. Khảo sát khả năng quan sát | Ngày 3–5 | Raw thật, bảng hành vi và heatmap |
| 3. Xác minh Sherlock | Ngày 6–8 | State machine đúng quy ước, ba đối chứng |
| 4. Thu chiến dịch thực nghiệm | Ngày 9–15 | Phiên phát triển/test, nhãn thiết bị thật |
| 5. Phân tích và chọn tham số | Ngày 16–20 | Cấu hình chốt, báo cáo test độc lập |
| 6. Hoàn thiện sản phẩm và báo cáo | Ngày 21–24 | Demo, mã nguồn, dataset chọn lọc và báo cáo |

## Giai đoạn 1 — Cài đặt, nạp, kiểm tra đường thu

1. Cài ứng dụng bằng scripts/setup.sh, chạy replay có nhãn MÔ PHỎNG.
2. Chỉ cắm một C3, xác định cổng CH340, nạp firmware/sniffer với ESP-IDF5.5.4.
3. Kiểm tra status 1Hz, scan_mode, channel, probe_seen/dropped, serial_errors.
4. Tạm thử fixed6 rồi cấu hình hopping1–13/dwell3s theo country policy đúng nơi dùng.
5. Mở dashboard, đóng mọi monitor đang dùng cùng cổng.

**Điều kiện qua giai đoạn:** nhận status đúng node sniffer, dashboard nguồn hợp
lệ, không xung đột cổng. Có ít nhất một phiên raw mở lại được. Chưa cần có số
Sherlock>0 vì AT dài. Nếu chưa có Probe thì sang khảo sát khả thi, không giả số.

## Giai đoạn 2 — Khảo sát điện thoại thực tế

Dùng ít nhất vài mẫu điện thoại có thể mượn được; ghi rõ model, OS, WiFi và trạng
thái màn hình. Không cần thiết bị kết nối cùng AP. Mỗi thử nghiệm giữ thiết bị
và vị trí cố định, thu20–30 phút ban đầu rồi tăng nếu không đủ quan sát.

| Kịch bản | Nhãn | Cần ghi |
|---|---|---|
| Không thiết bị thử nghiệm | 0 | Các nguồn nền trong/phòng bên vẫn quan sát |
| Một máy, màn hình mở | 1 | Gói đầu, số khe dương, khoảng gián đoạn |
| Một máy, khóa màn hình | 1 | Khác biệt quan sát so với mở màn hình |
| Đã kết nối AP | 1 | Có bị quan sát thưa/không thấy không |
| Chưa kết nối AP | 1 | Hành vi khi dò mạng bình thường |
| Fixed so với hopping | Không đổi số máy | Tách ảnh hưởng chiến lược thu |

Chạy inspect để có probe-slots.csv và heatmap. Khoảng im lặng quan sát được
không phải toàn bộ thời gian thiết bị ngừng phát: sniffer có thể ở kênh khác.
Nếu muốn gán các probe về điện thoại A/B, cần phiên kiểm soát một máy hoặc
nguồn tham chiếu có nhãn; không suy đoán chỉ từ RSSI/MAC.

**Điều kiện qua giai đoạn:** biết những điều kiện thiết bị có/không được quan sát,
serial ổn định, thông số thu và nguồn nền được ghi rõ. Nếu đa số máy không có
MAC đủ bền cho AT, ghi đây là hạn chế và thử tham số ngắn hơn; không hứa máy
trạng thái sẽ tự khắc phục MAC randomization.

## Giai đoạn 3 — Xác minh logic trước khi chấm hiệu quả

1. Chạy tests. Dùng demo slot5s/AT2/WT2/DT2 để quan sát dễ.
2. Kiểm tra một burst nhiều gói không biến thành nhiều khe dương.
3. Kiểm tra candidate bị hủy bởi WT, departing quay lại present khi thấy gói.
4. Kiểm tra rút USB, reset board, radio inactive, hết replay -> không giả count0.
5. Đối chiếu cùng raw giữa live và đánh giá offline; đọc quy ước ../DAC_TA_DU_AN.md.
6. Chuyển về tham chiếu slot60/AT6/WT2/DT6. RSSI mặc định không cắt bổ sung.

**Điều kiện qua:** có bảng minh chứng quy tắc chuyển trạng thái và các tình
huống lỗi. Mã được gọi là adaptation, chưa tuyên bố tương đương mã tác giả.

## Giai đoạn 4 — Thu dataset có ground truth

Mỗi phiên ghi bố trí, kênh/dwell, model/OS/trạng thái thiết bị, cấu hình phần mềm,
thời gian và số thiết bị thật. Cùng điều kiện nên lặp tối thiểu3 buổi như kế hoạch
khởi đầu; số lần này không bảo đảm đủ để khái quát kết quả.

- Kịch bản cơ bản 0→1→2→3→2→1→0; mỗi mức giữ đủ cho xác nhận và quan sát ổn định.
- Có ít nhất một đoạn0 đủ dài để đo đếm dư và thời gian hết hạn.
- Một máy ở lại lâu nhưng khóa màn hình; thử đi ngang dưới thời gian xác nhận.
- Thiết bị ở phòng bên trong thời gian dài, phòng mục tiêu có nhãn0.
- Một người mang hai thiết bị, minh họa không đồng nhất số người/số thiết bị.
- Thử thay trạng thái WiFi/khóa màn hình có thể làm thay địa chỉ quan sát; không
  mặc định thao tác nào cũng gây đổi MAC trên mọi mẫu máy.

Với tham chiếu phút, toàn bộ kịch bản nhiều mức thường cần dài hơn60 phút; có
thể chia thành các phiên sự kiện nhỏ. Bấm Ghi thay đổi nhãn ngay lúc thêm/bớt.
Giữ thêm đủ đoạn ổn định sau thay đổi, không kết thúc ngay khi mang thiết bị ra.

**Chia dữ liệu trước phân tích:** các buổi phát triển và buổi test khác nhau.
Các đoạn liên tiếp từ cùng buổi không được chia sang hai tập để tăng số phiên.
Giữ test cuối chưa dùng để chọn tham số.

## Giai đoạn 5 — So sánh và hiệu chỉnh

A. Dùng cùng dữ liệu để so unique-MAC, timeout, Sherlock; báo cả ba.
B. Giữ tham chiếu ban đầu làm mốc, khảo sát slot/AT/WT/DT trên development.
C. RSSI là thí nghiệm mở rộng riêng; không trộn thay đổi RSSI và hopping rồi
kết luận riêng nguyên nhân. Khi chỉ có một sniffer, fixed/hopping thu khác lần,
cần lặp và thừa nhận không phải đối chứng đồng thời cùng truyền dẫn.
D. Khóa cấu hình, chạy test. Nếu sửa dựa vào test phải thu test mới.

Báo cáo tối thiểu:

| Nhóm | Chỉ số / đồ thị |
|---|---|
| Chất lượng thu | Heartbeat, drop, lỗi parser/UART, coverage |
| Quan sát | Gói/MAC/khe, heatmap, khoảng gián đoạn quan sát |
| Số lượng | MAE, bias, tỷ lệ đúng, MRE nhãn>0, MAE riêng nhãn0 |
| Biến động | PCC nếu xác định, đồ thị đếm và ground truth |
| Sự kiện | Độ trễ chạm mức đếm mới, số/tỷ lệ censored |

Không gọi PCC là accuracy. Độ trễ count không phải nhận dạng đúng từng máy;
đếm dư có sẵn có thể khiến đạt mức mới ngay. Để đánh giá phát hiện từng thiết
bị, cần thêm dữ liệu có nhãn gán nguồn/thiết bị tin cậy và định nghĩa metric khác.

**Điều kiện qua:** kết quả test độc lập có đủ mẫu từng tình huống, hoặc ghi rõ
chưa đánh giá. Kết luận phải giới hạn theo phòng, thiết bị và chế độ thu đã thử.

## Giai đoạn 6 — Hoàn thiện sản phẩm và demo

- Chạy một phiên dài kiểm tra bộ nhớ, queue, USB và lưu file.
- Chốt giao diện: trạng thái nguồn rõ, số nguồn xác nhận, không trình bày MAC là
  danh tính thật; source trực tiếp/replay/synthetic phải phân biệt.
- Chuẩn bị dataset được phép chia sẻ, cấu hình, report.json, timeline.csv, heatmap.
- Lưu phiên demo thật dài đủ và replay để có thể trình bày trong thời gian ngắn.
  Replay phải ghi rõ, không diễn như nhận diện tức thì ngoài đời.
- Viết báo cáo: cơ sở bài báo, phần kế thừa, quy ước triển khai, phương pháp thu,
  ground truth, kết quả, sai số/độ trễ và giới hạn MAC randomization.

Kịch bản demo: nguồn serial hợp lệ -> xem Probe -> candidate/present/departing ->
so ba phương pháp -> xem nhãn thật và báo cáo -> rút USB để thấy mất dữ liệu.
Nếu dùng tham số demo ngắn, công bố ngay và không dùng nó như kết quả tham chiếu.

## Thứ tự bắt đầu ngay

1. Giải nén bản wifi-device-sherlock, chạy setup/run.
2. Nạp một board thành sniffer, cất hai board còn lại.
3. Chạy thử30 phút với một điện thoại và một phiên nền riêng.
4. Phân tích heatmap trước khi quyết định có đủ dữ liệu cho AT=6 hay cần thử ngắn hơn.
