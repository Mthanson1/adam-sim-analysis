"""Run ngspice netlists in batch mode from Python and read the results.

A study netlist is plain ngspice syntax with two conventions:
  - Component values are written as parameters named by refdes, e.g. `R13 a b {R13}`.
    `run_ngspice` defines them from the board parts table (shared/board/*.csv), and any
    `params` passed in override them. That way values live in one place, not in netlists.
  - `.include` / `.lib` paths are looked up next to the netlist first, then in
    shared/spice_models/. Netlists can write `.include bav199.lib` without a relative path.

Each run writes a deck, a `.spiceinit`, a log and a `.raw` file into `out_dir`
(normally the study's gitignored results/ folder). Units are SI throughout.
"""
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np
from spicelib import RawRead

from .board import load_parts
from .paths import REPO_ROOT

MODELS_DIR = REPO_ROOT / "shared" / "spice_models"
_DEFAULT_INSTALLS = (
    Path("C:/Spice64/bin"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Spice64" / "bin",
)
_INCLUDE_RE = re.compile(r'^(\s*\.(?:include|inc|lib)\s+)"?([^"\s]+)"?(.*)$', re.IGNORECASE)


def find_ngspice() -> Path:
    """Locate the ngspice console executable (NGSPICE env var, then PATH, then default installs)."""
    if os.environ.get("NGSPICE"):
        return Path(os.environ["NGSPICE"])
    # On Windows, ngspice.exe opens its own GUI window; ngspice_con.exe is the console build.
    for exe in ("ngspice_con", "ngspice"):
        found = shutil.which(exe)
        if found:
            return Path(found)
    for folder in _DEFAULT_INSTALLS:
        for exe in ("ngspice_con.exe", "ngspice.exe"):
            if (folder / exe).exists():
                return folder / exe
    raise FileNotFoundError(
        "ngspice not found. Install it (see README 'SPICE setup') or set the NGSPICE env var."
    )


def _format_value(value: float) -> str:
    return f"{value:.9g}"


def _resolve_include(path_text: str, netlist_dir: Path) -> str:
    candidate = Path(path_text)
    if candidate.is_absolute():
        return path_text
    for folder in (netlist_dir, MODELS_DIR):
        if (folder / candidate).exists():
            return (folder / candidate).resolve().as_posix()
    raise FileNotFoundError(f"{path_text!r} not found next to the netlist or in {MODELS_DIR}")


def build_deck(netlist: Path, params: dict[str, float], board: str | None) -> str:
    """Netlist text with board/override `.param` lines added and include paths made absolute."""
    netlist = Path(netlist)
    lines = netlist.read_text().splitlines()
    title, body = lines[0], lines[1:]

    for name in params:
        if re.search(rf"^\s*\.param\b.*\b{re.escape(name)}\s*=", "\n".join(body),
                     re.IGNORECASE | re.MULTILINE):
            # Two definitions of one .param are ambiguous in ngspice, so don't allow it.
            raise ValueError(f"{netlist.name} defines .param {name}; it can't also be overridden")

    values = {}
    if board:
        values.update({ref: p["value"] for ref, p in load_parts(board).items()
                       if isinstance(p.get("value"), float)})
    values.update(params)
    param_lines = [f".param {name}={_format_value(v)}" for name, v in values.items()]

    resolved = []
    for line in body:
        match = _INCLUDE_RE.match(line)
        if match:
            head, path_text, tail = match.groups()
            line = f'{head}"{_resolve_include(path_text, netlist.parent)}"{tail}'
        resolved.append(line)
    return "\n".join([title, *param_lines, *resolved]) + "\n"


def _check_log(log_path: Path) -> None:
    errors = [ln for ln in log_path.read_text(errors="replace").splitlines()
              if ln.lower().startswith(("error", "fatal")) or "simulation(s) aborted" in ln]
    if errors:
        raise RuntimeError(f"ngspice reported errors (see {log_path}):\n" + "\n".join(errors))


def run_ngspice(netlist, out_dir, params: dict[str, float] | None = None,
                name: str | None = None, board: str | None = "adam_cal_v2",
                compat: str = "psa") -> RawRead:
    """Run one netlist in batch mode and return the parsed .raw file.

    `compat="psa"` turns on ngspice's PSpice/LTspice compatibility, which the vendor
    models in shared/spice_models/ need. Pass `board=None` to skip the parts table.
    """
    netlist = Path(netlist)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = name or netlist.stem
    deck = out_dir / f"{name}.cir"
    raw = out_dir / f"{name}.raw"
    log = out_dir / f"{name}.log"

    deck.write_text(build_deck(netlist, params or {}, board))
    # ngspice reads .spiceinit from the working directory before parsing the deck,
    # which is the only place the compatibility mode takes effect for model files.
    (out_dir / ".spiceinit").write_text(f"set ngbehavior={compat}\nset filetype=binary\n")

    result = subprocess.run(
        [str(find_ngspice()), "-b", "-r", raw.name, "-o", log.name, deck.name],
        cwd=out_dir, capture_output=True, text=True,
    )
    if result.returncode != 0 or not raw.exists():
        raise RuntimeError(f"ngspice failed on {netlist.name} (exit {result.returncode}); "
                           f"see {log}\n{result.stderr}")
    _check_log(log)
    return RawRead(str(raw), dialect="ngspice", verbose=False)


def monte_carlo(netlist, out_dir, sampler: Callable[[np.random.Generator], dict[str, float]],
                n: int, seed: int = 0, keep_files: bool = False,
                **run_kwargs) -> list[tuple[dict[str, float], RawRead]]:
    """Run `netlist` n times with parameters drawn by `sampler(rng)`; return (params, raw) pairs.

    Each run's deck, log and .raw are deleted once read unless keep_files=True.
    """
    rng = np.random.default_rng(seed)
    runs = []
    for i in range(n):
        params = sampler(rng)
        name = f"{Path(netlist).stem}_mc{i:04d}"
        raw = run_ngspice(netlist, out_dir, params=params, name=name, **run_kwargs)
        if not keep_files:
            for ext in (".cir", ".log", ".raw"):
                (Path(out_dir) / f"{name}{ext}").unlink(missing_ok=True)
        runs.append((params, raw))
    return runs


def uniform_tol(rng: np.random.Generator, nominal: float, tol_pct: float) -> float:
    """Draw a value uniformly within ±tol_pct of nominal (worst-case-leaning for MC)."""
    return nominal * (1 + rng.uniform(-1, 1) * tol_pct / 100)


def trace(raw: RawRead, name: str) -> np.ndarray:
    """One trace from a raw file as a numpy array (complex for AC analyses)."""
    return np.asarray(raw.get_trace(name).get_wave())
