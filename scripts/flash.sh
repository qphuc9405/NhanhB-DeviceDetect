#!/usr/bin/env bash
set -eo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-}"
[[ -n "$PORT" && -r "$PORT" && -w "$PORT" ]] || { echo 'Dùng: bash scripts/flash.sh /dev/ttyUSB0 (thay bằng cổng thật có quyền đọc/ghi)';exit 1; }
if ! command -v idf.py >/dev/null 2>&1; then
  IDF_EXPORT="${IDF_PATH:-$HOME/esp/esp-idf}/export.sh"
  [[ -f "$IDF_EXPORT" ]] || { echo 'Cần ESP-IDF 5.5.4. Không tìm thấy export.sh';exit 1; }
  source "$IDF_EXPORT"
fi
idf.py --version
cd "$ROOT/firmware/sniffer"
if [[ ! -f sdkconfig ]] || ! grep -q 'CONFIG_IDF_TARGET="esp32c3"' sdkconfig; then idf.py set-target esp32c3; fi
idf.py build
idf.py -p "$PORT" -b 460800 flash
echo 'Nạp xong. Mở dashboard, chọn cổng này với baud 460800. Đóng monitor trước khi kết nối.'
