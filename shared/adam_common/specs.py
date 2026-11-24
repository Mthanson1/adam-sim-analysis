"""Datasheet and requirement values kept as CSV in a study's inputs/ folder.

Columns: name, value, unit, source (datasheet + table/page), note. Only `name` and
`value` are read; the rest documents where each number came from.
"""
import csv
from pathlib import Path


def load_specs(path) -> dict[str, float]:
    """Map name -> value (float) from a specs CSV."""
    with open(Path(path), newline="") as fh:
        return {row["name"]: float(row["value"]) for row in csv.DictReader(fh)}
