@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
echo Chay tai van ban QLVB that - hien trinh duyet...
echo Kiem tra nhanh truoc khi chay...
python -m tools.qlvb_downloader.doctor --check
if errorlevel 2 (
  echo [DUNG] Moi truong/cau hinh chua dat. Vui long sua theo bao cao tren.
  pause
  exit /b 2
)
echo.
python -m tools.qlvb_downloader.runner --directions both --headless false --dry-run false
pause
