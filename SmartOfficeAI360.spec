# -*- mode: python ; coding: utf-8 -*-
import os
import sys
import customtkinter

block_cipher = None

customtkinter_path = os.path.dirname(customtkinter.__file__)
playwright_browsers = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ms-playwright')
browser_datas = [(playwright_browsers, 'ms-playwright')] if os.path.isdir(playwright_browsers) else []
example_config = os.path.join('Data', 'config', 'qlvb_downloader_config.example.json')
release_datas = browser_datas + ([(example_config, 'Data/config')] if os.path.isfile(example_config) else [])

# 1. Main GUI
a_gui = Analysis(
    ['tools/qlvb_downloader/gui_tk.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        (customtkinter_path, 'customtkinter'),
    ] + release_datas,
    hiddenimports=[
        'tools.qlvb_downloader.config',
        'tools.qlvb_downloader.paths',
        'tools.qlvb_downloader.storage',
        'tools.qlvb_downloader.sync_client',
        'tools.qlvb_downloader.doctor',
        'tools.qlvb_downloader.runner',
        'tools.qlvb_downloader.downloader',
        'tools.qlvb_downloader.logger',
        'tools.qlvb_downloader.models',
        'tools.qlvb_downloader.parser',
        'tools.qlvb_downloader.report',
        'tools.qlvb_downloader.diagnostics',
        'tools.qlvb_downloader.audit_queue',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_gui = PYZ(a_gui.pure, a_gui.zipped_data, cipher=block_cipher)
exe_gui = EXE(
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name='SmartOfficeAI360',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 2. Doctor CLI
a_doctor = Analysis(
    ['tools/qlvb_downloader/doctor.py'],
    pathex=['.'],
    binaries=[],
    datas=release_datas,
    hiddenimports=[
        'tools.qlvb_downloader.config',
        'tools.qlvb_downloader.paths',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_doctor = PYZ(a_doctor.pure, a_doctor.zipped_data, cipher=block_cipher)
exe_doctor = EXE(
    pyz_doctor,
    a_doctor.scripts,
    [],
    exclude_binaries=True,
    name='qlvb_doctor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# 3. Runner CLI
a_runner = Analysis(
    ['tools/qlvb_downloader/runner.py'],
    pathex=['.'],
    binaries=[],
    datas=release_datas,
    hiddenimports=[
        'tools.qlvb_downloader.config',
        'tools.qlvb_downloader.paths',
        'tools.qlvb_downloader.downloader',
        'tools.qlvb_downloader.storage',
        'tools.qlvb_downloader.logger',
        'tools.qlvb_downloader.models',
        'tools.qlvb_downloader.parser',
        'tools.qlvb_downloader.report',
        'tools.qlvb_downloader.diagnostics',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz_runner = PYZ(a_runner.pure, a_runner.zipped_data, cipher=block_cipher)
exe_runner = EXE(
    pyz_runner,
    a_runner.scripts,
    [],
    exclude_binaries=True,
    name='qlvb_runner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Collect all
coll = COLLECT(
    exe_gui,
    a_gui.binaries,
    a_gui.zipfiles,
    a_gui.datas,
    
    exe_doctor,
    a_doctor.binaries,
    a_doctor.zipfiles,
    a_doctor.datas,
    
    exe_runner,
    a_runner.binaries,
    a_runner.zipfiles,
    a_runner.datas,
    
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SmartOfficeAI360',
)
