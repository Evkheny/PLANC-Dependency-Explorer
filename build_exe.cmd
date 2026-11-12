@echo off
REM Builds dist\PLANC_Dependency_Explorer.exe (single file, no Python needed on the target PC).
REM Needs Python 3.10+ and internet access for pip the first time. Run from this folder.
cd /d "%~dp0"
if not exist .buildenv\Scripts\python.exe python -m venv .buildenv
.buildenv\Scripts\python -m pip install --quiet --upgrade pip
.buildenv\Scripts\python -m pip install --quiet pyinstaller pymupdf openpyxl
.buildenv\Scripts\python -m PyInstaller --noconfirm --clean PLANC_Dependency_Explorer.spec
echo.
echo Built: %~dp0dist\PLANC_Dependency_Explorer.exe
