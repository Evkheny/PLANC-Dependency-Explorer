# PLANC Dependency Explorer - Release notes

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
