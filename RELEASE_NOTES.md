# PLANC Dependency Explorer - Release notes

## v1.4.0 (12-Nov-2026)

### New
- **Copy tables with the right mouse button**, ready to paste in Excel or OneNote (also Word / Outlook):
  - Parameters, Signals and Type selections tabs, the values-per-type popup and the "What to tune first" ranking:
    *Copy selected rows* or *Copy whole table* (with the column headers).
  - Tuning overview: *Copy overview as table* (one row per field; bullets, bold and line breaks kept, each field in
    one Excel cell), *Copy selected text* and *Copy for Jira*.
  - The clipboard holds an HTML table and tab-separated text, so each application takes the format it handles best.

## v1.3.0 (08-Nov-2026)

### New
- **Load case view** (toolbar): which control strategies affect a load case or a load, and which make most sense to
  tune to reduce it.
  - **By load case:** the DLC in the centre (use: extreme if it enters ULS, fatigue if it enters FLS; functions
    disabled in that case) and an arrow from every functionality whose tuning has a High impact on it; each box tells the loads it acts on in that case (e.g. "Tower FA E, Blade flap E").
    Functions disabled in the case are dashed.
  - **By load:** pick a load group (tower fore-aft / side-side, blade flap / edge, pitch bearing, drivetrain, hub and
    bearings, tip clearance, overspeed, AEP) and a type (extreme / fatigue) to see the functionalities that act on it
    and in which load cases.
  - Only the strategies with **High** impact are shown (by load: High in a load case whose reason names that load), so
    the diagram stays short (e.g. tower fore-aft extreme: 7 strategies).
  - **What to tune first:** ranking with the reason (why the load case matters for that tuning) and the mechanism (how
    its tuning changes the load); double-click opens its tuning overview.
  - The load cases and their use come from the project simulation when one is loaded; otherwise the DLC codes of the
    knowledge base with the IEC default use.
- Knowledge base: load effects per functionality (183), to be reviewed with the Loads team.

## v1.2.0 (03-Nov-2026)

### Changed
- **Highly affected functionalities / Highly affected by** in the tuning overview are now *tuning couplings*: A → B
  means that changing the tunable (mainly WTGType-dependent) parameters of A requires re-tuning or re-checking B. Each
  coupling gives the physical reason and the parameters involved (113 couplings). Before, these rows listed signal
  links, which do not say whether the tuning of one function depends on another.
- The signal-link lists were removed from the overview; signal links remain in the graph.

### New
- **Graph: tuning couplings** (selector above the graph): left, the functions whose tuning highly affects the selected
  one; right, the functions whose tuning must be repeated or re-checked when it changes. Hover an arrow for the reason.

## v1.1.0 (03-Nov-2026)

### New
- **Tuning overview of each function:** the overview table of its tuning task, as in the Jira OVTASK (Name, Main Scope,
  Tuning KPI, Relevant DLCs, Highly affected functionalities, Highly affected by, Risk of not tuning). Tuning gates are
  not shown. Open it from the new **Tuning overview** tab or by clicking the centre box of the graph.
  - The text comes from a tuning knowledge base built into the tool (76 tasks). Text marked *(proposed)* must be
    reviewed.
  - It is completed with live data: the model links, with how each signal is used inside the consumer (main,
    scheduling / auxiliary, event data); the type-dependent parameters and the A/B differences; and the load cases of
    the project simulation that match each relevant DLC ("not simulated" when the project does not run it).
  - **Copy for Jira** copies the table as Jira wiki markup.
  - Functions with a tuning task are marked in the tree (column Tun.); filter "with tuning overview".
- **Simulations (optional input):** add simulation folders in **Sources**. The first one is the project simulation.
- **Load cases (DLCs) window**, the same as in SimStatsPlotter: the load cases of a simulation (wind, speeds,
  simulations, PSF, ULS/FLS use, events), the card of each case and the comparison of simulations (new / removed /
  changed cases, template differences), with export to Excel.

### Changed
- The model build also traces where each signal is used inside its consumers (about 15-25 s in total).
- Rebuild the model after updating (**Build model**), so that the overview shows the signal roles.

## v1.0.0 (02-Nov-2026), first release

A Windows desktop tool to navigate the PLANC controller (Simulink) and the dependencies between its functions. It
runs as a single executable; no Python is needed.

### What it shows
- **Signal dependencies:** for any controller function, a graph of the functions that produce its input TDI signals and
  the functions that consume its outputs. Click a box to navigate, use Back/Forward to return, and hover an arrow to
  see all its signals.
- **Parameters of each function:** the STC1 Par number, owner, type selection, min/max and value per type value, read
  from the CoPaD export. The tool also finds parameters that live in Simulink libraries and template parameters such as
  `..._LoadEstX_...`.
- **A/B comparison of type values:** for example, WTGType 165 vs 170 variant.
  - Parameters whose values differ are highlighted.
  - Affected functions get an orange border.
  - "only where A ≠ B" lists only the functions that change.
  - Double-click a parameter to see its value for every type value.
- **Type selections:** the ones used in the function logic (`T_<type>`), the ones its parameter values depend on, and
  the ones mentioned in the Controller Description.
- **Controller Description:** the matching section (number, chapter, page, introduction) for each function.
- **Legacy STC1 functions:** functions still implemented in legacy STC1 are shown dashed. Their type-dependent
  parameters are found through the Controller Description.
- **Search:** finds functions, signals, parameters and STC1 Par numbers.

### Inputs (all three of the same PLANC release)
1. The PLANC repo `Controller` folder. It is only read, never modified.
2. The Controller Description PDF.
3. The CoPaD parameter-value export (`parVal<version>.csv`) of that PLANC version, exported from the CoPaD parameter
   database.

### How to use
1. Unzip and run `PLANC_Dependency_Explorer.exe`.
2. Click **Sources**, select the three inputs and click **Build model**. A build takes about 30 s, and the model is
   remembered for the next start.
3. Choose the type selection and the values A and B to compare (top right).

Settings and the model are stored in `%APPDATA%\PLANC_Dependency_Explorer`. `PLANC_Dependency_Explorer.exe --build`
rebuilds the model without the window, using the saved sources, and writes the result to `build.log`.

### Verified with
PLANC 173.0.0.1, Controller Description 170.0.0.1 and `parVal173.0.0.1.csv`.

| Item | Result |
|---|---|
| Components | 179 (115 functions, 22 legacy-STC1 emulations, 42 test helpers) |
| Signals | 3067 |
| Producer→consumer links | 817 |
| Parameters used | 2409 (2212 found in CoPaD) |
| Controller Description sections | 141; 162 components matched to one |

### Known limitations
- Windows only.
- 10 functions are not matched to a Controller Description section because their names differ from the section
  titles.
- Parameters that are not in the CoPaD export, such as simulation-only parameters, show no values.
- CoPaD gives table (matrix) parameters only as a hash: the tool shows `matrix#xxxxxxxx`, and equal hashes mean equal
  tables.
- The PDF is read with PyMuPDF (licence AGPL-3.0 or Artifex commercial). Check your company's rules before
  distributing the executable outside your team.
