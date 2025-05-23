# -*- mode: python ; coding: utf-8 -*-

import PyInstaller.config
import os
import datetime

# 读取版本号
with open("VERSION", "r", encoding="utf-8") as f:
    version = f.read().strip()

PyInstaller.config.CONF['distpath'] = os.path.join('dist', f'build-{datetime.datetime.now().strftime("%Y%m%d")}-{version}')

a = Analysis(
    ['main.py', 'utils.py', 'gui_mainWindow.py', 'gui_previewPanel.py', 'pdf_processor.py', 'workers.py'],
    pathex=[],
    binaries=[],
    datas=[('resources/*','resources')],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PDF-CE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources/icon.png'],
)
