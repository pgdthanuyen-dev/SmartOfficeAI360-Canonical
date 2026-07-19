@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
echo ============================================================
echo SMART OFFICE AI 360 - CAI DAT LAN DAU / CAP NHAT MOI TRUONG
echo V22.1.5 FIRST RUN GUARD
echo ============================================================
echo.
echo [1/6] Kiem tra Python...
python --version
if errorlevel 1 (
  echo [LOI] Chua tim thay Python. Vui long cai Python 3.11 tro len va tick Add Python to PATH.
  pause
  exit /b 1
)
echo.
echo [2/6] Tao thu muc du lieu va cau hinh mau neu thieu...
python -m tools.qlvb_downloader.doctor --prepare
echo.
echo [3/6] Cap nhat pip...
python -m pip install --upgrade pip
echo.
echo [4/6] Cai/cap nhat thu vien Python...
python -m pip install -r requirements.txt
echo.
echo [5/6] Cai/cap nhat trinh duyet Playwright Chromium...
python -m playwright install chromium
echo.
echo [6/6] Kiem tra lai moi truong sau cai dat...
python -m tools.qlvb_downloader.doctor --check --launch-browser-check
echo.
echo [OK] Hoan thanh cai dat lan dau/cap nhat moi truong.
echo Neu muc cau hinh con canh bao, quay ve menu chon so 2 de khai bao QLVB.
pause
