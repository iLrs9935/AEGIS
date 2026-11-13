# -*- mode: python ; coding: utf-8 -*-

import os
import sys
import sysconfig
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from scripts.release_files import public_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable,
    VarFileInfo, VarStruct, VSVersionInfo,
)


if sys.platform == 'win32':
    # Freeze against the project's runtime, not unrelated tools injected into PATH.
    # Qt6Core uses Windows ICU; Poppler's icuuc.dll has incompatible exports.
    runtime_root = Path(sys.base_prefix).resolve()
    windows_root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    runtime_search_paths = [
        windows_root / 'System32',
        windows_root,
        runtime_root,
        runtime_root / 'DLLs',
        Path(sysconfig.get_path('purelib')) / 'PyQt6' / 'Qt6' / 'bin',
        runtime_root / 'Library' / 'bin',
    ]
    os.environ['PATH'] = os.pathsep.join(
        str(path) for path in runtime_search_paths if path.is_dir()
    )


selenium_hiddenimports = collect_submodules('selenium')
webdriver_manager_hiddenimports = collect_submodules('webdriver_manager')
project_root = Path(SPECPATH)
build_version = os.environ.get('AEGIS_BUILD_VERSION', '3.0.0')
version_parts = tuple(int(value) for value in build_version.split('.'))
if len(version_parts) != 3 or any(value < 0 or value > 65535 for value in version_parts):
    raise ValueError('AEGIS_BUILD_VERSION must contain three version numbers')
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=(*version_parts, 0), prodvers=(*version_parts, 0),
                      mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'iLrs9935'),
        StringStruct('FileDescription', 'AEGIS Visual Workflow Editor'),
        StringStruct('FileVersion', build_version),
        StringStruct('InternalName', 'AEGIS'),
        StringStruct('LegalCopyright', 'Copyright 2026 iLrs9935'),
        StringStruct('OriginalFilename', 'AEGIS Command Terminal.exe'),
        StringStruct('ProductName', 'AEGIS'),
        StringStruct('ProductVersion', build_version),
    ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])],
)
image_datas = [
    (str(path), str(path.parent.relative_to(project_root)))
    for path in public_files(project_root)
    if path.relative_to(project_root).parts[0] == 'images'
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(str(path), 'dlls') for path in Path('dlls').glob('*.dll')]
             if os.environ.get('AEGIS_BUNDLE_LLAMA') == '1' else [],
    datas=image_datas + [('examples/workflows', 'workflows'),
                        ('config.local.example.json', '.')],
    hiddenimports=['nodes.actions', 'nodes.ai', 'nodes.keyboard_backend', 'nodes.logic', 'nodes.memory', 'nodes.network', 'nodes.notifications', 'nodes.okww', 'nodes.system', 'nodes.text_ops', 'nodes.timers', 'nodes.triggers', 'nodes.vision', 'functions.func_actions', 'functions.func_ai', 'functions.func_crawler', 'functions.func_logic', 'functions.func_memory', 'functions.func_network', 'functions.func_okww', 'functions.func_process', 'functions.func_system', 'functions.func_text', 'functions.func_vision', 'functions.func_window', 'pythoncom', 'win32com.client'] + selenium_hiddenimports + webdriver_manager_hiddenimports,
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
    [],
    exclude_binaries=True,
    name='AEGIS Command Terminal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['images\\icons\\LOGO.ico'],
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='AEGIS Command Terminal',
)
