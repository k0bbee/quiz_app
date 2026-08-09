# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)


project_root = Path(SPEC).resolve().parent
runtime_distributions = (
    "certifi",
    "charset-normalizer",
    "idna",
    "jaraco.classes",
    "jaraco.context",
    "jaraco.functools",
    "keyring",
    "more-itertools",
    "packaging",
    "Pillow",
    "pypdfium2",
    "PyQt6",
    "PyQt6-Qt6",
    "PyQt6-sip",
    "pytesseract",
    "pywin32-ctypes",
    "requests",
    "urllib3",
)

datas = [(str(project_root / "style.qss"), ".")]
datas += collect_data_files("pypdfium2")
for distribution in runtime_distributions:
    datas += copy_metadata(distribution)

hiddenimports = collect_submodules("keyring.backends")

analysis = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="AI课程刷题软件",
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
    contents_directory="_internal",
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AI课程刷题软件",
)
