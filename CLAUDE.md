# CLAUDE.md: PLANC Dependency Explorer

## What it is
A Windows desktop tool (Python + Tkinter, shipped as one `.exe` built with PyInstaller). For the PLANC wind-turbine
controller (Siemens Gamesa / Siemens Energy, Simulink) it shows, for every controller function:
- who produces its input TDI signals and who consumes its outputs;
- its parameters, with STC1 Par number, owner, type selection and value per type value;
- the matching Controller Description section.

Its main use is comparing two type values (e.g. two WTGType variants such as the 165 and the 170 rotor) to see which
functions and parameters change.

**Read `HISTORY.md` before changing anything.** It holds the decisions, the reference numbers and the pitfalls.

## Hard rules
- **Only three inputs**, all of the same PLANC release. This was the user's decision on 02-Nov-2026; do not add others
  (no Tuning Procedure, no manual maps, no project/planning files, no tuning-order output):
  1. the PLANC repo `Controller` folder;
  2. the Controller Description PDF;
  3. the CoPaD parameter-value export `parVal<version>.csv`.
- **The PLANC repo is READ ONLY.** Never write to it and never run git commands in it.
- **Never commit company data:** no PDFs, CSV exports, model JSON, Controller Description text, screenshots, or the
  `legacy/` folder. `.gitignore` covers these; check `git status` before every commit.
- **The `.exe` is not committed.** It is attached to GitHub releases.
- **Language:** reply to the user (Eugenio) in Spanish (castellano). The UI, code, comments and README stay in English.
- **Publishing:** ask before pushing, publishing or creating releases. The GitHub repo is the user's personal one.

## Files
| File | Role |
|---|---|
| `planc_model.py` | Scanner. `build(ctrl, cd, copad, progress)` returns the model dict. It can also run as a CLI (`python planc_model.py <Controller> --cd <pdf> --csv <csv> --out model.json`). |
| `planc_explorer.py` | Tkinter UI, the `Explorer` class. `--build` does a headless rebuild from the saved config and writes `build.log`. Holds `__version__`. |
| `build_exe.cmd` | Creates a `.buildenv` venv, pip-installs pyinstaller + pymupdf, builds `dist\PLANC_Dependency_Explorer.exe` (onefile, windowed). |
| `run_explorer.cmd` | Runs from source with `pythonw`. |
| `tests/ui_smoke.py` | Drives the UI and saves 3 screenshots (needs pillow and an existing model). |
| `requirements.txt` | pymupdf (runtime), pyinstaller (build), pillow (test). |
| `legacy/` | Local only, git-ignored: the first, project-specific version. Not used. |

User data: `%APPDATA%\PLANC_Dependency_Explorer\`, which holds `config.json` (paths and compare choice), `planc_model.json`
(cache) and `build.log`.

## How the model is built (`planc_model.build`)

**1. `scan_shared`.** Reads `Shared/Parameters.xml`, `MultiParameters.xml` (layers),
`Signals.xml` (TDI name, unit, description) and `TypeSelections.xml`.
- The STC1 mapping is `Mapping[@interface=STC1]/@name`.

**2. `find_components`.** A component is `Subareas/<Subarea>/.../<Name>/<Name>.slx` with a sibling `<Name>.xml` whose root
is `<SubComponent>` (`Info/@shortName`, `Info/Description`). Paths containing `\Test\` are skipped.
- `kind` is `function`, `harness` or `stc1`:
  - `harness` = a test helper: `<X>_Helper` where `X` is a real component, or a name in the `HARNESS` set;
  - `stc1` = any other `Helper` component, which emulates a function still in legacy STC1 C++.

**3. `scan_slx`.** Opens the `.slx` zip.
- `simulink/systems/system_root.xml` root Inport/Outport names are the TDI signal names.
- Every identifier in `simulink/systems/*` and `simulink/stateflow/*` is collected as a token.

**4. Libraries.** The tokens of every other `.slx` are added: those in the component folder, plus those referenced by
name, transitively (`expand_with_libraries`).
- Many parameters only appear in `*_Library.slx`.

**5. `match_params`.** Exact parameter names, plus templates with an `X` segment: `ACS_LoadEstX_Coef2` matches
`ACS_LoadEst1_Coef2`, and so on.
- Multi-parameter layers are named `<Multi>_<Layer>`.

**6. Type selections used in the logic.** These are the tokens `T_<type>`.

**7. Edges.** Producer → consumer for each signal.
- A harness only counts as producer if nothing else produces the signal.
- Harness consumers are ignored.

**8. `load_copad`.** Reads the csv: `;`-separated, utf-8-sig, read with `DictReader`. Columns used:
- parameterDefinitionName, parameterMappingName, typeName, typeValue, value, minValue, maxValue, matriceValue, owner.
- Each parameter has exactly ONE typeName; `''` means untyped, and its value is stored under `values['']`.
- Matrix values are shown as `matrix#<first 8 chars of the CoPaD hash>`.

**9. `load_cd`.** Uses PyMuPDF.
- Sections are the level-2 PDF bookmarks (`get_toc()`, title `"9.4 Blade Load Limiter"`); level 1 = chapter.
- Section text runs from its start page to the next section's start page.
- The intro is the text between `<num>.1 Introduction` and `<num>.2` (whitespace collapsed, footer removed).
- `types` are the `|Type|` marks.
- `tokens` are used to locate parameters.

**10. `cd_section_for`.** Matches by normalised title: exact match with the name or short name, otherwise the best
Jaccard word overlap ≥ 0.6. CamelCase is split and the `_Helper` suffix ignored.

**11. `outside_model_params`.** CoPaD parameters with a type selection that the model does not use (legacy STC1
functions), located by the CD sections whose tokens contain them.
- The UI lists them (purple) under the `stc1` component, or any component without parameters, that shares the section.

**12. `meta.type_values`.** The list of type values per type selection, taken from CoPaD; it feeds the A/B comboboxes.

Model JSON keys: meta, components, signals, parameters, typeselections, edges, outside_model_params, cd.

## UI (`Explorer`)
- **Left:** a search box (function, short name, signal, parameter, or an exact STC1 Par) and a tree grouped by subarea.
  - Columns: Typed (parameters depending on the compared type selection) and A≠B (parameters that differ).
  - Filters: test helpers, only type-dependent, only where A ≠ B.
- **Centre:** a Canvas with the selected node in the middle.
  - Producers on the left with blue arrows, consumers on the right with green arrows.
  - Labels are truncated to the free gap; hover shows all signals.
  - Orange border = parameters differ between A and B. Dashed = STC1 emulation.
  - Back/Forward history.
- **Right tabs:**
  - Parameters: sorted with differences first. Double-click opens a popup with all values per type value, A and B marked.
  - Signals: double-click jumps to the peer.
  - Type selections.
  - Description: model data plus CD section, chapter, page and intro.
- **Top right:** compare type selection, value A, value B. These are saved in config.
- **Threading:** the build runs in a thread, and status updates go through `self.after`.
- **DPI:** the process is made DPI-aware (`SetProcessDpiAwareness(1)`).

## Build, test, release
- **Run from source:** `pip install pymupdf`, then `python planc_explorer.py`.
- **Exe:** run `build_exe.cmd`. pymupdf 2.x pulls numpy, onnxruntime, pymupdf4llm and pymupdf_layout; they are excluded
  in PyInstaller because `import pymupdf` does not need them. The result is about 32 MB.
- **Verify after changes:**
  1. Headless build: `dist\PLANC_Dependency_Explorer.exe --build`, then read `%APPDATA%\PLANC_Dependency_Explorer\build.log`.
     It must start with `OK` and give the reference numbers in HISTORY.md for the same release.
  2. `python tests/ui_smoke.py <tmp>`, then look at the screenshots.
- **Release:**
  1. Bump `__version__`.
  2. Commit and tag `vX.Y.Z`.
  3. Build the exe.
  4. Create a GitHub release with the tag and attach `dist\PLANC_Dependency_Explorer.exe`.
- **Licence:** PyMuPDF is AGPL-3.0 or commercial (Artifex). The user has been told. The alternative is pypdf (BSD;
  about 60 s for a 1500-page PDF, and it has outlines via `reader.outline`).

## Environment notes (author's PC)
- Windows 11. Python 3.12. Git Bash plus PowerShell.
- `gh` CLI is NOT installed. Git uses Git Credential Manager (a browser login on the first push).
- Under Git Bash, write files to `%APPDATA%` from Python, not from a heredoc (that went wrong once).
- A running instance locks `dist\*.exe`: close it before rebuilding.
