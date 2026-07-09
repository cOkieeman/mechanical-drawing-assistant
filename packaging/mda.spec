# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).parent


def data_tree(root, prefix):
    root = Path(root)
    items = []
    if not root.exists():
        return items
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        target_dir = Path(prefix) / path.relative_to(root).parent
        items.append((str(path), str(target_dir)))
    return items


datas = data_tree(PROJECT_ROOT / "knowledge", "knowledge")
datas += data_tree(PROJECT_ROOT / "samples", "samples")

hiddenimports = [
    "pythoncom",
    "pywintypes",
    "win32com",
    "win32com.client",
    "win32timezone",
]

a = Analysis(
    [str(PROJECT_ROOT / "src" / "mechanical_drawing_assistant" / "__main__.py")],
    pathex=[str(PROJECT_ROOT / "src")],
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
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mda",
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="mda",
)
