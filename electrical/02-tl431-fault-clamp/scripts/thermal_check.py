"""Fault power in every part on a clamped or open-drain path, against its rating.

    python electrical/02-tl431-fault-clamp/scripts/thermal_check.py

Reads results/fault_sweep.csv from run_sims.py (run that first). The open-drain outputs
(Z_CONTACT, OUT0) are not clamped, so they are computed here: fault on the connector with the
2N7002 on, current limited by R30/R32 + R_DS(on). Writes results/summary_thermal.csv and
results/figures/fault_power.png. Exits non-zero on any FAIL.
"""
import csv
import sys

import matplotlib.pyplot as plt
import numpy as np

from adam_common import (
    apply_style,
    check,
    load_parts,
    load_specs,
    save_figure,
    study_paths,
    write_summary,
)

P = study_paths(__file__)
DEV = load_specs(P["inputs"] / "devices.csv")
CRIT = load_specs(P["inputs"] / "criteria.csv")
PARTS = load_parts()


def load_sweep():
    with open(P["results"] / "fault_sweep.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}


def resistor_rating(ref):
    return PARTS[ref]["power_W"] or DEV["r_0603_p"]


def tl431_rating():
    return (DEV["tj_max"] - CRIT["t_ambient"]) / DEV["tl431_theta_ja"]


def powers(sweep, v_fault):
    """(part, power W, rating W) at one fault voltage."""
    s = {k: float(np.interp(v_fault, sweep["v_fault"], v)) for k, v in sweep.items()}
    r = {ref: PARTS[ref]["value"] for ref in ("R13", "R14", "R25", "R29", "R30", "R31")}
    i_od = v_fault / (r["R30"] + DEV["nmos_rds_on_max"])
    p_d13 = s["i_tx"] * (s["v_ctx"] - s["v_rail"]) + s["i_rx"] * (s["v_crx"] - s["v_rail"])
    return [
        ("R13 (prox divider top)", (v_fault - s["v_s0"]) ** 2 / r["R13"], resistor_rating("R13")),
        ("R14 (prox divider bottom)", s["v_s0"] ** 2 / r["R14"], resistor_rating("R14")),
        ("R25 (prox Rs)", s["i_ch0"] ** 2 * r["R25"], resistor_rating("R25")),
        ("R29 (UART TX)", s["i_tx"] ** 2 * r["R29"], resistor_rating("R29")),
        ("R31 (UART RX)", s["i_rx"] ** 2 * r["R31"], resistor_rating("R31")),
        ("D13 BAV199DW (both UART diodes)", p_d13, DEV["bav199_p_max"]),
        ("D12 BAV199DW (prox CH0)", s["i_ch0"] * (s["v_c0"] - s["v_rail"]), DEV["bav199_p_max"]),
        ("U3 TL431", s["v_rail"] * s["i_tl431"], tl431_rating()),
        ("R30/R32 (open drain, FET on)", i_od**2 * r["R30"], resistor_rating("R30")),
        ("Q2/Q3 2N7002 (FET on)", i_od**2 * DEV["nmos_rds_on_max"], PARTS["Q2"]["power_W"]),
    ]


def plot_utilisation(tables):
    fig, ax = plt.subplots(figsize=(7, 5))
    names = [row[0] for row in tables[CRIT["v_fault"]]]
    y = np.arange(len(names))
    for k, (v_fault, table) in enumerate(tables.items()):
        util = [100 * p / rating for _, p, rating in table]
        ax.barh(y + (0.2 if k == 0 else -0.2), util, height=0.4, label=f"{v_fault:g} V fault")
    ax.axvline(100, ls="--", c="r", lw=0.8)
    ax.set_xscale("log")
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlabel(f"Power / rating at {CRIT['t_ambient']:.0f} C [%]")
    ax.legend()
    save_figure(fig, P["figures"] / "fault_power")


def main():
    apply_style()
    sweep = load_sweep()
    tables = {v: powers(sweep, v) for v in (CRIT["v_fault"], CRIT["v_fault_high"])}
    plot_utilisation(tables)

    rows = []
    for v_fault, table in tables.items():
        rows += [check(f"{name} at {v_fault:g} V", p * 1e3, "mW", max=rating * 1e3)
                 for name, p, rating in table]
    i_tx_low = CRIT["v_fault"] / (PARTS["R29"]["value"] + CRIT["r_mcu_pin"])
    # Per-pin limit not checked here (not in inputs); this is the sum-of-all-GPIO limit.
    rows.append(check("STM32 TX pin current if driving low at 24 V", i_tx_low * 1e3, "mA",
                      max=DEV["stm32_gpio_total"] * 1e3))
    if not write_summary(rows, P["results"] / "summary_thermal.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
