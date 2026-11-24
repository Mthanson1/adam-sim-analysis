"""Pass/fail summary tables for study scripts (results/summary*.csv)."""
import csv


def check(criterion: str, value: float, unit: str, min: float | None = None,
          max: float | None = None) -> dict:
    """One summary row. With no min/max the row is informational."""
    if min is None and max is None:
        result = "info"
    else:
        ok = (min is None or value >= min) and (max is None or value <= max)
        result = "PASS" if ok else "FAIL"
    return {"criterion": criterion, "value": value, "unit": unit,
            "min": "" if min is None else min, "max": "" if max is None else max,
            "result": result}


def write_summary(rows: list[dict], path) -> bool:
    """Write rows to CSV, print them, and return True if no row failed."""
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for r in rows:
        limits = " ".join(f"{k} {r[k]:.4g}" for k in ("min", "max") if r[k] != "")
        print(f"{r['result']:5} {r['criterion']:48} {r['value']:>11.4g} {r['unit']:6} {limits}")
    return all(r["result"] != "FAIL" for r in rows)
