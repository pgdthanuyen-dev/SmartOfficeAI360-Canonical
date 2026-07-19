@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
echo Soi cau truc trang QLVB - Page Probe...
echo Kiem tra nhanh truoc khi chay...
python -m tools.qlvb_downloader.doctor --check
if errorlevel 2 (
  echo [DUNG] Moi truong/cau hinh chua dat. Vui long sua theo bao cao tren.
  pause
  exit /b 2
)
echo.
python -m tools.qlvb_downloader.diagnostics --headless false
pause
