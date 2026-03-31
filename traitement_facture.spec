# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec — Traitement de facture
# Sédentaire.co
#
# Prérequis :
#   pip install pyinstaller customtkinter anthropic pypdf pdf2image pillow keyring
#
# Structure attendue dans le même dossier que ce .spec :
#   traitement_facture.py
#   logo_titlebar.png
#   app_icon.ico               ← converti depuis logo_titlebar.png (voir BUILD.md)
#   Coolvetica Rg.otf
#   Coolvetica Rg Lt.otf
#   Coolvetica Rg Cond.otf
#   Coolvetica Rg Cram.otf
#   Coolvetica Hv Comp.otf
#   poppler\                   ← binaires Poppler pour Windows
#       bin\
#           pdftoppm.exe
#           pdfinfo.exe
#           ...

import sys
from pathlib import Path
import customtkinter as _ctk

ROOT   = Path(SPECPATH)
CTK_DIR = Path(_ctk.__file__).parent

# ── Données à embarquer (src, dest_dans_le_bundle) ──────────────────────────
added_files = [
    # Logo
    (str(ROOT / "logo_titlebar.png"),       "."),
    # Polices Coolvetica
    (str(ROOT / "Coolvetica Rg.otf"),       "."),
    (str(ROOT / "Coolvetica Rg It.otf"),    "."),
    (str(ROOT / "Coolvetica Rg Cond.otf"),  "."),
    (str(ROOT / "Coolvetica Rg Cram.otf"),  "."),
    (str(ROOT / "Coolvetica Hv Comp.otf"),  "."),
    # Poppler (binaires Windows) — structure conda-forge : Library\bin\
    (str(ROOT / "poppler"),                 "poppler"),
    # Thèmes customtkinter (nécessaires au runtime)
    (str(CTK_DIR), "customtkinter"),
]

# ── Imports cachés que PyInstaller rate parfois ──────────────────────────────
hidden_imports = [
    "customtkinter",
    "PIL",
    "PIL._imaging",
    "PIL.Image",
    "PIL.ImageTk",
    "keyring",
    "keyring.backends",
    "keyring.backends.Windows",
    "anthropic",
    "pypdf",
    "pdf2image",
    "httpx",
    "httpcore",
    "anyio",
]

a = Analysis(
    [str(ROOT / "traitement_facture.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib", "numpy", "pandas", "scipy",
        "IPython", "notebook", "pytest",
    ],
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
    upx=True,
    console=False,               # pas de fenêtre console noire
    disable_windowed_traceback=False,
    icon=str(ROOT / "app_icon.ico"),
    version_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TraitementFactures",    # → dist/TraitementFacture/
)
