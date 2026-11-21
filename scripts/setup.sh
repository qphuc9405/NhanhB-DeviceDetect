#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3.12}"
if [[ -z "${PYTHON:-}" && -x "$HOME/.local/bin/python3.12" ]]; then
  PY="$HOME/.local/bin/python3.12"
fi
if ! command -v "$PY" >/dev/null 2>&1; then PY=python3; fi
"$PY" -c 'import sys; assert sys.version_info[:2]==(3,12), "Cần Python 3.12. Chọn bằng PYTHON=/duong/dan/python3.12 bash scripts/setup.sh"'
command -v npm >/dev/null || { echo 'Cần Node.js 22 và npm'; exit 1; }
node -e 'if(Number(process.versions.node.split(".")[0])<22){console.error("Cần Node.js >=22");process.exit(1)}'
"$PY" -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm --prefix frontend ci
npm --prefix frontend run build
printf '\nCài đặt xong. Chạy: bash scripts/run.sh\n'
