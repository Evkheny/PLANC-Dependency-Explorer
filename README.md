# PLANC Dependency Explorer

Visual navigator of the PLANC controller: which function produces the TDI signals another function uses, the parameters
of each function, their STC1 Par number, owner, type selection and values per type, and the Controller Description text.

## What you need (all three of the same PLANC release)
| Source | Where to get it |
|---|---|
| PLANC repo `Controller` folder | Your local clone of the PLANC repo (`...\planc\Controller`, it contains `Subareas` and `Shared`). It is only read, never modified. |
| Controller Description (`.pdf`) | The Controller Description document of that release. |
| CoPaD parameter export (`.csv`) | Export the parameter values of the PLANC version to analyse from the CoPaD parameter database (e.g. `parVal173.0.0.1.csv`, `;`-separated). Only these columns are used: `parameterDefinitionName`, `parameterMappingName`, `typeName`, `typeValue`, `value`, `minValue`, `maxValue`, `matriceValue`, `owner`. |

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

Settings and the model are stored in `%APPDATA%\PLANC_Dependency_Explorer`. To rebuild without the window, run
`PLANC_Dependency_Explorer.exe --build`; it uses the saved sources and writes the result to `build.log`.

## Developers
- `planc_model.py` is the scanner. It can also be run on its own: `python planc_model.py <Controller> --cd <pdf> --csv <csv> --out model.json`.
- `planc_explorer.py` is the window (Tkinter).
- `build_exe.cmd` creates a venv, installs `pyinstaller` and `pymupdf`, and builds `dist\PLANC_Dependency_Explorer.exe`.

The PDF is read with PyMuPDF, which is dual-licensed: AGPL-3.0 or an Artifex commercial licence. Check that this fits your company's rules before distributing the `.exe` outside the team.

For AI agents and developers: read `CLAUDE.md` and `HISTORY.md` first. Smoke test: `python tests/ui_smoke.py <out folder>`
(needs `pillow` and a built model).
