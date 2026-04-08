# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['joycon_helper\\__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=[('../.ui-bundle', '.ui-bundle'), ('icon.ico', '.'), ('../docs/ui/misc/icon.png', '.')],
    hiddenimports=['serial', 'serial.tools', 'serial.tools.list_ports', 'serial.tools.list_ports_windows', 'hid', 'esptool', 'esptool.targets', 'esptool.targets.esp32', 'esptool.targets.esp32s3'],
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
    name='BindBandit',
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
    version='build\\pyinstaller-version-info.txt',
    icon='icon.ico',
)
