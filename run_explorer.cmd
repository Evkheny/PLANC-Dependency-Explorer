@echo off
REM PLANC Dependency Explorer from source (needs Python + pymupdf). Users: run dist\PLANC_Dependency_Explorer.exe instead.
cd /d "%~dp0"
start "" pythonw planc_explorer.py
