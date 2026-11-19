# CLAUDE.md

Simulation and analysis repo for the ADAM capstone. See [README.md](README.md) for the layout
and the study structure.

## Git workflow
- **Never commit or push directly to `main`.**
- Give each study its own branch and PR: `study/<domain>-<NN>-<short-name>`,
  e.g. `study/mechanical-01-dsif-friction-limit`.
- Changes outside a study (shared helpers, tooling, docs) also go on a branch and PR,
  e.g. `chore/<short-name>`.
- Keep a PR to one study or one change, so it can be reviewed and reverted on its own.
- Commit messages are one sentence. No `Co-Authored-By: Claude` line or other AI attribution.

## Code style
- Write code a human can follow on the first read: clear names, small functions,
  no clever one-liners.
- Comments are brief and only explain **non-obvious gotchas**: sign conventions, unit traps,
  solver quirks, why a value was chosen. Don't comment what the code already says.
- Docstrings: one or two lines on what the function does. Derivations and model assumptions
  go in the module docstring or the study README, not scattered through the code.
- Math-style names (`D`, `F_n`, `K`) are fine when they match the physics.
- Lengths in mm, stresses in MPa, forces in N, unless a script states otherwise.

## Linting
Run Ruff before committing; it must pass:
```
ruff check .
```
Config is in [ruff.toml](ruff.toml). Use `ruff check . --fix` for the auto-fixable issues.
CI ([.github/workflows/lint.yml](.github/workflows/lint.yml)) runs the same check on every PR.
When upgrading Ruff, bump the version in both `requirements.txt` and the workflow.

## Studies
- Start from `templates/study/` and fill in its README.
- Hand calcs live as PDFs in the team Drive, not in this repo.
- Write outputs through `adam_common.study_paths()`. Raw output goes to `results/`
  (gitignored); report figures go to `results/figures/` (committed).
- Material properties live in `shared/materials/*.csv` and are loaded with
  `adam_common.load_material()`. Don't hardcode them in scripts.
