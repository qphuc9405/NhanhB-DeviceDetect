# Kiến trúc nhánh thiết bị

```mermaid
flowchart TD
 D["Thiết bị WiFi thử nghiệm"] -->|"Probe Request trên kênh đang nghe"| S["ESP32-C3 sniffer"]
 S -->|"Queue → JSONL qua USB"| C["Một serial collector"]
 C --> P["Parser và metadata"]
 P --> F["Lọc nguồn / RSSI / retry"]
 F --> SH["Sherlock AT / WT / DT"]
 F --> B["Đối chứng unique / timeout"]
 P --> DB["Raw JSONL + SQLite"]
 GT["Người thử nghiệm ghi nhãn"] --> DB
 SH --> UI["FastAPI + React dashboard"]
 B --> UI
 DB --> EV["Inspect / evaluate / sweep"]
 EV --> UI
```

Không có đường truyền TX/RX sensing. Board không tạo AP và không liên kết AP.
Sniffer chỉ theo dõi một kênh tại mỗi thời điểm; hopping tạo các khoảng không
quan sát các kênh khác. Kết quả là thống kê quan sát và suy luận thời gian.

Ba thuật toán dùng cùng một chuỗi quan sát đã lọc. Thiếu heartbeat -> result=null,
không biểu diễn như count0. Dashboard polling mỗi giây không quyết định thời gian
thu serial; offline chạy theo đồng hồ file để có đánh giá tái lập được.
