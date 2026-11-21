# WiFi Device Sherlock

Dự án phát hiện và theo dõi **nguồn MAC từ Probe Request WiFi** bằng một ESP32-C3 và laptop. Backend Python xử lý dữ liệu serial, chạy máy trạng thái Sherlock adaptation và lưu phiên thực nghiệm; dashboard React hỗ trợ quan sát, ghi nhãn và đánh giá.

Số nguồn MAC được xác nhận là đầu ra của thuật toán, có thể khác số thiết bị thật. Dự án hiện không thu CSI, không huấn luyện mô hình phát hiện người, không truy tìm MAC gốc và không liệt kê danh sách máy đang kết nối router.

Đặc tả thống nhất: [DAC_TA_DU_AN.md](DAC_TA_DU_AN.md).

## 1. Yêu cầu

- Ubuntu/Linux, terminal Bash; có thể dùng terminal tích hợp VS Code.
- Python **3.12**, có `venv`; Node.js **từ 22** và npm.
- Internet khi cài thư viện lần đầu.
- Khi thu thật: ESP32-C3 đã nạp firmware `firmware/sniffer`, cáp USB có truyền dữ liệu. Không cần board cho demo phần mềm.

Kiểm tra công cụ:

```bash
python3.12 --version
node --version
npm --version
```

Nếu Ubuntu báo thiếu `venv` khi tạo môi trường Python cài bằng apt:

```bash
sudo apt install python3.12-venv
```

## 2. Chạy trên terminal VS Code

Mở **File → Open Folder** và chọn thư mục dự án, sau đó **Terminal → New Terminal**. Tại thư mục chứa `run.sh`, chạy:

```bash
./run.sh
```

Hoặc dùng `bash run.sh`. Mở địa chỉ mà script in trong terminal, thường là **http://127.0.0.1:8000**. Dừng bằng **Ctrl + C**.

Script dùng Python tại `.venv/bin/python`. Nếu chưa có môi trường hoặc chưa build giao diện, script tự gọi `scripts/setup.sh` để cài đặt và build. Khi tạo môi trường, script ưu tiên `$HOME/.local/bin/python3.12` nếu có; trên máy hiện tại là `/home/phuc/.local/bin/python3.12`. Không cần nhập lại đường dẫn hoặc tự activate `.venv` mỗi lần chạy.

Để cài lại thư viện/build hoặc chọn Python riêng:

```bash
bash scripts/setup.sh
# Chỉ dùng dòng dưới khi Python nằm ở vị trí riêng; thay đường dẫn thực tế.
PYTHON=/duong/dan/python3.12 bash scripts/setup.sh
```

Hướng dẫn terminal chi tiết: [HUONG_DAN_CHAY_VSCODE.md](HUONG_DAN_CHAY_VSCODE.md).

## 3. Sử dụng dashboard

### Kết nối & quan sát

1. Cắm ESP32-C3, chọn đúng cổng USB rồi bấm **Kết nối USB**.
2. Chờ trạng thái **Đang nhận dữ liệu**, heartbeat hợp lệ.
3. Xem **Probe vừa nhận · trước bộ lọc**. MAC hiện cùng RSSI, thời gian và lý do chấp nhận hoặc loại gói. Mỗi Probe hợp lệ về định dạng gia hạn mục MAC trong bộ đệm, kể cả khi gói bị lọc RSSI. Sau hơn `mac_expiry_s` giây không thấy MAC, mục được xóa khỏi bảng và giải phóng chỗ cho MAC mới. Dữ liệu raw đã ghi vẫn dùng để đối chiếu.
4. Xem **Nguồn đang theo dõi**: trạng thái Sherlock cập nhật sau khi chốt khe. Xác nhận cần đủ số khe AT; không đồng nghĩa nhận gói là được xác nhận ngay.

Các số chính: nguồn MAC đã xác nhận, nhãn thiết bị thật đã lưu và chênh lệch. Khi chưa có nguồn hợp lệ, hiển thị `—`; không coi mất dữ liệu là 0 thiết bị.

**Tắt lọc RSSI:** trong **Phòng & bộ lọc**, mở **Điều chỉnh phạm vi bằng RSSI**, bỏ tích **Bật lọc tín hiệu bằng RSSI**, bấm **Áp dụng bộ lọc**. Khi hiện **Bộ lọc đang tắt** là hoàn tất. Nếu đang ghi phiên, kết thúc phiên trước; hoặc chọn lưu phiên hiện tại và tiếp tục phiên mới theo lựa chọn trên giao diện. Đổi RSSI sẽ xác nhận lại các nguồn, không ngắt radio.

**Demo:** khi đang ngắt nguồn, bấm **Chạy demo nhanh**. Backend tự tạo dữ liệu tổng hợp cho demo. Phiên demo chạy 10× với khe 5 giây, AT/WT/DT = 2/2/2 và tắt lọc RSSI. Ngắt nguồn sau demo để quay về cấu hình thu đã lưu.

### Ghi phiên & nhãn

1. Điền phòng/bố trí trong tab quan sát.
2. Sang **Ghi phiên & nhãn**; nhập số thiết bị thật, mô tả model/OS/WiFi/màn hình, số người tùy chọn và ghi chú.
3. Bấm **Bắt đầu ghi**; cần USB và heartbeat hợp lệ.
4. Khi thêm/bớt thiết bị, nhập số mới rồi **Ghi số mới** ngay tại thời điểm thay đổi. Số đang nhập chưa tự trở thành nhãn đã lưu.
5. Bấm **Kết thúc & lưu** để chuyển sang kết quả.

Số người được lưu riêng; báo cáo hiện đánh giá theo **số thiết bị thật**, không theo số người.

### Kết quả đã lưu và Nâng cao

- **Xem kết quả**: so Sherlock, unique-MAC và timeout; xem coverage, MAE, bias, tỷ lệ đếm đúng, PCC, MRE, sai số nhãn 0 và độ trễ.
- Tải raw JSONL, nhãn, metadata, báo cáo JSON và timeline CSV.
- **Tạo heatmap / bảng khe** rồi mở heatmap hoặc tải bảng CSV.
- **Nâng cao**: cấu hình đầy đủ, loại trừ MAC, replay phiên đã kết thúc theo cấu hình đã lưu của phiên, chẩn đoán MAC, ghi dấu mốc thao tác và nhật ký thuật toán.

## 4. Cấu hình đang dùng

Backend đọc [configs/probe.json](configs/probe.json). Giá trị tại thời điểm viết tài liệu:

| Tham số | Giá trị |
|---|---|
| Khe Sherlock | 60 giây |
| AT / WT / DT | 2 / 2 / 3 khe |
| RSSI | −127: tắt cắt RSSI bổ sung |
| Cửa sổ unique-MAC | 60 giây |
| Timeout | 120 giây |
| Thời gian giữ MAC trong bộ đệm chẩn đoán (`mac_expiry_s`) | 120 giây |
| Xác nhận timeout | 2 gói trong 30 giây |
| Heartbeat timeout | 5 giây |
| Giới hạn nguồn | 2000 |

Đây là cấu hình thử hiện tại, chưa phải thông số đã chứng minh tối ưu. `configs/reference.json` dùng 60 giây và 6/2/6; cấu hình demo ngắn phục vụ kiểm tra phần mềm. Dashboard có thể ghi đè cấu hình; file và cấu hình hiển thị trên dashboard là giá trị thực tế cần kiểm tra trước mỗi buổi thu.

## 5. Cắm và nạp ESP32-C3

Firmware mục tiêu ESP-IDF **5.5.4** (đã thử build và chạy trên **6.1**), UART0 **460800 baud**, TX GPIO21 / RX GPIO20 cho board dùng CH340. Không mặc định cấu hình này phù hợp mọi board USB native. Không dùng 921600: thử với CH340 bị mất byte ở 2,4% số dòng, 460800 thì 0%.

```bash
source ~/esp/esp-idf/export.sh
idf.py --version
.venv/bin/python -m serial.tools.list_ports -v
bash scripts/flash.sh /dev/ttyUSB0
```

Thay cổng bằng cổng thực tế. Lệnh flash thay chương trình trên board; đóng dashboard/serial monitor đang giữ cổng trước khi nạp. Nếu build lỗi vì đường dẫn chứa khoảng trắng/ngoặc, dùng bản sao nguồn firmware ở đường dẫn không có các ký tự đó; xem [ghi chú board](docs/BOARD_SETUP.md).

Firmware mặc định nghe lần lượt kênh 1–13, 3 giây/kênh, country VN. Muốn đổi fixed/hopping/dwell: vào `firmware/sniffer`, chạy `idf.py menuconfig`, mục **Probe research sniffer**, rồi build/flash lại. Dashboard không đổi kênh radio.

Nếu thiếu quyền USB trên Ubuntu:

```bash
sudo usermod -aG dialout "$USER"
```

Đăng xuất/đăng nhập lại. Không chạy backend bằng `sudo`. Nếu cần monitor, dùng `idf.py -p /dev/ttyUSB0 -b 460800 monitor` trong thư mục firmware, thoát bằng **Ctrl + ]** trước khi dashboard kết nối.

## 6. Khi không thấy MAC

- **Chưa có heartbeat:** kiểm tra cáp, cổng, quyền USB, đúng firmware JSONL và baud. Chỉ một tiến trình được mở serial.
- **Heartbeat có, chưa có Probe:** firmware chỉ thu Probe Request; thiết bị đang kết nối WiFi có thể không phát Probe trong lúc quan sát. Thử mở danh sách mạng trên máy đặt gần board, quan sát qua vài vòng hopping. Board chỉ nghe WiFi 2.4 GHz, một kênh tại một thời điểm.
- **Có MAC trong bảng trước lọc nhưng không có nguồn theo dõi:** xem lý do bị loại, tắt RSSI để kiểm tra, xem danh sách MAC loại trừ; chờ chốt khe và tích lũy AT.
- **Cổng 8000 mặc định bận:** `run.sh` tự chọn cổng trống. Để chọn cổng cụ thể, chạy `WIFI_PORT=8001 bash run.sh` hoặc đặt `WIFI_PORT` trong `.env`.
- **Giao diện chưa đổi sau sửa mã:** chạy `npm run build`, tải lại bằng **Ctrl + Shift + R**. `run.sh` không tự build lại khi đã có `frontend/dist`.

Trạng thái chẩn đoán: http://127.0.0.1:8000/api/probe/state. API tương tác: http://127.0.0.1:8000/docs.

## 7. Dữ liệu và công cụ offline

Phiên thật nằm ở `data/runtime/experiments/<id>/`; SQLite ở `data/runtime/metadata.sqlite3`. Raw giữ **MAC đầy đủ**, chưa băm hoặc ẩn danh. Chỉ chia sẻ dữ liệu đã được phép và xử lý phù hợp; rút gọn MAC trên báo cáo không ẩn danh raw.

```bash
.venv/bin/python -m research.inspect --session data/runtime/experiments/ID
.venv/bin/python -m research.evaluate --session data/runtime/experiments/ID
.venv/bin/python -m research.sweep --root data/runtime/experiments --split configs/split.json --output data/results
```

Thay `ID` bằng phiên thật. Trước khi sweep, tạo `configs/split.json` từ `configs/split.example.json`, chia buổi development/test độc lập. Không để các đoạn cùng buổi xuất hiện ở cả hai tập.

### Kiểm kê và so sánh dấu vân tay IE (thử nghiệm)

Firmware gửi trường `ie` với mã và độ dài của tối đa 24 Information Element theo thứ tự. CLI thống kê các cấu trúc IE trong log và có thể xuất kiểm kê từng loại IE.

```bash
.venv/bin/python -m research.ie_fingerprint data/runtime/experiments/ID/raw.jsonl --rssi-min -45 --report ie-report.json
```

Thu dữ liệu cho việc này nên nghe cố định một kênh để bắt trọn từng đợt quét (xoá `firmware/sniffer/sdkconfig` trước nếu đã build bản nhảy kênh):

```bash
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.fixed" build
```

Nhiều MAC có thể cùng cấu trúc IE. Xem phiên bản, cách tính điểm tương đồng và giới hạn dữ liệu ở [thiết kế IE fingerprint](docs/IE_FINGERPRINT_DESIGN.md).

Các thử nghiệm trước đây ghi nhận 11 MAC trong 2,5 phút thuộc một nhóm IE khi thử với OPPO Find X6 Pro, và hơn 100 MAC cùng dãy IE phổ biến ở trường. Hiện workspace thiếu log gốc để kiểm tra lại các kết quả này.

## 8. Phát triển và kiểm tra

```bash
npm run dev
```

Lệnh này chạy backend cổng 8000 và Vite cổng 5173. Mở http://127.0.0.1:5173; dừng phiên `run.sh` trước để tránh trùng cổng.

```bash
npm run build
.venv/bin/python -m pytest -q
```

| Thư mục | Vai trò |
|---|---|
| firmware/sniffer, firmware/common | Firmware thu Probe Request |
| backend/app | FastAPI, parser, API và SQLite |
| research | Collector, máy trạng thái, inspect/evaluate/sweep/diagnose |
| frontend | Dashboard React/TypeScript |
| configs | Cấu hình hiện tại và cấu hình tham khảo |
| data/runtime/synthetic-probe-demo | Dữ liệu mô phỏng được tạo khi chạy demo lần đầu |
| scripts | Cài đặt, chạy, nạp và đóng gói |

Kiểm tra phần mềm không chứng minh độ chính xác RF. Hiệu quả với thiết bị thật, phòng thật và điều kiện màn hình/WiFi cần được đo qua các phiên có nhãn độc lập.
