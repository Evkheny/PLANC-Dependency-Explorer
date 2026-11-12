# PyInstaller spec (onefile, windowed). Build: python -m PyInstaller --noconfirm --clean PLANC_Dependency_Explorer.spec
# Recent PyMuPDF wheels also ship the layout ONNX models (pymupdf/layout) and the MuPDF C++ dev files
# (pymupdf/mupdf-devel): plain `import pymupdf` needs neither, so they are filtered out (exe ~37 MB instead of ~75 MB).
EXCLUDE_MODULES = ['pymupdf4llm', 'pymupdf_layout', 'numpy', 'PIL', 'onnxruntime', 'matplotlib', 'pandas']
DROP = ('pymupdf\\layout', 'pymupdf/layout', 'mupdf-devel', '.onnx')

a = Analysis(['planc_explorer.py'], pathex=[], binaries=[], datas=[('tuning_kb.json', '.')], hiddenimports=[],
             hookspath=[], runtime_hooks=[], excludes=EXCLUDE_MODULES, noarchive=False)
a.datas = [d for d in a.datas if not any(x in d[0] for x in DROP)]
a.binaries = [b for b in a.binaries if not any(x in b[0] for x in DROP)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PLANC_Dependency_Explorer', debug=False, strip=False,
          upx=False, runtime_tmpdir=None, console=False)
