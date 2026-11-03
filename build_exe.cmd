@echo off
REM Builds dist\PLANC_Dependency_Explorer.exe (single file, no Python needed on the target PC).
REM Needs Python 3.10+ and internet access for pip the first time. Run from this folder.
cd /d "%~dp0"
if not exist .buildenv\Scripts\python.exe python -m venv .buildenv
.buildenv\Scripts\python -m pip install --quiet --upgrade pip
.buildenv\Scripts\python -m pip install --quiet pyinstaller pymupdf openpyxl
.buildenv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name PLANC_Dependency_Explorer ^
  --exclude-module pymupdf4llm --exclude-module pymupdf_layout --exclude-module numpy --exclude-module PIL ^
  --exclude-module onnxruntime --exclude-module matplotlib --exclude-module pandas --add-data "tuning_kb.json;." planc_explorer.py
echo.
echo Built: %~dp0dist\PLANC_Dependency_Explorer.exe
