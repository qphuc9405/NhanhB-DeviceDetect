# Đặc tả định dạng dữ liệu – Đề tài Wi‑Fi Sensing (Nhóm 8)

**Phiên bản:** v0.1 (bản nháp, cần Tiên và Phúc góp ý trước khi chốt)
**Người soạn:** Chiến

---

## 0. File này để làm gì?

Ba người làm ba phần khác nhau, nhưng dữ liệu phải chạy xuyên qua cả ba:

- **Tiên** viết firmware #1, #2 → #2 gửi dữ liệu CSI lên laptop → Tiên tiền xử lý, trích đặc trưng.
- **Phúc** viết firmware #3 → #3 gửi dữ liệu Probe Request lên laptop → Phúc chạy máy trạng thái Sherlock.
- **Chiến** đọc dữ liệu từ cả hai board, ghi thành file theo từng buổi thu, train mô hình và làm dashboard.

File này chốt **dữ liệu trông như thế nào ở mỗi chỗ giao nhau**: ESP32 in ra dòng gì, laptop lưu file gì, cột nào tên gì. Ai cũng làm theo file này thì khi ghép lại sẽ khớp, không phải sửa code của nhau.

> Nguyên tắc: muốn đổi định dạng thì sửa file này trước, báo cả nhóm, tăng số phiên bản, rồi mới sửa code.

---

## 1. Đường đi của dữ liệu

```
 ESP32-C3 #2 (RX, thu CSI) ──USB──┐
                                  ├──► logger.py (laptop) ──► data/raw/<buổi thu>/
 ESP32-C3 #3 (sniffer)     ──USB──┘          ▲                 csi.csv, probe.csv, stat.csv
                                             │                 labels.csv, meta.json
                                  phím ghi nhãn (labels)
                                                                      │
                     ┌────────────────────────────────────────────────┤
                     ▼                                                ▼
        Tiên: tiền xử lý + đặc trưng                    Phúc: máy trạng thái Sherlock
        → data/features/<buổi thu>.csv                  → data/device/<buổi thu>.csv
                     │                                                │
                     └──────────────► Chiến: train mô hình, dashboard ◄┘
```

ESP32-C3 #1 (TX/SoftAP) **không gửi dữ liệu lên laptop**. Nó chỉ cần in dòng `BOOT` (mục 3.1) để nhóm biết MAC của nó.

---

## 2. Quy ước chung cho dữ liệu ESP32 gửi lên laptop

| Quy ước | Giá trị | Vì sao |
|---|---|---|
| Cổng | USB Serial/JTAG có sẵn trên ESP32-C3 | Nhanh hơn UART 115200, không cần mạch chuyển USB |
| Dạng dữ liệu | **Văn bản**, mỗi bản ghi một dòng, kết thúc bằng `\n` | Mở serial monitor là đọc được, dễ gỡ lỗi |
| Phân cách | Dấu phẩy `,`, không có dấu cách | Đọc bằng `line.split(",")` |
| Từ khoá đầu dòng | `BOOT`, `CSI`, `PRB`, `STAT` | Laptop biết dòng thuộc loại nào |
| Dòng khác | Laptop **bỏ qua** | Log `ESP_LOGI` để gỡ lỗi vẫn in thoải mái |
| Thời gian trên ESP | `t_us` = `esp_timer_get_time()`, micro giây tính từ lúc bật board | Có sẵn, đủ chính xác |
| Thời gian trên laptop | `host_time` = `time.time()`, giây (số thực, Unix time) | Dùng để ghép dữ liệu của #2, #3 và nhãn |
| Định dạng MAC | `aa:bb:cc:dd:ee:ff`, chữ thường | Thống nhất để so sánh |

**Về tốc độ:** một dòng `CSI` dài khoảng 330 ký tự. Ở 100 dòng/giây là khoảng 33 KB/giây. USB Serial/JTAG dự kiến đáp ứng được, nhưng **phải kiểm tra ở buổi kiểm thử tuần đầu** (xem số `n_queue_drop` trong dòng `STAT`). Nếu không kịp, phiên bản sau sẽ chuyển sang dạng nhị phân.

---

## 3. Các loại dòng ESP32 gửi lên

### 3.1. `BOOT` – mọi board (#1, #2, #3)

In **khi khởi động** và **lặp lại mỗi 30 giây**, để logger bật sau vẫn nhận được.

```
BOOT,<board>,<fw>,<mac_sta>,<mac_ap>,<channel>
```

| Trường | Ý nghĩa | Ví dụ |
|---|---|---|
| `board` | `TX` (#1), `RX` (#2) hoặc `SNF` (#3) | `RX` |
| `fw` | Phiên bản firmware | `0.1` |
| `mac_sta` | MAC giao diện STA của board | `64:e8:33:01:02:03` |
| `mac_ap` | MAC giao diện SoftAP (với #2: BSSID của AP đang kết nối; không có thì `-`) | `64:e8:33:0a:0b:0d` |
| `channel` | Kênh hiện tại | `6` |

Ví dụ:
```
BOOT,TX,0.1,64:e8:33:0a:0b:0c,64:e8:33:0a:0b:0d,6
BOOT,RX,0.1,64:e8:33:01:02:03,64:e8:33:0a:0b:0d,6
BOOT,SNF,0.1,64:e8:33:05:06:07,-,1
```

Dùng để: biết MAC của #1 (lọc CSI), và lập **danh sách MAC loại trừ** cho nhánh thiết bị.

### 3.2. `CSI` – ESP32-C3 #2 (Tiên phụ trách)

Mỗi khung nhận được từ #1 sinh ra một dòng.

```
CSI,<seq>,<t_us>,<src_mac>,<rssi>,<noise_floor>,<channel>,<sig_mode>,<cwb>,<first_word_invalid>,<len>,<csi_hex>
```

| Trường | Lấy từ (`wifi_csi_info_t`) | Ý nghĩa |
|---|---|---|
| `seq` | bộ đếm trên ESP | Tăng 1 sau mỗi dòng `CSI` gửi đi. Laptop dựa vào đây để biết có mất dòng hay không |
| `t_us` | `esp_timer_get_time()` | Thời điểm nhận khung, micro giây |
| `src_mac` | `mac` | MAC nguồn của khung |
| `rssi` | `rx_ctrl.rssi` | dBm |
| `noise_floor` | `rx_ctrl.noise_floor` | dBm |
| `channel` | `rx_ctrl.channel` | Kênh nhận |
| `sig_mode` | `rx_ctrl.sig_mode` | 0: non-HT (11b/g), 1: HT (11n) |
| `cwb` | `rx_ctrl.cwb` | 0: 20 MHz, 1: 40 MHz |
| `first_word_invalid` | `first_word_invalid` | 1 nếu 4 byte đầu của CSI không hợp lệ (giới hạn phần cứng C3) |
| `len` | `len` | Số byte CSI |
| `csi_hex` | `buf` | `len` byte CSI viết dưới dạng hex liền nhau (2 ký tự mỗi byte) |

**Cấu hình CSI thống nhất** (`wifi_csi_config_t`):

| Trường | Giá trị | Ghi chú |
|---|---|---|
| `lltf_en` | `true` | Chỉ lấy phần LLTF (64 sóng mang con) |
| `htltf_en` | `false` | |
| `stbc_htltf2_en` | `false` | |
| `ltf_merge_en` | `false` | |
| `channel_filter_en` | `false` | Giữ các sóng mang con độc lập, không làm mượt |
| `manu_scale` | `false` | Tự động co giãn |

Với cấu hình này, **`len` dự kiến là 128 byte** (64 sóng mang con × 2 byte). Cần kiểm tra lại ở tuần đầu.

**Cách đọc `csi_hex`:** mỗi sóng mang con chiếm 2 byte có dấu (`int8`): **byte đầu là phần ảo, byte sau là phần thực** (theo tài liệu ESP-IDF). Biên độ = √(thực² + ảo²).

**Lọc trên ESP:** chỉ gửi dòng khi `src_mac` trùng BSSID của AP đang kết nối (đọc bằng `esp_wifi_sta_get_ap_info()` sau khi kết nối, **không ghi cứng MAC vào code**).

Ví dụ (rút gọn phần hex):
```
CSI,1532,48211934,64:e8:33:0a:0b:0d,-42,-95,6,1,0,1,128,0000000003fa05f8...
```

### 3.3. `PRB` – ESP32-C3 #3 (Phúc phụ trách)

Mỗi Probe Request bắt được sinh ra một dòng.

```
PRB,<seq>,<t_us>,<src_mac>,<rssi>,<channel>
```

| Trường | Ý nghĩa |
|---|---|
| `seq` | Bộ đếm trên ESP, tăng 1 sau mỗi dòng `PRB` |
| `t_us` | Thời điểm nhận, micro giây |
| `src_mac` | MAC nguồn (Address 2, byte 10–15 của header) |
| `rssi` | `rx_ctrl.rssi`, dBm (chỉ ghi log, không dùng để quyết định) |
| `channel` | Kênh sniffer đang nghe khi bắt được khung |

**Lọc trên ESP:** chỉ lấy khung quản lý có subtype 4 (byte đầu của frame control là `0x40`).

MAC được gửi nguyên dạng qua USB. **Laptop băm MAC trước khi ghi xuống đĩa** (mục 4.3), nên MAC thật không bao giờ được lưu.

Ví dụ:
```
PRB,88,61230011,9a:31:87:22:fd:08,-67,6
```

### 3.4. `STAT` – ESP32-C3 #2 và #3, mỗi giây một dòng

```
STAT,<t_us>,<board>,<n_rx>,<n_filtered>,<n_queue_drop>,<channel>
```

| Trường | Với #2 (`RX`) | Với #3 (`SNF`) |
|---|---|---|
| `n_rx` | Số dòng `CSI` đã gửi trong giây vừa qua | Số dòng `PRB` đã gửi |
| `n_filtered` | Số khung bị bỏ vì sai MAC | Số khung quản lý không phải Probe Request |
| `n_queue_drop` | Số bản ghi mất vì queue đầy | Như bên trái |
| `channel` | Kênh hiện tại | Kênh đang nghe |

Dùng cho buổi kiểm thử tuần đầu (tốc độ CSI thực tế) và đèn báo "hệ thống khoẻ" trên dashboard.

---

## 4. File của mỗi buổi thu (logger trên laptop ghi ra)

### 4.1. Thư mục

```
data/raw/<session_id>/
    meta.json      thông tin buổi thu
    csi.csv        các dòng CSI
    probe.csv      các dòng PRB (MAC đã băm)
    stat.csv       các dòng STAT
    boot.csv       các dòng BOOT
    labels.csv     nhãn ghi bằng phím
```

`session_id` có dạng `YYYYMMDD_HHMM_<tên-ngắn>`, ví dụ `20261112_1430_phongA`.

### 4.2. `csi.csv`, `stat.csv`, `boot.csv`

Giữ nguyên các trường như mục 3, **thêm cột `host_time` ở đầu**. Dòng tiêu đề là tên các trường.

```
host_time,seq,t_us,src_mac,rssi,noise_floor,channel,sig_mode,cwb,first_word_invalid,len,csi_hex
1762932600.1234,1532,48211934,64:e8:33:0a:0b:0d,-42,-95,6,1,0,1,128,0000000003fa05f8...
```

### 4.3. `probe.csv`

```
host_time,seq,t_us,mac_hash,local_admin,rssi,channel,excluded
```

| Cột | Ý nghĩa |
|---|---|
| `mac_hash` | 12 ký tự hex đầu của SHA-256(`salt` + MAC). Cùng một MAC luôn cho cùng `mac_hash` |
| `local_admin` | Bit U/L của MAC: 1 = địa chỉ quản lý cục bộ (thường là MAC ngẫu nhiên) |
| `excluded` | 1 nếu MAC nằm trong danh sách loại trừ (board của nhóm, laptop demo). Máy trạng thái bỏ qua các dòng này |

`salt` để trong file cấu hình cục bộ, **không đưa lên Git và không ghi vào thư mục dữ liệu**.

### 4.4. `labels.csv` – nhãn ghi bằng phím

```
host_time,event,value
```

| `event` | `value` | Phím | Ý nghĩa |
|---|---|---|---|
| `STATE` | `EMPTY` | `E` | Phòng trống |
| `STATE` | `WALK` | `W` | Có người đi lại |
| `STATE` | `STATIC` | `S` | Có người ngồi / đứng yên |
| `STATE` | `MULTI` | `M` | Có 2–3 người trong phòng |
| `STATE` | `NEIGHBOR` | `N` | Phòng trống, có người đi lại ở phòng bên |
| `STATE` | `PAUSE` | `P` | Đang sắp xếp, không dùng đoạn này |
| `COUNT` | `+1` / `-1` | `+` / `-` | Có người vào / ra (số đếm thủ công cho nhánh thiết bị) |
| `NOTE` | chữ tự do | `T` | Ghi chú |

Một nhãn `STATE` có hiệu lực **từ thời điểm bấm đến lần bấm `STATE` tiếp theo**.

**Quy đổi sang nhãn nhị phân** cho mô hình:

| Nhãn chi tiết | Nhãn nhị phân |
|---|---|
| `WALK`, `STATIC`, `MULTI` | 1 – Occupied |
| `EMPTY`, `NEIGHBOR` | 0 – Empty |
| `PAUSE` | bỏ |

### 4.5. `meta.json`

```json
{
  "session_id": "20261112_1430_phongA",
  "room": "Phòng A, tầng 2",
  "tx_rx_distance_m": 3.0,
  "channel": 6,
  "members": ["Chiến", "Tiên", "Phúc"],
  "simulated": false,
  "ports": {"RX": "/dev/ttyACM0", "SNF": "/dev/ttyACM1"},
  "notes": "",
  "fw": {"RX": "0.1", "SNF": "0.1"},
  "spec_version": "0.1",
  "stats": {
    "duration_s": 1800.2,
    "lines": {"BOOT": 120, "CSI": 179870, "PRB": 2301, "STAT": 3600},
    "lost_by_seq": {"RX/CSI": 12},
    "bad_lines": 0,
    "label_events": 9
  }
}
```

- `fw` lấy từ các dòng `BOOT` nhận được (#1 không nối USB nên thường không có).
- `stats` chỉ có khi logger kết thúc bình thường. Thiếu `stats` nghĩa là buổi thu bị ngắt giữa chừng; dữ liệu đã ghi vẫn dùng được.
- `simulated: true` là dữ liệu giả, **không dùng để train**.

---

## 5. File đặc trưng (Tiên → Chiến)

```
data/features/<session_id>.csv
data/features/feature_meta.json
```

Mỗi dòng là **một window**:

| Cột | Ý nghĩa |
|---|---|
| `session_id` | Mã buổi thu (dùng để chia train/test theo buổi) |
| `win_start`, `win_end` | `host_time` đầu và cuối window |
| `n_samples` | Số mẫu CSI trong window |
| `valid` | 1 nếu `n_samples` ≥ 70% số mẫu dự kiến |
| `label_detail` | `EMPTY`, `WALK`, `STATIC`, `MULTI`, `NEIGHBOR` |
| `label` | 0 hoặc 1 (theo bảng quy đổi ở mục 4.4) |
| `rssi_var`, `rssi_mad`, `rssi_range`, `rssi_iqr` | 4 đặc trưng của RSSI |
| `csi_var_k`, `csi_mad_k`, `csi_range_k`, `csi_iqr_k` | 4 đặc trưng của sóng mang con thứ `k`. `k` là **chỉ số gốc 0–63**, viết 2 chữ số (`csi_var_07`), để tên cột không đổi khi danh sách sóng mang con giữ lại thay đổi |

Quy tắc:
- Window **cắt ngang chỗ đổi nhãn** thì bỏ, vì không biết gán nhãn nào.
- Window nằm trong đoạn `PAUSE` thì bỏ.
- Window có `valid = 0` vẫn ghi ra file (để thống kê), mô hình sẽ lọc bỏ.

`feature_meta.json` ghi lại cách tạo đặc trưng, để biết hai file có so sánh được với nhau không:
```json
{
  "spec_version": "0.1",
  "window_s": 6,
  "expected_rate_hz": 100,
  "valid_ratio": 0.7,
  "subcarriers_kept": [6, 7, 8],
  "denoise": {"wavelet": "db4", "level": 9},
  "code_version": "git commit"
}
```
(`subcarriers_kept` ở trên chỉ là ví dụ; danh sách thật được chốt sau khi xem dữ liệu C3.)

**Code tiền xử lý viết thành hàm trong một module dùng chung** (ví dụ `features.py`), không chỉ trong notebook. Dashboard sẽ gọi lại đúng các hàm này khi chạy thời gian thực.

---

## 6. File đầu ra nhánh thiết bị (Phúc → Chiến)

```
data/device/<session_id>.csv
```

Mỗi dòng là **một khe 1 phút**:

| Cột | Ý nghĩa |
|---|---|
| `session_id` | Mã buổi thu |
| `slot_start` | `host_time` đầu khe |
| `n_sources_seen` | Số `mac_hash` khác nhau thấy trong khe (đã bỏ `excluded = 1`) |
| `n_confirmed` | Số nguồn đang ở trạng thái "Xác nhận đến" hoặc "Có thể đã đi" |
| `device_present` | 1 nếu `n_confirmed` ≥ 1 |
| `people_manual` | Số người đếm thủ công, tính từ các sự kiện `COUNT` trong `labels.csv` (dùng để tính PCC, MRE) |

---

## 7. Thông số mặc định

| Thông số | Giá trị |
|---|---|
| Tốc độ ping của #2 | 100 lần/giây |
| Window | 6 giây, không chồng lấn |
| Window hợp lệ | ≥ 70% số mẫu dự kiến (≥ 420 mẫu) |
| Sniffer #3 | Kênh 1→13, 3 giây mỗi kênh |
| Khe Sherlock | 60 giây |
| Ngưỡng Sherlock | AT = DT = 6, WT = 2 |
| Chu kỳ dòng `STAT` | 1 giây |
| Chu kỳ lặp dòng `BOOT` | 30 giây |

---

## 8. Việc cần chốt và ai làm

**Cần cả nhóm xác nhận:**
- [ ] Đồng ý dùng dạng văn bản cho bản v0.1 (chuyển sang nhị phân nếu buổi kiểm thử cho thấy không kịp).
- [ ] Đồng ý tên và thứ tự các trường ở mục 3.
- [ ] Đồng ý bộ phím ghi nhãn ở mục 4.4.

**Tiên:** firmware #1 in `BOOT`; firmware #2 in `BOOT`, `CSI`, `STAT` đúng mục 3; kiểm tra `len` thực tế; viết `features.py` xuất file đúng mục 5.

**Phúc:** firmware #3 in `BOOT`, `PRB`, `STAT` đúng mục 3; máy trạng thái đọc `probe.csv` và xuất file đúng mục 6.

**Chiến:** viết `logger.py` (đọc hai cổng USB, gắn `host_time`, băm MAC, đánh dấu `excluded`, ghi nhãn bằng phím, ghi file đúng mục 4); viết script kiểm tra tốc độ từ `stat.csv` cho buổi kiểm thử tuần đầu.

---

## Lịch sử thay đổi

| Phiên bản | Ngày | Người sửa | Nội dung |
|---|---|---|---|
| 0.1 | 09/11/2026 | Chiến | Bản nháp đầu tiên; bổ sung các trường `simulated`, `ports`, `stats` của `meta.json` theo `laptop/logger.py` |
