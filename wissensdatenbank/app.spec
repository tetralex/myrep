# -*- mode: python ; coding: utf-8 -*-
# PyInstaller-Konfiguration – erzeugt eine einzelne .exe.
# Name und Version kommen aus app/config.py.
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from app.config import EXE_NAME  # noqa: E402
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs  # noqa: E402

datas = [("app/assets", "app/assets")]
datas += collect_data_files("CoolProp")
datas += collect_data_files("docx")
binaries = collect_dynamic_libs("CoolProp")

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=["CoolProp.CoolProp", "docx", "pypdf", "anthropic"],
    excludes=["tkinter", "matplotlib", "numpy.tests", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=EXE_NAME,
    console=False,
    icon="app/assets/icon.ico",
    upx=False,
    disable_windowed_traceback=False,
)
