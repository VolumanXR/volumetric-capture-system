# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['C:\\Users\\Aldi\\Repos\\VolumanXR\\hardware-capture\\src\\capture\\master_controller.py'],
    pathex=['C:\\Users\\Aldi\\Repos\\VolumanXR\\hardware-capture\\src\\capture'],
    binaries=[],
    datas=[('C:\\Users\\Aldi\\Repos\\VolumanXR\\hardware-capture\\src\\utils', 'utils')],
    hiddenimports=[],
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
    name='master_controller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\Aldi\\Repos\\VolumanXR\\hardware-capture\\src\\utils\\Voluman_Icon.ico'],
)
