"""Shared helpers for ADAM simulation and analysis scripts."""
from .board import load_parts, part
from .materials import load_material, load_table
from .paths import REPO_ROOT, study_paths
from .plotting import apply_style, save_figure
from .specs import load_specs
from .summary import check, write_summary

__all__ = [
    "REPO_ROOT",
    "apply_style",
    "check",
    "load_material",
    "load_parts",
    "load_specs",
    "load_table",
    "part",
    "save_figure",
    "study_paths",
    "write_summary",
]
