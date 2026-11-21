# Máy trạng thái Sherlock adaptation

## Cơ sở và phạm vi

Oliveira, Schneider, De Souza, Shen, *Mobile Device Detection Through WiFi Probe
Request Analysis*, IEEE Access 7 (2019), DOI 10.1109/ACCESS.2019.2925406.
Tham khảo phần IV/Hình 5 và phần VI. Bài báo có khảo sát thu một giao diện và
nhiều giao diện; bản ESP32-C3 này triển khai **một giao diện thu**, không tương
đương prototype đa giao diện của tác giả.

Nguồn bài: https://www.researchgate.net/publication/334069600_Mobile_Device_Detection_Through_WiFi_Probe_Request_Analysis
API chip: https://docs.espressif.com/projects/esp-idf/en/v5.5.4/esp32c3/api-guides/wifi.html

Đây là triển khai độc lập diễn giải máy trạng thái từ bài, đã đối chiếu phần bộ đếm trong mã gốc
[repo Sherlock](https://github.com/luizsoliveira/sherlock), chưa chạy nguyên bộ PHP trên dataset gốc. Không dùng chữ “tái lập chính xác” hay suy ra sẽ đạt sai số của bài báo.

## Quy ước chính xác v2 (sherlock-repo-slots-v2)

Đã đối chiếu quantifyPeopleBySlots.php tại commit738a896258d9446717c5035bb8b5faae18f2adc4.
Khe = floor(elapsed_s / slot_s), chốt tại cuối khe. Mỗi MAC tính có/không có
Probe; nhiều gói trong một khe không làm tăng nhiều lần bộ đếm.

| Trạng thái | Quan sát trong khe đã chốt | Xử lý |
|---|---|---|
| Chưa theo dõi | Có Probe | Tạo candidate, AT counter=1 ngay |
| candidate | Có Probe | AT tăng, WT counter về0; đủ AT thì xác nhận |
| candidate | Không có Probe | WT counter tăng; đủ WT liên tiếp thì hủy |
| present | Khe trống đầu tiên | departing, DT counter=1 ngay |
| departing | Có Probe | present, DT counter về0 |
| departing | Không có Probe | DT tăng; đủ DT thì hết hiệu lực xác nhận |

AT=1 xác nhận ngay khi chốt khe dương đầu. DT=1 hết hiệu lực ngay khi chốt khe
trống đầu sau xác nhận. AT6 cần sáu khe dương tổng cộng (không phải bảy).
WT>1 cho phép gián đoạn, không tự xóa số khe dương chỉ vì một khe trống.

Ví dụ slot10s/AT2: gói tại1s và11s -> xác nhận tại20s. DT2 và sau đó không có:
30s chuyển thiếu quan sát (DT1), 40s hết hiệu lực. Đây không chứng minh đã rời.

Khác bản PHP offline: không backdate đường số đếm về khe đầu nghi ngờ. Event
lưu first_seen_s, confirmed_at_s và t_s. Chỉ confirmed_at_s mới là lúc có đủ
bằng chứng để đưa nguồn vào số đếm online. Báo độ trễ theo sự kiện causal.

Các ngưỡng mặc định6/2/6 được giữ làm cấu hình tham chiếu bài báo; file PHP
trong repo đang ghi7/4/7 (AT/WT/DT). Có thể thay các số nhưng không đổi quy tắc
đếm. Đây là adaptation có thêm quản lý chất lượng dữ liệu, không phải kết quả
bit-for-bit của mọi script hoặc thí nghiệm trong repo.

## Mở rộng và đối chứng

- Unique: số MAC có gói trong unique_window_s.
- Timeout: đủ confirm_hits trong confirm_window_s; còn hiệu lực timeout_s sau
  gói cuối. Đây là đối chứng khác với Sherlock.
- Tùy chọn ngưỡng RSSI và exclusion áp dụng cùng trước cả ba phương pháp.
- Chỉ khi retry=true và cùng MAC/channel/frame_seq trong 100ms mới triệt quan sát lặp;
  không dùng frame_seq để ghép MAC. Đây là quy tắc bổ sung, cần ghi khi báo cáo.
- max_sources giới hạn bộ nhớ và báo capacity_drops, không che tình trạng bão MAC.

Không dùng bit U/L để xóa mọi MAC local. Không giả định MAC ngẫu nhiên chỉ tồn
tại ngắn. Nguồn đổi MAC trước khi đủ AT có thể không bao giờ được xác nhận;
MAC cũ đang departing và MAC mới đã present có thể làm đếm dư. Máy trạng thái
không khôi phục danh tính hoặc tự giải quyết mọi loại randomization.

## Đồng hồ và thiếu dữ liệu

Live dùng monotonic laptop tương đối đầu phiên; raw giữ cả ts_us trên board,
boot_id, UTC nhận và host_elapsed_s. Không so thời gian boot giữa các board.
Offline dùng host_elapsed_s, không dùng tốc độ phát replay để đổi tham số.

Heartbeat một giây. Quá heartbeat_s, radio inactive hoặc disconnect: valid=false,
result=null. Không dùng count=0 biểu diễn mất dữ liệu. Boot mới, control record reconnect hoặc heartbeat
trở lại sau gap dài xóa tracks, xác nhận lại; đều có sự kiện reset chẩn đoán. Thời gian có dữ liệu hợp lệ được
báo coverage. Khi kết thúc file không suy đoán thêm một quá trình rời.

Kênh 1–13, dwell3s tạo vòng danh nghĩa39s. Khoảng không nghe một kênh không phải
bằng chứng điện thoại không phát. RSSI cao/thấp không chắc chắn phân biệt trong
phòng/ngoài phòng; nguồn ở phòng bên đủ lâu vẫn có thể được xác nhận.
