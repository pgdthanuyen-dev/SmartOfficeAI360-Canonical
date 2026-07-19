@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
echo Xuat goi loi/gui ky thuat...
python -m tools.qlvb_downloader.doctor --support-package
echo.
if exist "Data\support_packages" start "" "Data\support_packages"
pause
