# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the FRAME AI Windows desktop build.

Only application code, the traced Next.js server bundle and the bundled
semantic model are added. The repository ``data`` directory, ``.env`` files,
provider settings, API tokens and backups are deliberately absent.
"""

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
API_ROOT = ROOT / "services" / "api"
STAGE = ROOT / "packaging" / "out"
ASSETS = ROOT / "packaging" / "assets"

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

datas = [
    (str(STAGE / "web"), "web"),
    (str(STAGE / "node"), "node"),
    (str(STAGE / "semantic"), "semantic"),
    (str(ASSETS / "frame-ai.png"), "assets"),
    (str(API_ROOT / "app" / "imaging" / "semantic"), "app/imaging/semantic"),
    (str(API_ROOT / "app" / "repositories" / "migrations"), "app/repositories/migrations"),
]

# The skyseg ONNX model (MIT) is an optional feature that is staged into
# semantic/ by packaging/build.py after SHA-256 verification; the launcher
# copies it into the per-user data directory on first run.
#
# Excluded by construction (only the explicit datas above are added):
#   data/            frame.db*, api-token, provider-settings.json,
#                    provider-master-key, onboarding.json, originals, masks,
#                    generated, generative, tmp, visual-acceptance, visual-inspect
#   .env / .env.*    local provider keys and timeouts
#   eval-data/       labelled evaluation images
#   backups/         backup_data.py output
#   dist/, .next/    previous build output
# packaging/build.py re-audits the final directory for every path above.

hiddenimports = [
    *collect_submodules("app"),
    *collect_submodules("pystray"),
    "PIL.ImageDraw",
    "clr",
    "webview",
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "multipart",
    "python_multipart",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(API_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "mypy",
        "ruff",
        "IPython",
        "matplotlib",
        "tkinter",
        "tests",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FRAME AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ASSETS / "frame-ai.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FRAME AI",
)
