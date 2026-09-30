#!/usr/bin/env bash
# ======================================================================
#  Chạy thử KMG Club trên macOS / Linux:   bash chay-thu.sh
#  Lần đầu mất vài phút để cài thư viện. Dừng máy chủ: Ctrl+C.
# ======================================================================
set -e
cd "$(dirname "$0")"
PORT="${PORT:-8000}"   # cổng 8000 bận thì chạy:  PORT=8001 bash chay-thu.sh

PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[LỖI] Chưa cài Python 3.10+. Tải tại https://www.python.org/downloads/"
  exit 1
fi
"$PY" -c "import sys; sys.exit(sys.version_info < (3, 10))" || {
  echo "[LỖI] Cần Python 3.10 trở lên."; exit 1; }

if [ ! -x venv/bin/python ]; then
  echo "[1/5] Tạo môi trường ảo..."
  "$PY" -m venv venv
fi
VPY=venv/bin/python

echo "[2/5] Cài thư viện (lần đầu mất vài phút)..."
"$VPY" -m pip install -q --disable-pip-version-check -r requirements.txt

if [ ! -f .env ]; then
  echo "[3/5] Tạo file cấu hình .env (SQLite)..."
  cp .env.mau-de-chay-nhanh .env
fi

echo "[4/5] Tạo / cập nhật cơ sở dữ liệu và dữ liệu demo..."
"$VPY" manage.py migrate -v 0
"$VPY" manage.py seed_demo >/dev/null

cat <<EOF
[5/5] Khởi động máy chủ...

  Mở trình duyệt:  http://127.0.0.1:$PORT
  Tài khoản demo (mật khẩu chung: demo1234):
    admin       - Admin / Ban chủ nhiệm
    truongbtc   - Trưởng ban tổ chức
    btc1        - Thành viên ban tổ chức
    thanhvien   - Thành viên

  Dừng máy chủ: Ctrl+C
EOF
"$VPY" manage.py runserver "127.0.0.1:$PORT"
