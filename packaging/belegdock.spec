import os

VERSION = os.environ.get("BELEGDOCK_VERSION", "0.1.0.dev0")
CONSOLE_ENTRY = os.path.join(SPECPATH, "console_entry.py")
DESKTOP_ENTRY = os.path.join(SPECPATH, "desktop_entry.py")

HIDDEN_IMPORTS = [
    "belegdock",
    "belegdock.cli",
    "belegdock.desktop",
    "google_auth_oauthlib.flow",
    "google.auth.transport.requests",
    "google.oauth2.credentials",
    "googleapiclient.discovery",
    "httpx",
    "keyring.backends.SecretService",
    "keyring.backends.Windows",
    "platformdirs",
    "tkinter",
    "_tkinter",
]

console_analysis = Analysis(
    [CONSOLE_ENTRY],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
console_pyz = PYZ(console_analysis.pure)
console_exe = EXE(
    console_pyz,
    console_analysis.scripts,
    [],
    exclude_binaries=True,
    name="belegdock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

desktop_analysis = Analysis(
    [DESKTOP_ENTRY],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
desktop_pyz = PYZ(desktop_analysis.pure)
desktop_exe = EXE(
    desktop_pyz,
    desktop_analysis.scripts,
    [],
    exclude_binaries=True,
    name="BelegDock-Desktop",
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
)

bundle = COLLECT(
    console_exe,
    desktop_exe,
    console_analysis.binaries,
    console_analysis.datas,
    desktop_analysis.binaries,
    desktop_analysis.datas,
    strip=False,
    upx=False,
    name="BelegDock",
)
