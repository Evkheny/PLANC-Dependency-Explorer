# PLANC Dependency Explorer - Release notes

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
