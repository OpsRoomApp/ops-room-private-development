# PyInstaller one-folder build for OPS ROOM on Windows x64.
from pathlib import Path
import importlib.util

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH)

hidden_imports = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("SimConnect")
    + collect_submodules("qrcode")
    + collect_submodules("reportlab")
    + collect_submodules("pystray")
    + collect_submodules("PIL")
    + ["app.raas", "app.raas_audio", "app.charts"]
)
pygame_datas, pygame_binaries, pygame_hidden = collect_all("pygame")
hidden_imports += pygame_hidden
pymupdf_datas, pymupdf_binaries, pymupdf_hidden = collect_all("pymupdf")
hidden_imports += pymupdf_hidden
simconnect_data = collect_data_files("SimConnect", includes=["SimConnect.dll"])
webview_datas, webview_binaries, webview_hidden = collect_all("webview")
hidden_imports += webview_hidden

optional_datas = []
optional_binaries = []
# pyuipc is a top-level compiled extension distributed by the Windows-only
# fsuipc package. Add it explicitly; collect_all() is intended for packages.
if importlib.util.find_spec("pyuipc") is not None:
    hidden_imports.append("pyuipc")
if importlib.util.find_spec("fsuipc") is not None:
    package_datas, package_binaries, package_hidden = collect_all("fsuipc")
    optional_datas += package_datas
    optional_binaries += package_binaries
    hidden_imports += package_hidden

if not any(Path(source).name.lower() == "simconnect.dll" for source, _ in simconnect_data):
    raise RuntimeError("PyInstaller could not locate SimConnect/SimConnect.dll. Check requirements_shipping.txt.")

a = Analysis(
    [str(root / "opsroom_launcher.py")],
    pathex=[str(root)],
    binaries=[*webview_binaries, *pygame_binaries, *pymupdf_binaries, *optional_binaries],
    datas=[
        (str(root / "app" / "static"), "app/static"),
        (str(root / "app" / "raas_audio.py"), "app"),
        (str(root / "app" / "raas.py"), "app"),
        (str(root / "app" / "data"), "app/data"),
        (str(root / "app" / "assets"), "app/assets"),
        (str(root / "version.json"), "."),
        (str(root / "README.md"), "."),
        (str(root / "RELEASE_NOTES.md"), "."),
        (str(root / "PMDG_777_SDK_EULA.txt"), "."),
        (str(root / "vpilot_plugin" / "OPSROOM.VPilotBridge.cs"), "vpilot_plugin"),
        (str(root / "vpilot_plugin" / "README.txt"), "vpilot_plugin"),
        *simconnect_data,
        *webview_datas,
        *pygame_datas,
        *pymupdf_datas,
        *optional_datas,
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OPS ROOM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "app" / "static" / "opsroom.ico"),
)
updater_a = Analysis(
    [str(root / "opsroom_updater.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=["tkinter", "tkinter.ttk"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi"],
    noarchive=False,
)
updater_pyz = PYZ(updater_a.pure)
# Updater is intentionally built as a true one-file executable.
# It is staged into AppData before replacing OPS ROOM, so it must not depend
# on the install folder's _internal/python311.dll at launch time.
updater_exe = EXE(
    updater_pyz,
    updater_a.scripts,
    updater_a.binaries,
    updater_a.datas,
    [],
    exclude_binaries=False,
    name="OPS ROOM Updater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "app" / "static" / "opsroom.ico"),
)

coll = COLLECT(
    exe,
    updater_exe,
    a.binaries,
    a.datas,
    updater_a.binaries,
    updater_a.datas,
    strip=False,
    upx=False,
    name="OPS ROOM",
)
