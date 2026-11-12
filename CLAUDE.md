# CLAUDE.md: PLANC Dependency Explorer

## What it is
A Windows desktop tool (Python + Tkinter, shipped as one `.exe` built with PyInstaller). For the PLANC wind-turbine
controller (Siemens Gamesa / Siemens Energy, Simulink) it shows, for every controller function:
- who produces its input TDI signals and who consumes its outputs;
- its parameters, with STC1 Par number, owner, type selection and value per type value;
- the matching Controller Description section.

Its main use is comparing two type values (e.g. two WTGType variants such as the 165 and the 170 rotor) to see which
functions and parameters change. Since v1.1.0 it also shows the **tuning overview** of each function (the Jira OVTASK
overview table, without gates) and the **load cases (DLCs)** of simulation folders.

**Read `HISTORY.md` before changing anything.** It holds the decisions, the reference numbers and the pitfalls.

## Hard rules
- **Only three model inputs**, all of the same PLANC release. This was the user's decision on 02-Nov-2026; do not add
  others (no Tuning Procedure, no manual maps, no project/planning files, no tuning-order output):
  1. the PLANC repo `Controller` folder;
  2. the Controller Description PDF;
  3. the CoPaD parameter-value export `parVal<version>.csv`.
- **Plus, optional, simulation folders** (user, 03-Nov-2026): read only, the first is the project simulation whose DLCs
  feed the tuning overview. The tuning knowledge base `tuning_kb.json` ships inside the tool (it is not an input).
- **"Highly affected functionalities / by" = tuning couplings, never signal links** (user, 03-Nov-2026): A → B when
  changing the tunable (mainly WTGType-dependent) parameters of A requires re-tuning or re-checking B, with the physical
  reason. Signal links stay in the signal graph only; the tuning-coupling graph is a complementary view.
- **Tuning overview content:** physics, not workflows; no run or seed counts; no tuning gates; no platform names in
  reasons. Dependencies are checked inside the slx (signal-use role), never assumed from names.
- **The PLANC repo is READ ONLY.** Never write to it and never run git commands in it.
- **Never commit company data:** (exception: `tuning_kb.json`, user decision 03-Nov-2026) no PDFs, CSV exports, model JSON, Controller Description text, screenshots, or the
  `legacy/` folder. `.gitignore` covers these; check `git status` before every commit.
- **The `.exe` is not committed.** It is attached to GitHub releases.
- **Language:** reply to the user (Eugenio) in Spanish (castellano). The UI, code, comments and README stay in English.
- **Publishing:** ask before pushing, publishing or creating releases. The GitHub repo is the user's personal one.

## Files
| File | Role |
|---|---|
| `planc_model.py` | Scanner. `build(ctrl, cd, copad, progress)` returns the model dict. It can also run as a CLI (`python planc_model.py <Controller> --cd <pdf> --csv <csv> --out model.json`). |
| `planc_explorer.py` | Tkinter UI, the `Explorer` class. `--build` does a headless rebuild from the saved config and writes `build.log`. Holds `__version__`. |
| `overview.py` | Tuning overview: `tasks_for(comp)`, `dlc_items` / `match_dlcs` / `dlc_rows` (KB DLC codes → simulation folders), `links` (model links with role), `type_params`, `jira_markup`. |
| `tuning_kb.json` | Tuning knowledge base: 76 tasks `{key, name, comp, cd, subarea, scope, kpi, dlcs, affects, affected_by, risk, workflow}` built from the SG5.2-170-HCF tuning sheets (gates and project-only sentences removed; `workflow` is not shown), plus `couplings` = `[{from, to, reason}]` (113 tuning couplings), `effects` = `{key: [{comp, kind, why}]}` (183 load effects, kind E / F / EF), `components` (load groups), `keywords` (words that name a load group in a DLC reason) and `dlc_switch` (DLC set-up label → OVTASK of a function switched off in the case). `effects` / `components` / `keywords` / `dlc_switch` come from the project's `tools/tuning_sheets/load_effects.py`. `affects` / `affected_by` are generated from `couplings` by the project's `tools/tuning_sheets/coupling.py` (single source: edit there, then regenerate the Word document and this file). Markup: `**bold**`, `- ` bullets, `[P]` = proposed. `comp` is None for 6 tasks. Bundled in the exe (`--add-data`). |
| `clipboard_win.py` | Clipboard with two formats at once: "HTML Format" (CF_HTML, table) + CF_UNICODETEXT (TSV, Excel quoting). `bind_tree_copy` = right-click menu on a Treeview (selected rows / whole table). Line breaks inside a cell use `<br style="mso-data-placement:same-cell">` so Excel keeps a field in one cell. Falls back to the Tk clipboard (text). |
| `loadview.py` | Load case view: `affecting(code, setup, comp, kind)` (functionalities affecting a DLC, with level, reasons, load effects matching the DLC use E / F, disabled flag, score), `affecting_load(comp, kind)` (by load), `LoadCaseWindow` (DLC list, filters, diagram, ranking). |
| `slx_trace.py` | `Slx(path).first_users(inport)`: the first blocks that use a root inport inside a component (through Goto/From, subsystems and library links). |
| `dlcsetup.py`, `dlcview.py`, `screen_fit.py` | Copied from `D:\PYTHON_functions_epm\SimStatsPlotter` (keep in sync): load-case reader and the Load cases window. |
| `dlc_inputs.py`, `dlc_viewutil.py` | The numpy-free parts of SimStatsPlotter `extremes.py` / `loadcalc.py` (ULS/FLS input readers) and `viewutil.py` (`help_layout`, `tree`). |
| `build_exe.cmd` | Creates a `.buildenv` venv, pip-installs pyinstaller + pymupdf + openpyxl, builds `dist\PLANC_Dependency_Explorer.exe` (onefile, windowed, with `tuning_kb.json`). |
| `run_explorer.cmd` | Runs from source with `pythonw`. |
| `tests/ui_smoke.py` | Drives the UI and saves 6 screenshots with PrintWindow (works behind other windows; needs pillow and an existing model; ui4-ui6 = overview tab, overview window, Load cases). |
| `requirements.txt` | pymupdf, openpyxl (runtime), pyinstaller (build), pillow (test). |
| `legacy/` | Local only, git-ignored: the first, project-specific version. Not used. |

User data: `%APPDATA%\PLANC_Dependency_Explorer\`, which holds `config.json` (paths, `sims` list and compare choice),
`planc_model.json` (cache), `dlccache\` (load cases read from the simulations) and `build.log`.

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

**13. `trace_signal_use`** (v1.1.0). For every link and signal, `slx_trace.Slx(consumer).first_users(signal)` gives the
first blocks that use it; `edge['use'][sig]` keeps up to 4 `"path: block"`, and `classify_use` sets `edge['role'][sig]`
from the innermost path segment + block name only (the full path gave false hits, e.g. ESFE "frequenc"):
`event data` (event/alarm/warning/reason), `scheduling / auxiliary` (notch, nP, frequency, gain scheduling, scaling,
selector, status...), `main`, or `not traced`.

Model JSON keys: meta, components, signals, parameters, typeselections, edges (with `use` and `role`),
outside_model_params, cd.

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
- **Copy:** every detail table gets `clipboard_win.bind_tree_copy` in `Explorer.table`; the overview Text has
  `ov_menu` (copy as table = `overview.table_rows` → `paras_text` / `paras_html`; copy selection; copy for Jira).
  Tested by pasting into Excel through COM (parameters 28 x 10; overview 8 x 2 with bullets U+2022, line breaks, bold).
- **Load case view** (`loadview.LoadCaseWindow`, toolbar button): DLC use from the simulation set-up (`setup.uls` /
  `setup.fls`; IEC default by code when no simulation), functions disabled in the case from the 'Control functions' /
  'Safety system' facts mapped with `dlc_switch`. DLC match: exact, `x` wildcard, and a code without letter matches its
  lettered variants (`2.1` → 2.1g). **Only High impact is shown** (user, 08-Nov-2026): by DLC, level == High; by load,
  a High DLC row whose reason names the load (`named_components`). Score = level (3 / 2 / 1) + 0.5 if the reason names the load + 0.5 if direct
  (mechanism not starting "through") − 0.7 for monitors; by-load also + 0.1 per High DLC (max 5).
- **Graph mode** (`self.gmode`): `draw` = signal links, `draw_tuning` = tuning couplings from `overview.couplings(comp)`
  (grouped by peer; tasks without a Simulink function are grey boxes; hover = reasons).
- **Tuning overview** (first tab, and a window when the centre box is clicked): `ov_frame` / `fill_overview` /
  `render_overview`. Task combobox: tasks of the function, then the tasks not tied to one function. DLC names are links
  to a card (`dlc_card`); function names navigate. "Copy for Jira" = `overview.jira_markup`.
- **Simulations:** Sources panel listbox (`self.sims`, saved in config). `load_project_sim` reads the first one in a
  thread (`dlcsetup.load_sim`, cache `dlccache`); `self.loaded` (label → SimDlcs) is shared with the Load cases window
  (`DlcWindow`, a subclass of `dlcview.DlcWindow` that also adds new folders to the list and refreshes the overview).
- **Top right:** compare type selection, value A, value B. These are saved in config.
- **Threading:** the build runs in a thread, and status updates go through `self.after`.
- **DPI:** the process is made DPI-aware (`SetProcessDpiAwareness(1)`).

## Build, test, release
- **Run from source:** `pip install pymupdf`, then `python planc_explorer.py`.
- **Exe:** run `build_exe.cmd`, which builds from `PLANC_Dependency_Explorer.spec` (committed). pymupdf 2.x pulls numpy,
  onnxruntime, pymupdf4llm and pymupdf_layout (excluded modules), and its wheel ships the layout ONNX models
  (`pymupdf/layout`) and MuPDF dev files (`mupdf-devel`), which the spec filters out of `a.datas` / `a.binaries`:
  `import pymupdf` needs none of them. `tuning_kb.json` is a data file (read through `sys._MEIPASS`). About 32 MB.
  Without the filter the exe is about 75 MB.
- **Verify after changes:**
  1. Headless build: `dist\PLANC_Dependency_Explorer.exe --build`, then read `%APPDATA%\PLANC_Dependency_Explorer\build.log`.
     It must start with `OK` and give the reference numbers in HISTORY.md for the same release.
  2. `python tests/ui_smoke.py <tmp>`, then look at the screenshots.
- **Load effects update:** edit `load_effects.py` in the project, run it (checks), export `effects`, `components`,
  `keywords`, `dlc_switch` into `tuning_kb.json`, rebuild the exe.
- **Knowledge-base update** (couplings or sheet text changed in the project): regenerate `tuning_kb.json` from the
  project's `tools/tuning_sheets` (`coupling.fields` for `affects` / `affected_by`, `couplings` = `coupling.EDGES`), check
  that `kb['couplings']` equals `coupling.EDGES`, bump `version` in the json, rebuild the exe.
- **Release:**
  1. Bump `__version__`.
  2. Commit and tag `vX.Y.Z`.
  3. Build the exe.
  4. Add a section to `RELEASE_NOTES.md`, then build `release\PLANC_Dependency_Explorer_vX.Y.Z.zip` containing the
     exe, README.md and RELEASE_NOTES.md (PowerShell `Compress-Archive`; `release/` is git-ignored).
  5. Create a GitHub release with the tag, paste that version's notes and attach the zip. The user pushes and publishes
     the release themself, because Claude Code's auto mode blocks `git push`.
- **Licence:** PyMuPDF is AGPL-3.0 or commercial (Artifex). The user has been told. The alternative is pypdf (BSD;
  about 60 s for a 1500-page PDF, and it has outlines via `reader.outline`).

## Environment notes (author's PC)
- Windows 11. Python 3.12. Git Bash plus PowerShell.
- `gh` CLI is NOT installed. Git uses Git Credential Manager (a browser login on the first push).
- Under Git Bash, write files to `%APPDATA%` from Python, not from a heredoc (that went wrong once).
- A running instance locks `dist\*.exe`: close it before rebuilding.
