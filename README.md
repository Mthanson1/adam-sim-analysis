# ADAM: Simulation & Analysis

Simulation and analysis work for the ADAM engineering capstone: SPICE circuit sims,
FEA (ANSYS / SolidWorks Simulation), and custom Python analysis.

## Layout

```
adam-sim-analysis/
├── electrical/      # SPICE (LTspice/ngspice), power budgets, signal analysis
├── mechanical/      # Structural FEA, tolerance stacks, kinematics
├── shared/          # Code and data used across domains
│   ├── adam_common/ #   Python helpers (paths, plotting, material/parts loaders, ngspice runner)
│   ├── board/       #   Board parts tables (CSV, SI units; load with adam_common.load_parts)
│   ├── materials/   #   Material property tables (CSV; load with adam_common.load_material)
│   └── spice_models/#   Vendor SPICE models + ngspice self-test
└── templates/study/ # Copy this to start a new study
```

Add more domain folders (e.g. `thermal/`, `controls/`) as the project grows.

## Studies

Each piece of work is a **study**: a self-contained folder inside a domain, named
`NN-short-description` (e.g. `electrical/01-motor-driver-transient/`).

To start one, copy the template:

```powershell
Copy-Item -Recurse templates/study electrical/01-motor-driver-transient
```

Each study contains:

| Folder             | Contents                                                   | Committed?   |
|--------------------|------------------------------------------------------------|--------------|
| `model/`           | Tool source files: `.asc`, `.cir`, `.wbpj`, `.sldprt`, ... | Yes          |
| `scripts/`         | Python/MATLAB for pre/post-processing                      | Yes          |
| `inputs/`          | Small input data: parameters, loads, measured data         | Yes          |
| `results/`         | Raw solver output                                          | No (ignored) |
| `results/figures/` | Final plots and screenshots used in reports                | Yes          |
| `README.md`        | Goal, setup, assumptions, conclusions                      | Yes          |

Rule of thumb: **commit what you need to reproduce a result, plus the figures you
report. Don't commit anything a solver can regenerate.**

Hand calcs are stored as PDFs in the team Drive, not in this repo.

## Python setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e shared   # makes `import adam_common` work from any study
ruff check .            # lint (config in ruff.toml)
```

## SPICE setup

Electrical studies use **ngspice** in batch mode, driven from Python by
[`adam_common.spice`](shared/adam_common/spice.py). Netlists are plain-text `.cir` files in
each study's `model/` folder.

1. Download `ngspice-<ver>_64.7z` (version 47 or later) from
   <https://sourceforge.net/projects/ngspice/files/ng-spice-rework/> and extract it to
   `C:\Spice64` (so `C:\Spice64\bin\ngspice_con.exe` exists). Anywhere else works if you
   set the `NGSPICE` env var to the full path of `ngspice_con.exe`.
   On Linux or macOS, install the `ngspice` package instead.
2. Run the self-test: `python shared/spice_models/selftest.py`

Component values come from the board parts table
[`shared/board/adam_cal_v2.csv`](shared/board/adam_cal_v2.csv) (one row per refdes, SI units).
Netlists refer to them by refdes (`R13 a b {R13}`), so a BOM change is a one-line CSV edit.
Vendor models live in [`shared/spice_models/`](shared/spice_models/README.md).

Contribution rules (branch + PR per study, code style) are in [CLAUDE.md](CLAUDE.md).

## Large / binary files

CAD and FEA project files are binary and can be large. They are marked binary in
`.gitattributes`. If the repo starts getting big (files over ~50 MB, or many revisions of
CAD parts), move those extensions to Git LFS; see the comments in `.gitattributes`.
