# Hướng dẫn chạy WiFi Device Sherlock trong terminal của VS Code

Hướng dẫn dành cho Ubuntu/Linux, sử dụng terminal **Bash** trong VS Code. Có thể chạy demo khi chưa có ESP32-C3.

## Chạy nhanh trên máy hiện tại

Mở terminal tại thư mục dự án và chạy:

```bash
./run.sh
```

Sau đó mở địa chỉ mà script in trong terminal, thường là **http://127.0.0.1:8000**. Nhấn **Ctrl + C** để dừng.
Script dùng Python tại `.venv/bin/python` trong dự án. Nếu chưa có môi trường hoặc bản build giao diện, script tự chạy cài đặt; Python 3.12 tại `$HOME/.local/bin/python3.12` (trên máy hiện tại là `/home/phuc/.local/bin/python3.12`) được ưu tiên khi tạo môi trường. Lần cài đặt cần Internet và các công cụ ở mục 2. Không cần nhập lại đường dẫn Python mỗi lần chạy.

## 1. Mở dự án và terminal

1. Mở VS Code, chọn **File → Open Folder…**.
2. Chọn thư mục `wifi-device-sherlock` (thư mục chứa `README.md`, `backend`, `frontend`, `scripts`).
3. Chọn **Terminal → New Terminal**, hoặc nhấn **Ctrl + `**.
4. Nếu terminal chưa ở thư mục dự án, chạy:

```bash
cd "/home/phuc/Downloads/WiFi_Device_Sherlock_Source (1)/wifi-device-sherlock"
```

Đường dẫn trên là vị trí hiện tại của dự án. Nếu chuyển thư mục, thay bằng đường dẫn mới; giữ dấu ngoặc kép khi đường dẫn có khoảng trắng.

## 2. Kiểm tra công cụ cần có

Cần **Python 3.12**, **Node.js từ 22 trở lên** và **npm**. Kiểm tra:

```bash
python3.12 --version
node --version
npm --version
```

Nếu chưa có công cụ hoặc phiên bản chưa phù hợp, cài đúng phiên bản trước khi tiếp tục. Python cần hỗ trợ tạo môi trường ảo `venv`. Nếu Ubuntu báo thiếu `ensurepip`/`venv` khi cài đặt, và Python 3.12 được cài qua apt, chạy:

```bash
sudo apt install python3.12-venv
```

Nếu máy không có lệnh `python3.12` nhưng `python3 --version` trả về **3.12.x**, script cài đặt có thể tự dùng `python3`.

## 3. Cài đặt lần đầu

Tại thư mục gốc của dự án, chạy:

```bash
bash scripts/setup.sh
```

Script tạo môi trường Python `.venv`, cài thư viện Python, cài thư viện frontend và build giao diện. Cần kết nối Internet để tải các thư viện. Chờ đến khi xuất hiện thông báo **Cài đặt xong**.

Nếu Python 3.12 nằm ở đường dẫn riêng, thay đường dẫn bên dưới bằng đường dẫn thực tế:

```bash
PYTHON=/duong/dan/python3.12 bash scripts/setup.sh
```

## 4. Chạy chương trình

```bash
bash scripts/run.sh
```

Giữ terminal mở. Khi terminal hiện `Application startup complete`, truy cập địa chỉ trên dòng `Mở http://...`. Script sử dụng Python trong `.venv`.

Các lần chạy sau chỉ cần mở thư mục dự án trong VS Code rồi chạy lại `bash scripts/run.sh`. Khi sửa mã frontend, chạy `npm run build` trước khi chạy lại để cập nhật giao diện.

## 5. Thử khi chưa có ESP32-C3

1. Mở dashboard tại địa chỉ ở bước 4.
2. Bấm **Chạy demo nhanh**.
3. Quan sát trạng thái và số đếm trên giao diện. Đây là dữ liệu mô phỏng.

Demo tự dùng cấu hình nhanh và tắt lọc RSSI. Sau demo, ngắt nguồn demo và chọn lại thời gian xác nhận/bộ lọc mong muốn trước khi thu dữ liệu thật.

## 6. Chạy với ESP32-C3

Board cần được nạp firmware của dự án trước. Nếu chưa nạp, xem mục **Cắm và nạp ESP32-C3** trong [README.md](README.md).

1. Cắm board bằng cáp USB có truyền dữ liệu.
2. Trên dashboard, chọn cổng USB tương ứng, ví dụ `/dev/ttyUSB0`, rồi kết nối.
3. Chờ heartbeat hợp lệ; chọn thời gian xác nhận và bộ lọc phù hợp.
4. Nhập thông tin phòng, thiết bị và số thiết bị thật, sau đó bấm **Bắt đầu ghi**.
5. Khi thay đổi số thiết bị, nhập số mới rồi bấm **Ghi số mới**.
6. Bấm **Kết thúc & lưu**, sau đó **Xem kết quả**.

Chỉ một tiến trình được mở cổng serial. Đóng serial monitor trước khi dashboard kết nối board. Dữ liệu phiên được lưu trong `data/runtime/experiments/`.

## 7. Dừng chương trình

Quay lại terminal đang chạy chương trình và nhấn **Ctrl + C**. Chờ máy chủ dừng trước khi chạy lại.

## 8. Xử lý lỗi thường gặp

### Báo `Chạy bash scripts/setup.sh trước`

Chạy lại cài đặt, chỉ khởi động khi cài đặt thành công:

```bash
bash scripts/setup.sh
bash scripts/run.sh
```

### Cổng 8000 đang được sử dụng

Khi cổng mặc định bận, script tự chọn cổng trống và in địa chỉ mới. Để chọn cổng cụ thể, chạy:

```bash
WIFI_PORT=8001 bash scripts/run.sh
```

Sau đó mở **http://127.0.0.1:8001**. Nếu cổng đã chọn đang bận, hãy đổi `WIFI_PORT` hoặc dừng tiến trình đang dùng cổng đó.

### Không mở được trang web

Kiểm tra terminal còn chạy và dùng địa chỉ mà script in. Nếu VS Code đang kết nối máy khác qua Remote SSH/Container, cần chuyển tiếp cổng tương ứng trong tab **Ports** của VS Code.

### Không có quyền truy cập cổng USB (`Permission denied`)

Trên Ubuntu, thêm tài khoản vào nhóm serial:

```bash
sudo usermod -aG dialout "$USER"
```

Đăng xuất rồi đăng nhập lại để áp dụng, sau đó mở lại VS Code. Không chạy backend bằng `sudo`.

## 9. Chạy khi phát triển giao diện (tùy chọn)

Sau khi đã cài đặt bằng `scripts/setup.sh`, dừng phiên chạy ở bước 4 rồi chạy tại thư mục gốc:

```bash
npm run dev
```

Lệnh này khởi động backend trên cổng **8000** và Vite cho frontend trên cổng **5173**. Mở **http://127.0.0.1:5173** để xem giao diện cập nhật khi sửa mã. Nếu cổng 5173 bận, dùng địa chỉ thực tế Vite in trong terminal. Nhấn **Ctrl + C** để dừng.
