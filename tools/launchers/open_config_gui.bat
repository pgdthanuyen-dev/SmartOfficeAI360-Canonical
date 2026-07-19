@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
echo Mo giao dien phan mem SmartOfficeAI360 V22.2.3-QC Maintenance 1...
python -m tools.qlvb_downloader.gui_tk
pause
