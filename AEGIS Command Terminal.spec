# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from scripts.release_files import public_files


if sys.platform == 'win32':
    # Freeze against the project's runtime, not unrelated tools injected into PATH.
    # Qt6Core uses Windows ICU; Poppler's icuuc.dll has incompatible exports.
    runtime_root = Path(sys.executable).resolve().parent
    windows_root = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    runtime_search_paths = [
        runtime_root,
        runtime_root / 'DLLs',
        runtime_root / 'Library' / 'bin',
        runtime_root / 'Lib' / 'site-packages' / 'PyQt6' / 'Qt6' / 'bin',
        windows_root / 'System32',
        windows_root,
    ]
    os.environ['PATH'] = os.pathsep.join(
        str(path) for path in runtime_search_paths if path.is_dir()
    )


selenium_hiddenimports = collect_submodules('selenium')
webdriver_manager_hiddenimports = collect_submodules('webdriver_manager')
project_root = Path(SPECPATH)
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
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['images\\icons\\LOGO.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AEGIS Command Terminal',
)
