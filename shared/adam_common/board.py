"""Board parts tables stored as CSV in shared/board/.

One row per refdes, values in SI units (ohm, F, W, V). Blank cells load as None,
numbers as float, everything else (mpn, package, notes) as str. These tables are the
single source of component values for both SPICE netlists and Python analyses.
"""
import csv

from .paths import REPO_ROOT

BOARD_DIR = REPO_ROOT / "shared" / "board"


def _parse(cell: str):
    if cell.strip() == "":
        return None
    try:
        return float(cell)
    except ValueError:
        return cell


def load_parts(board: str = "adam_cal_v2") -> dict[str, dict]:
    """All parts in shared/board/<board>.csv, keyed by refdes."""
    with open(BOARD_DIR / f"{board}.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["refdes"]: {k: _parse(v) for k, v in r.items() if k != "refdes"} for r in rows}


def part(refdes: str, board: str = "adam_cal_v2") -> dict:
    """One part's row. Raises KeyError listing valid refdes."""
    parts = load_parts(board)
    if refdes not in parts:
        raise KeyError(f"{refdes!r} not in {board}.csv; options: {sorted(parts)}")
    return parts[refdes]
