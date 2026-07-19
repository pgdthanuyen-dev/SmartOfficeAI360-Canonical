@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
cd /d "%ROOT%"
:title
cls
echo ============================================================
echo        SMART OFFICE AI 360 - TRINH DIEU KHIEN QLVB
echo        SmartOfficeAI360 V22.2.3-QC Maintenance 1 - QLVB Download
echo        Tag: smartofficeai360-v22.2.2-qc-hotfix3-qlvb-download
echo ============================================================
echo.
echo  1. Mo giao dien phan mem SmartOfficeAI360
echo  2. Cai dat lan dau / cap nhat moi truong
echo  3. Khai bao cau hinh tai van ban QLVB
echo  4. Kiem tra moi truong va cau hinh thong minh
echo  5. Soi cau truc trang QLVB ^(Page Probe^)
echo  6. Chay thu kho ^(quet danh sach, chua tai file^)
echo  7. Test tai 01 ho so
echo  8. Chay tai van ban that
echo  9. Chay tai nen ^(an trinh duyet^)
echo 10. Mo bao cao lan chay gan nhat
echo 11. Mo thu muc log / loi
echo 12. Mo thu muc van ban da tai
echo 13. Mo thu muc queue READY cho AI xu ly
echo 14. Xuat goi loi/gui ky thuat
echo  0. Thoat
echo.
echo Goi y lan dau: chon 2 ^> chon 3 ^> chon 4 ^> chon 7 ^> chon 8.
echo.
set /p CHON=Nhap so can chon roi nhan Enter: 
if "%CHON%"=="1" call "START_SMARTOFFICEAI360_GUI.bat"
if "%CHON%"=="2" call "tools\launchers\first_run_setup.bat"
if "%CHON%"=="3" call "tools\launchers\open_config_gui.bat"
if "%CHON%"=="4" call "tools\launchers\check_config.bat"
if "%CHON%"=="5" call "tools\launchers\page_probe.bat"
if "%CHON%"=="6" call "tools\launchers\dry_run.bat"
if "%CHON%"=="7" call "tools\launchers\test_1_item.bat"
if "%CHON%"=="8" call "tools\launchers\run_real.bat"
if "%CHON%"=="9" call "tools\launchers\run_background.bat"
if "%CHON%"=="10" call "tools\launchers\open_last_report.bat"
if "%CHON%"=="11" call "tools\launchers\open_logs.bat"
if "%CHON%"=="12" call "tools\launchers\open_data_files.bat"
if "%CHON%"=="13" call "tools\launchers\open_ready_queue.bat"
if "%CHON%"=="14" call "tools\launchers\export_support_package.bat"
if "%CHON%"=="0" goto end
goto title
:end
endlocal
