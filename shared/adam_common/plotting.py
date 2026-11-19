"""Consistent figure style across all studies."""
from pathlib import Path

import matplotlib.pyplot as plt


def apply_style() -> None:
    plt.rcParams.update({
        "figure.figsize": (7, 4.5),
        "figure.dpi": 110,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "font.size": 11,
        "savefig.bbox": "tight",
        "savefig.dpi": 300,
    })


def save_figure(fig, path, formats=("png",)) -> None:
    """Save a figure; pass formats=("png", "pdf") to also get a vector copy."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for ext in formats:
        fig.savefig(path.with_suffix(f".{ext}"))
