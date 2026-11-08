# PLANC Dependency Explorer

Visual navigator of the PLANC controller: which function produces the TDI signals another function uses, the parameters
of each function, their STC1 Par number, owner, type selection and values per type, and the Controller Description text.

## What you need (all three of the same PLANC release)
| Source | Where to get it |
|---|---|
| PLANC repo `Controller` folder | Your local clone of the PLANC repo (`...\planc\Controller`, it contains `Subareas` and `Shared`). It is only read, never modified. |
| Controller Description (`.pdf`) | The Controller Description document of that release. |
| CoPaD parameter export (`.csv`) | Export the parameter values of the PLANC version to analyse from the CoPaD parameter database (e.g. `parVal173.0.0.1.csv`, `;`-separated). Only these columns are used: `parameterDefinitionName`, `parameterMappingName`, `typeName`, `typeValue`, `value`, `minValue`, `maxValue`, `matriceValue`, `owner`. |

Optional: one or more **simulation folders** of the loads tool (the folder holding `Btc\`, `Res\` and `Post\`). They
are only read. The first one is the project simulation: its load cases (DLCs) fill the "Relevant DLCs" of the tuning
overview. The others can be compared with it in the **Load cases (DLCs)** window.

Nothing else is needed. No Python is needed on the PC that runs the `.exe`.

## Use
1. Run `PLANC_Dependency_Explorer.exe`.
2. Click **Sources**, select the three paths, then click **Build model**. A build takes about 30 s, and the model is remembered for the next start.
3. Pick a function on the left. The search also finds signals, parameters and STC1 Par numbers.
4. The graph shows:
   - the producers of the function's inputs on the left (blue arrows);
   - the consumers of its outputs on the right (green arrows).

   Click a box to navigate and use Back/Forward to return. Hover an arrow to see all its signals. Dashed boxes are functions still in legacy STC1, emulated by a helper in the model.
5. **Compare** (top right): choose a type selection (e.g. `WTGType`) and two type values A and B (e.g. the 165 and the 170 variants).
   - Parameters whose value differs are highlighted.
   - Functions with differences get an orange border.
   - **only where A ≠ B** lists just those functions.
6. Tabs:
   - **Parameters**: red = type-dependent; purple = STC1 parameter outside the Simulink model (found in the Controller Description section). Double-click a parameter to see all its values per type.
   - **Signals**: double-click a signal to jump to its producer or consumer.
   - **Type selections**.
   - **Description**: model data plus the Controller Description introduction.
   - **Tuning overview**: see below.
7. **Tuning overview** (tab, or click the centre box of the graph): the overview table of the tuning task of the
   function, as in the Jira OVTASK (tuning gates omitted):
   - Name, Main Scope, Tuning KPI, Relevant DLCs, Highly affected functionalities, Highly affected by, Risk of not
     tuning: from the built-in tuning knowledge base (`tuning_kb.json`, 76 tasks). Text marked *(proposed)* must be
     reviewed.
   - **Load cases of the project:** for each relevant DLC, the load cases of the project simulation that match it, or
     "not simulated". Click one to see its set-up. With more simulations loaded, each one is listed.
   - **Highly affected functionalities / Highly affected by** are *tuning couplings*, not signal links: A → B means that
     changing the tunable (mainly WTGType-dependent) parameters of A requires re-tuning or re-checking B. Each coupling
     gives the physical reason and the parameters involved.
   - **Type-dependent parameters:** how many depend on the compared type selection and which values differ between A and B.
   - **Copy for Jira** copies the table as Jira wiki markup.
   - When a function has several tuning tasks (e.g. the Speed-Pitch Controller), pick one in **Tuning task**. Tasks that
     are not tied to one Simulink function are listed at the end.
8. **Graph: signal links / tuning couplings** (above the graph): *signal links* is the TDI producer / consumer graph;
   *tuning couplings* draws the couplings of the overview: left, the functions whose tuning highly affects this one;
   right, the functions whose tuning must be repeated or re-checked when this one changes. Hover an arrow for the reason.
9. **Load case view** (toolbar): which control strategies affect a load case or a load, and which make most sense to
   tune to reduce it.
   - **By load case:** pick a DLC (the project simulation's, or the DLC codes of the knowledge base). The DLC sits in
     the centre with its use (extreme = in ULS, fatigue = in FLS) and the functions disabled in that case; every
     functionality whose tuning affects it points at it. The box says which loads it acts on in that case (e.g. "Tower FA E, Blade flap E"); dashed =
     disabled in the case.
   - **By load:** pick "(all load cases) - by load" and a load group (Tower fore-aft, Blade flap, Pitch bearing,
     Drivetrain, Hub / bearings, Clearance, Overspeed, AEP...) and type (extreme / fatigue).
   - **Only strategies with High impact are shown:** High relevance of that load case in their tuning sheet; by load,
     High in a load case whose reason names that load. Filters: load group and load type. Example: tower load rising in
     DLC 1.4 → pick DLC 1.4, Tower fore-aft, Extreme.
   - **What to tune first** (right): ranking by relevance, whether the reason names that load, direct vs indirect action
     (estimators act through other functions) and monitors last (they protect, they do not reduce the load). Select a
     row for the reason and the mechanism; double-click (or click a box) opens its tuning overview.
10. **Load cases (DLCs)**: the same window as SimStatsPlotter. It lists the load cases of a simulation (wind, speeds,
   number of simulations, PSF, ULS/FLS use, events), opens the card of each load case, and compares simulations: new,
   removed and changed cases, and the template differences.

Settings, the model and the load-case cache (`dlccache`) are stored in `%APPDATA%\PLANC_Dependency_Explorer`. To rebuild without the window, run
`PLANC_Dependency_Explorer.exe --build`; it uses the saved sources and writes the result to `build.log`.

## Developers
- `planc_model.py` is the scanner. It can also be run on its own: `python planc_model.py <Controller> --cd <pdf> --csv <csv> --out model.json`.
- `planc_explorer.py` is the window (Tkinter).
- `overview.py` builds the tuning overview from `tuning_kb.json`, the model and the load cases.
- `loadview.py` is the Load case view (logic: `affecting`, `affecting_load`; window: `LoadCaseWindow`).
- `dlcsetup.py`, `dlcview.py`, `dlc_inputs.py`, `dlc_viewutil.py`, `screen_fit.py` are copied from SimStatsPlotter (load
  cases; keep them in sync). `slx_trace.py` traces where a signal is used inside a consumer.
- `build_exe.cmd` creates a venv, installs `pyinstaller`, `pymupdf` and `openpyxl`, and builds
  `dist\PLANC_Dependency_Explorer.exe` (with `tuning_kb.json` inside).

The PDF is read with PyMuPDF, which is dual-licensed: AGPL-3.0 or an Artifex commercial licence. Check that this fits your company's rules before distributing the `.exe` outside the team.

For AI agents and developers: read `CLAUDE.md` and `HISTORY.md` first. Smoke test: `python tests/ui_smoke.py <out folder>`
(needs `pillow` and a built model).
