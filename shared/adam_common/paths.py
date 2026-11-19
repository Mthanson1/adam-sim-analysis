"""Path helpers so scripts work regardless of the current working directory."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def study_paths(script_file: str) -> dict[str, Path]:
    """Return the standard folders for the study containing `script_file`.

    Usage (inside a study's scripts/ folder):
        p = study_paths(__file__)
        df = pd.read_csv(p["inputs"] / "loads.csv")
    """
    study = Path(script_file).resolve().parent.parent
    paths = {
        "study": study,
        "model": study / "model",
        "inputs": study / "inputs",
        "results": study / "results",
        "figures": study / "results" / "figures",
    }
    paths["figures"].mkdir(parents=True, exist_ok=True)
    return paths
