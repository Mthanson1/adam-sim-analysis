"""Shared helpers for ADAM simulation and analysis scripts."""
from .materials import load_material, load_table
from .paths import REPO_ROOT, study_paths
from .plotting import apply_style, save_figure

__all__ = [
    "REPO_ROOT",
    "apply_style",
    "load_material",
    "load_table",
    "save_figure",
    "study_paths",
]
