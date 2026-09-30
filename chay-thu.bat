@echo off
rem ======================================================================
rem  CHAY THU KMG CLUB TREN WINDOWS - chi can nhap dup vao file nay.
rem  Lan dau mat vai phut de cai thu vien. Cac lan sau chay ngay.
rem  Dung may chu: nhan Ctrl+C trong cua so nay (hoac dong cua so).
rem  Cong 8000 dang ban? Mo cmd, go:  set PORT=8001  roi chay file nay.
rem ======================================================================
chcp 65001 >nul
cd /d "%~dp0"
if not defined PORT set "PORT=8000"

echo.
echo === KMG Club - chay thu ===
echo.

rem 1. Kiem tra Python (can ban 3.10 tro len)
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [LOI] Chua cai Python. Tai tai https://www.python.org/downloads/
  echo       Khi cai nho tick "Add python.exe to PATH", xong chay lai file nay.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(sys.version_info < (3, 10))" || (
  echo [LOI] Can Python 3.10 tro len. Hay cai ban moi tai https://www.python.org/downloads/
  pause
  exit /b 1
)

rem 2. Moi truong ao rieng cho du an (khong dung cham Python cua may)
if not exist "venv\Scripts\python.exe" (
  echo [1/5] Tao moi truong ao...
  %PY% -m venv venv || (echo [LOI] Khong tao duoc moi truong ao. & pause & exit /b 1)
)
set "VPY=venv\Scripts\python.exe"

echo [2/5] Cai thu vien (lan dau mat vai phut)...
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt || (
  echo [LOI] Cai thu vien that bai. Kiem tra ket noi mang roi chay lai.
  pause
  exit /b 1
)

rem 3. File cau hinh: dung SQLite, khong can cai MySQL
if not exist ".env" (
  echo [3/5] Tao file cau hinh .env ^(SQLite^)...
  copy /y ".env.mau-de-chay-nhanh" ".env" >nul
)

echo [4/5] Tao / cap nhat co so du lieu va du lieu demo...
"%VPY%" manage.py migrate -v 0 || (echo [LOI] migrate that bai. & pause & exit /b 1)
"%VPY%" manage.py seed_demo >nul || (echo [LOI] Nap du lieu demo that bai. & pause & exit /b 1)

echo [5/5] Khoi dong may chu...
echo.
echo   Mo trinh duyet:  http://127.0.0.1:%PORT%
echo   Tai khoan demo (mat khau chung: demo1234):
echo     admin       - Admin / Ban chu nhiem
echo     truongbtc   - Truong ban to chuc
echo     btc1        - Thanh vien ban to chuc
echo     thanhvien   - Thanh vien
echo.
echo   Dung may chu: nhan Ctrl+C hoac dong cua so nay.
echo.
if not defined KHONG_MO_TRINH_DUYET start "" "http://127.0.0.1:%PORT%"
"%VPY%" manage.py runserver 127.0.0.1:%PORT%
pause
