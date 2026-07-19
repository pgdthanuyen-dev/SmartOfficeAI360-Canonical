@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
echo Kiem tra moi truong va cau hinh thong minh V22.1.5...
python -m tools.qlvb_downloader.doctor --check
echo.
echo In cau hinh da chuan hoa ^(che mat khau^)...
python -m tools.qlvb_downloader.runner --print-config
pause
