@echo off
chcp 65001 >nul
set "ROOT=%~dp0..\.."
cd /d "%ROOT%"
if not exist "Data\logs" mkdir "Data\logs"
start "" "Data\logs"
