"""Material property tables stored as CSV in shared/materials/.

Each CSV has a `name` column plus property columns whose names end in a unit
suffix (e.g. `E_MPa`, `uts_MPa`). The suffix is stripped on load, so
`load_material("aa3003-o")` returns {"E": 69000.0, "nu": 0.33, "uts": 110.0, ...}.
Columns that don't parse as numbers (e.g. `notes`) are kept as strings.
"""
import csv

from .paths import REPO_ROOT

MATERIALS_DIR = REPO_ROOT / "shared" / "materials"
_UNIT_SUFFIXES = ("_MPa", "_GPa", "_Pa", "_kgm3", "_K", "_C")


def _strip_unit(col: str) -> str:
    for suf in _UNIT_SUFFIXES:
        if col.endswith(suf):
            return col[: -len(suf)]
    return col


def _parse(v: str):
    try:
        return float(v)
    except ValueError:
        return v


def load_table(table: str = "sheet_metals") -> dict[str, dict]:
    """All materials in shared/materials/<table>.csv, keyed by name."""
    path = MATERIALS_DIR / f"{table}.csv"
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {
        r["name"]: {_strip_unit(k): _parse(v) for k, v in r.items() if k != "name"}
        for r in rows
    }


def load_material(name: str, table: str = "sheet_metals") -> dict:
    """Properties of one material. Raises KeyError listing valid names."""
    mats = load_table(table)
    if name not in mats:
        raise KeyError(f"{name!r} not in {table}.csv; options: {sorted(mats)}")
    return mats[name]
