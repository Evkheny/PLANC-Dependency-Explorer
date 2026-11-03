# HISTORY: PLANC Dependency Explorer

Read together with `CLAUDE.md`. Section 0 is the current state; then the timeline, decisions, reference numbers, domain
knowledge and ideas.

## 0. Current state (03-Nov-2026, evening)
- **Version 1.2.0** (local commit, not pushed): "Highly affected functionalities / by" rewritten as tuning couplings with
  the physical reason (113 couplings), model-link sections removed from the overview, new graph mode "tuning couplings".
- **Version 1.1.0** (tagged locally by the user): tuning overview per function + load cases (DLCs) of simulation folders.
- **Version 1.0.0** was released on GitHub on 02-Nov-2026.
- **Repository:** the user's personal GitHub. The `.exe` goes in the release assets; company data is never committed.
- **Open points:**
  - PyMuPDF licence (AGPL or commercial) vs company rules; pypdf is the fallback.
  - 10 functions without a Controller Description section match (list in section 3).
  - 197 model parameters not in the CoPaD export, which are internal or simulation parameters (e.g. `BHawC_*`,
    `Optional_*`, `Conv_DFIGEnable`).

## 1. Purpose and origin
The tool was created in the session that planned the Turbine Control tuning of the NPD project SG5.2-170-HCF (folder
`D:\ON TE LC TC OPT\38_SG5.2-170_HCF`). The Turbine Control engineer (Eugenio, TCOV) needed to see, from the real
Simulink model:
- the dependencies between controller functions (TDI producers and consumers);
- their parameters, and which ones depend on type selections.

Turbine Control tunes only the functions whose parameters depend on type selections: mainly WTGType (the platform
variant), plus OpWIceTy, HWOType and WGPFType. The tool therefore highlights type-dependent parameters and compares two
type values.

## 2. Timeline and decisions
- **02-Nov-2026 morning, v0 (project-specific, now in `legacy/`).**
  - Scanner of the PLANC repo plus a Tkinter UI.
  - Inputs: PLANC folder, `parameter_mappings_173.0.0.1.xlsx` (no values, only name/type/owner), the Tuning Procedure
    workbook (OVTASK ids), `mapping.json` (component → OVTASK by hand), the CD as pdftotext text, and the project plan.
  - Exported a tuning order per gate to `Tuning_Procedure_proposal.xlsx` (`tp_update.py`).
- **02-Nov-2026 afternoon, v1.0.0. The user's decision:**
  - The tool needs only the PLANC path, the Controller Description and the CoPaD export, nothing else.
  - The parameter source is the CoPaD csv `parVal<version>.csv`: the xlsx was only the user's own conversion of it.
  - No tuning-order or planning outputs.
  - It must be an executable anyone can use.
- **Changes made for v1.0.0:**
  - lxml replaced by `xml.etree`.
  - pdftotext replaced by PyMuPDF, using the PDF bookmarks: 9 s for 1491 pages, against about 5 min with pdftotext.
  - OVTASK and the tuning order removed.
  - A/B comparison of type values added.
  - Config moved to `%APPDATA%`.
  - `--build` headless mode added.
  - PyInstaller onefile exe.
- **02-Nov-2026:** the tool moved to `D:\PYTHON_functions_epm\PLANC_Dependency_Explorer`, plus CLAUDE.md, HISTORY.md, the
  smoke test and the git repo.
- **03-Nov-2026 evening, v1.2.0. The user's correction:** in OVTASK-122 the overview said the Speed-Pitch Controller
  highly affects the Pitch Reference Limiter because the limiter uses PitchRefCollective. The user: "Highly affected
  functionalities" means that tuning THIS function affects the performance / tuning of the other one to a high degree,
  and "Highly affected by" the reverse, always with the underlying physics and focused on the tunable (WTGType)
  parameters; signal links are not the criterion. The signal graphs are fine and stay; the tuning guides show only
  tuning couplings; complementary tuning graphs are welcome.
  - Done: one coupling graph (`tools/tuning_sheets/coupling.py` in the project, 113 edges, each with one reason written
    once and shown on both sheets), cited parameter names checked against the model / CoPaD. Example: the Pitch Reference
    Limiter (rate limit, deadband) affects the Speed-Pitch PI and IPC, not the reverse.
- **03-Nov-2026, v1.1.0. The user's request:** add the Overview table of each tuning task (as in the Jira OVTASKs and the
  Word document `Tuning_Task_Sheets_SG5.2-170-HCF.docx` of the SG5.2-170-HCF project), shown when clicking the box of a
  function, without the tuning gates; add the simulation path(s) as the only new input, with the same DLC detail and
  comparison as SimStatsPlotter; the project DLCs feed the Relevant DLCs of the overview.
  - The overview text comes from a knowledge base built into the tool (`tuning_kb.json`, from the project's
    `tools/tuning_sheets/content_*.py`), not from a new input. Removed from it: gates, sources, sentences that compare
    project reference types or name open points of the project, and the plan notes. The `workflow` field is kept in the
    file but not shown (the user does not want workflow references).
  - The tool adds what is live: the model links with the role of each signal inside the consumer (traced in the slx),
    the CoPaD A/B differences and the matching load cases of the simulations.
  - SimStatsPlotter's `dlcsetup.py` / `dlcview.py` / `screen_fit.py` are copied unchanged except the imports; the numpy
    parts of `extremes.py` / `loadcalc.py` / `viewutil.py` are left out (`dlc_inputs.py`, `dlc_viewutil.py`), so the exe
    stays without numpy.
  - DLC matching: KB codes such as `1.2a`, `2.4a/b`, `3.x` (any 3.*), `1.7` (→ 1.7p/1.7q when there is no plain 1.7);
    post-processing (extrapolation) cases are skipped; codes not in the project are shown "not simulated".

## 3. Reference numbers (PLANC 173.0.0.1 repo state of 02-Nov-2026, CD 170.0.0.1, `parVal173.0.0.1.csv`)
Use these to check that a change did not break the scanner. Counts change with other releases.

**Model:**
- 179 components: 115 functions, 22 STC1 emulations, 42 test harness helpers.
- 3067 signals and 817 producer→consumer links.
- 2409 parameters used, 2212 of them in CoPaD.

**CoPaD csv:**
- 90 453 rows, 3218 parameters.
- Type selections: WTGType 80 034 rows; others include BldType, HWProfil, GenType, HTRTType, OpWIceTy, HWOType and
  WGPFType.
- 62 WTGType values, for example `Ge_04800_165_00_N0_00_00`, `Ge_06600_170_00_N0_00_00` and `Ge_07000_170_00_N0_00_00`.

**Controller Description:**
- 1491 pages, 1652 bookmarks, 141 level-2 sections.
- 162 of 179 components matched to a section.
- Not matched: BladeFrequencyEstimator, HydraulicPressureMonitor, ExternalOffsetInterface, AlarmHandler, OrientationStop,
  StopSignalConverter, HighPerformanceParkPilot, ConverterControl, InsDriver, WindSpeedFilter.

**Parameters outside the model:** 428 type-dependent parameters (249 WTGType), 289 of them located in a CD section.

**Spot checks:**

| Component | CD section | Type-dependent parameters |
|---|---|---|
| SpeedPitchController | 7.7 | 22 WTGType |
| BladeLoadLimiter | 9.4 | 9 |
| RotorSpeedFilter | 3.5 | 25 |
| TowerFrequencyEstimator | 4.5 | 4 |
| PitchTrajectoryTables | 6.5 | 70 WTGType + 1 BldType |
| OperationWithIce_Helper | 13.2 | (OWI_* via CD) |

For 165 (`Ge_04800`) vs 170 (`Ge_07000`): 61 of 70 parameters of PitchTrajectoryTables differ, and 17 of the 22 of
SpeedPitchController.

**Signal-use roles (v1.1.0):** main 1333, scheduling / auxiliary 330, event data 61, not traced 3. Checks: ADTD2,
BladeLoadLimiter and TTCC use RotSpdFi_Spd as auxiliary; ESFE uses it as main; OverspeedMonitor and TwrVibMon use
PitchRefCollective as event data. The full rebuild with tracing takes about 15-25 s.

**Load cases (v1.1.0):** `S:\LR\SG5X\MkIB\70_170\SG5XMkIB70170LR20a`: 71 load cases (4 post-processing), 5 ULS and
8 FLS inputs, about 10 s from S: (then cached). OVTASK-121: 1.2a → DLC12a x2; 1.4/9.4w → DLC14_ECD_SS, DLC94w; OVTASK-125:
9.4c not simulated.

**Timing:** the exe build takes about 90 s on the author's PC. The exe is about 37 MB.

## 4. Domain knowledge an agent needs
- **TDI** = the signal interface between functions. Root Inport/Outport block names in each component `.slx` equal the
  names in `Shared/Signals.xml` (a `__` in a name is a struct dot).
- **Parameters:**
  - `Shared/Parameters.xml` gives the STC1 Par number in `Mapping[@interface=STC1]`.
  - Multi-parameters (tables) have layers.
  - CoPaD `parameterMappingName` is the same `ParNNNNNN`.
- **Type selections:** WTGType, OpWIceTy and WGPFType act only through the parameter values loaded by STC1. They do not
  appear as logic in the model. 17 type selections do appear in the logic as `T_<type>`.
- **STC1 legacy functions:** some functions still run in legacy STC1 C++ (Operation, HWRT, AirDensity,
  ReductionInterface, ADTD v1, ANR, SST, OWI...). The model has only a helper that emulates them, and their parameters
  are found through the Controller Description.
- **Test harness helpers:** `HARNESS` set plus `<Component>_Helper`. They are hidden by default.
- **Platform facts from the project** (useful for interpretation; not encoded in the tool):
  - Pitch Kick disabled, Active Idle unused, HWRT not in the product.
  - ANR handled by Loads/SCADA; rotor imbalance tuned by SLC.

## 5. Pitfalls met
- **pymupdf 2.0 dependencies:** it installs numpy, onnxruntime, pymupdf4llm and pymupdf_layout. Exclude them in
  PyInstaller, or the exe grows a lot. Plain `import pymupdf` works without them.
- **Headings in the PDF text:** PyMuPDF puts the section number and title on separate lines ("9.4.1" / "Introduction").
  Use the bookmarks for sections and whitespace-collapsed text for the intro.
- **`|Type|` marks** can break across lines: use the regex `\|\s*([A-Za-z][A-Za-z0-9]{3,11})\s*\|` on collapsed text.
- **Narrow centre canvas:** signal labels overlapped the boxes. Labels are now truncated to the free gap (`maxc`), and
  the font of the centre name shrinks with its length.
- **Config written from a Git Bash heredoc** under `$APPDATA` ended up empty or wrong. Write it from Python.
- **Locked exe:** a running instance (a onefile bootloader plus a child process) locks `dist\*.exe` and its folder.
- **Screenshots in the smoke test** with `ImageGrab` caught whatever window was on top (the user's Teams); it now uses
  `PrintWindow` on the window handle.
- **DLC text split:** splitting the KB "Relevant DLCs" on `;` inside parentheses produced empty chunks; split only at
  top level (`_split_top`).
- **Matrix parameters** have no value in CoPaD, only a hash (`matriceValue`), which is shown as `matrix#xxxxxxxx`.
  Equal hashes mean equal tables.

## 6. Ideas for next versions (not requested yet)
- Export the A/B differences per function to CSV or Excel.
- Graph depth 2 (producers of producers) or a full-network view with filters.
- Compare two PLANC releases (two models) instead of two type values.
- Better CD matching for the 10 unmatched functions (a manual alias table would break the "only 3 sources" rule; prefer
  fuzzy matching on the short name or the description).
- Show units and descriptions from CoPaD if a future export includes them.
- Use pypdf instead of PyMuPDF if the licence is a problem.
