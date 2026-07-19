@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if exist "Data\logs\qlvb_downloader_last_run_report.html" (
  start "" "Data\logs\qlvb_downloader_last_run_report.html"
) else (
  echo Chua co bao cao lan chay gan nhat.
  echo Hay chay thu hoac chay tai van ban truoc.
  pause
)
