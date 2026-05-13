# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — Traitement de factures (macOS)
# Sédentaire.co
#
# Prérequis :
#   brew install poppler
#   pip3 install pyinstaller customtkinter anthropic pypdf pdf2image pillow keyring httpx
#
# Structure attendue dans le même dossier que ce .spec :
#   traitement_facture.py
#   logo_titlebar.png
#   app_icon.icns              ← format icône Mac (voir BUILD.md)
#   Coolvetica Rg.otf
#   Coolvetica Rg It.otf
#   Coolvetica Rg Cond.otf
#   Coolvetica Rg Cram.otf
#   Coolvetica Hv Comp.otf
#   poppler/                   ← binaires Poppler (copie depuis Homebrew, voir BUILD.md)
#       bin/
#           pdftoppm
#           pdfinfo
#           ...

import re
import sys
from pathlib import Path
import customtkinter as _ctk

ROOT    = Path(SPECPATH)
CTK_DIR = Path(_ctk.__file__).parent

# Lire APP_VERSION depuis le .py (seule source de vérité)
_PY_SRC = (ROOT / "traitement_facture.py").read_text(encoding="utf-8")
_v = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', _PY_SRC, re.M)
APP_VERSION = _v.group(1) if _v else "0.0"

# ── Données à embarquer ──────────────────────────────────────────────────────
added_files = [
    (str(ROOT / "logo_titlebar.png"),       "."),
    (str(ROOT / "Coolvetica Rg.otf"),       "."),
    (str(ROOT / "Coolvetica Rg It.otf"),    "."),
    (str(ROOT / "Coolvetica Rg Cond.otf"),  "."),
    (str(ROOT / "Coolvetica Rg Cram.otf"),  "."),
    (str(ROOT / "Coolvetica Hv Comp.otf"),  "."),
    (str(CTK_DIR),                          "customtkinter"),
]

# Poppler — embarquer les binaires depuis Homebrew
import subprocess as _sp
_brew_prefix = _sp.check_output(["brew", "--prefix"]).decode().strip()
_poppler_bins = []
for _bin_name in ["pdftoppm", "pdfinfo"]:
    _bin_path = Path(_brew_prefix) / "bin" / _bin_name
    if _bin_path.exists():
        _poppler_bins.append((str(_bin_path), "poppler/bin"))

hidden_imports = [
    "customtkinter",
    "PIL", "PIL._imaging", "PIL.Image", "PIL.ImageTk",
    "keyring", "keyring.backends", "keyring.backends.macOS",
    "anthropic", "pypdf", "pdf2image",
    "httpx", "httpcore", "anyio",
]

a = Analysis(
    [str(ROOT / "traitement_facture.py")],
    pathex=[str(ROOT)],
    binaries=_poppler_bins,
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "scipy", "IPython", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TraitementFactures",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX non recommandé sur Mac (signature de code)
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "app_icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TraitementFactures",
)

# ── Bundle .app ──────────────────────────────────────────────────────────────
app = BUNDLE(
    coll,
    name="Traitement de factures.app",
    icon=str(ROOT / "app_icon.icns"),
    bundle_identifier="co.sedentaire.traitementfactures",
    info_plist={
        "CFBundleName":               "Traitement de factures",
        "CFBundleDisplayName":        "Traitement de factures",
        "CFBundleVersion":            APP_VERSION + ".0",
        "CFBundleShortVersionString": APP_VERSION,
        "CFBundleIdentifier":         "co.sedentaire.traitementfactures",
        "NSHighResolutionCapable":    True,
        "NSHumanReadableCopyright":   "© 2026 Sédentaire.co",
        "LSMinimumSystemVersion":     "11.0",   # macOS Big Sur minimum
        "NSRequiresAquaSystemAppearance": False, # Support mode sombre
    },
)
