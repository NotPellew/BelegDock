import os

VERSION = os.environ.get("BELEGDOCK_VERSION", "0.1.0a1")
CONSOLE_ENTRY = os.path.join(SPECPATH, "console_entry.py")
DESKTOP_ENTRY = os.path.join(SPECPATH, "desktop_entry.py")
BUILD_REVISION_NAME = "build_revision.txt"
REVISION_FILE = os.environ.get("BELEGDOCK_BUILD_REVISION_FILE")
REVISION_DATAS = [(REVISION_FILE, "belegdock")] if REVISION_FILE else []
ICON = os.path.join(SPECPATH, "icon", "belegdock.ico")
WINDOW_ICON_PNG = os.path.normpath(
    os.path.join(SPECPATH, "..", "src", "belegdock", "assets", "belegdock.png")
)
WINDOW_ICON_DATAS = [(WINDOW_ICON_PNG, "belegdock/assets")]

HIDDEN_IMPORTS = [
    "belegdock",
    "belegdock.build_info",
    "belegdock.cli",
    "belegdock.desktop",
    "belegdock.desktop_setup",
    "belegdock.desktop_smoke",
    "belegdock.setup",
    "google_auth_oauthlib.flow",
    "google.auth.exceptions",
    "google.auth.transport.requests",
    "google.oauth2.credentials",
    "googleapiclient.discovery",
    "googleapiclient.errors",
    "httplib2",
    "httpx",
    "keyring.backends.SecretService",
    "keyring.backends.Windows",
    "oauthlib.oauth2.rfc6749.errors",
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
    icon=ICON,
)

desktop_analysis = Analysis(
    [DESKTOP_ENTRY],
    pathex=[],
    binaries=[],
    datas=[*REVISION_DATAS, *WINDOW_ICON_DATAS],
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
    icon=ICON,
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
