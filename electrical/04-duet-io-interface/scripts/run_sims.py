"""Duet interface: Z_CONTACT/OUT0 open drain (sim 6) and UART TX edges (sim 7).

    python electrical/04-duet-io-interface/scripts/run_sims.py

Writes results/summary_sims.csv and figures in results/figures/. Exits non-zero on any FAIL.
"""
import sys

import matplotlib.pyplot as plt
import numpy as np

from adam_common import (
    apply_style,
    check,
    load_specs,
    part,
    save_figure,
    study_paths,
    write_summary,
)
from adam_common.spice import run_ngspice, trace

P = study_paths(__file__)
CRIT = load_specs(P["inputs"] / "criteria.csv")
T_ON, T_OFF = 100e-6, 500e-6  # open-drain gate pulse edges in open_drain.cir
UART_T0 = 2e-6  # first falling edge in uart_tx.cir
UART_CABLES = np.array([100, 220, 470, 1000]) * 1e-12
R30 = part("R30")["value"]


def first_cross(t, v, level, after, rising):
    """First time after `after` that v crosses `level` in the given direction."""
    mask = t > after
    hit = (v[mask] >= level) if rising else (v[mask] <= level)
    return t[mask][np.argmax(hit)] if hit.any() else np.nan


# ---------- Sim 6: open drain ----------

def open_drain(rpu, c_cable):
    raw = run_ngspice(P["model"] / "open_drain.cir", P["results"], name="open_drain",
                      params={"RPU": rpu, "CCABLE": c_cable})
    t = np.real(trace(raw, "time"))
    return t, {fet: np.real(trace(raw, f"v(in{fet})")) for fet in ("t", "w")}


def open_drain_metrics(t, v):
    v_low = np.interp(T_OFF - 1e-6, t, v)
    fall = first_cross(t, v, CRIT["v_il"], T_ON, rising=False) - T_ON
    rise = first_cross(t, v, CRIT["v_ih"], T_OFF, rising=True) - T_OFF
    return v_low, fall, rise


def open_drain_fault():
    """Current and power split between R30 and the FET at the fault voltage, typ and worst."""
    raw = run_ngspice(P["model"] / "open_drain_fault.cir", P["results"])
    vf = np.real(trace(raw, "v(ext)"))
    out = {}
    for fet in ("t", "w"):
        v_d = np.interp(CRIT["v_fault"], vf, np.real(trace(raw, f"v(d{fet})")))
        i = (CRIT["v_fault"] - v_d) / R30
        out[fet] = {"i": i, "p_r30": i**2 * R30, "p_fet": i * v_d}
    return out


def plot_open_drain(cases):
    fig, ax = plt.subplots()
    for (rpu, c_cable), (t, v) in cases.items():
        ax.plot((t - T_ON) * 1e6, v["w"], label=f"{rpu / 1e3:g}k pull-up, {c_cable * 1e12:g} pF")
    ax.axhline(CRIT["v_il"], ls="--", c="r", lw=0.8)
    ax.axhline(CRIT["v_ih"], ls="--", c="r", lw=0.8)
    ax.set_xlabel("Time after Z_DRV high [µs] (worst-case FET)")
    ax.set_ylabel("Duet input pin [V]")
    ax.set_xlim(-20, 520)
    ax.legend(fontsize=9)
    save_figure(fig, P["figures"] / "open_drain")


def sim6_rows():
    cases = {(rpu, c): open_drain(rpu, c)
             for rpu in (CRIT["rpu_opto"], CRIT["rpu_nonopto"])
             for c in (CRIT["c_cable_min"], CRIT["c_cable_max"])}
    plot_open_drain(cases)
    rows = []
    for (rpu, c_cable), (t, v) in cases.items():
        tag = f"{rpu / 1e3:g}k, {c_cable * 1e12:g} pF, worst FET"
        v_low, fall, rise = open_drain_metrics(t, v["w"])
        rows += [
            check(f"OD V_low ({tag})", v_low, "V", max=CRIT["v_il"]),
            check(f"OD fall to V_IL ({tag})", fall * 1e6, "us"),
            check(f"OD rise to V_IH ({tag})", rise * 1e6, "us", max=CRIT["od_rise_max"] * 1e6),
        ]
    fault = open_drain_fault()
    for fet, name in (("t", "typ"), ("w", "worst")):
        f = fault[fet]
        rows += [
            check(f"OD fault current at {CRIT['v_fault']:g} V, {name} FET", f["i"] * 1e3, "mA"),
            check(f"OD fault R30 power, {name} FET", f["p_r30"] * 1e3, "mW",
                  max=CRIT["r30_p_max"] * 1e3),
            check(f"OD fault FET power, {name} FET", f["p_fet"] * 1e3, "mW",
                  max=CRIT["fet_p_max"] * 1e3),
        ]
    return rows


# ---------- Sim 7: UART TX ----------

def uart(c_cable):
    tbit = 1 / CRIT["baud"]
    raw = run_ngspice(P["model"] / "uart_tx.cir", P["results"], name="uart_tx",
                      params={"TBIT": tbit, "CCABLE": c_cable, "RPU": CRIT["rpu_opto"]})
    return np.real(trace(raw, "time")), np.real(trace(raw, "v(in)"))


def edge_times(t, v):
    """10-90 % fall time (bit start) and rise time (bit end) at the Duet pin."""
    tbit = 1 / CRIT["baud"]
    v_hi = v[t < UART_T0].mean()
    v_lo = np.interp(UART_T0 + 0.95 * tbit, t, v)
    lvl10 = v_lo + 0.1 * (v_hi - v_lo)
    lvl90 = v_lo + 0.9 * (v_hi - v_lo)
    fall = (first_cross(t, v, lvl10, UART_T0, rising=False)
            - first_cross(t, v, lvl90, UART_T0, rising=False))
    t_end = UART_T0 + tbit
    rise = (first_cross(t, v, lvl90, t_end, rising=True)
            - first_cross(t, v, lvl10, t_end, rising=True))
    return v_lo, fall, rise


def plot_uart(waves, edges, limit):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7))
    for c_cable, (t, v) in waves.items():
        ax1.plot((t - UART_T0) * 1e6, v, label=f"{c_cable * 1e12:g} pF")
    ax1.set_xlim(-1, 12)
    ax1.set_xlabel("Time after start bit [µs] (115200 baud)")
    ax1.set_ylabel("Duet input pin [V]")
    ax1.legend(title="cable C", fontsize=9)
    ax2.plot(UART_CABLES * 1e12, edges[:, 0] * 1e9, "o-", label="fall 10-90 %")
    ax2.plot(UART_CABLES * 1e12, edges[:, 1] * 1e9, "o-", label="rise 10-90 %")
    ax2.axhline(limit * 1e9, ls="--", c="r", lw=0.8, label="5 % of a bit")
    ax2.set_xlabel("Cable capacitance [pF]")
    ax2.set_ylabel("Edge time [ns]")
    ax2.legend()
    save_figure(fig, P["figures"] / "uart_tx")


def sim7_rows():
    waves = {c: uart(c) for c in UART_CABLES}
    metrics = np.array([edge_times(*waves[c]) for c in UART_CABLES])
    limit = CRIT["uart_edge_frac"] / CRIT["baud"]
    plot_uart(waves, metrics[:, 1:], limit)
    slowest = metrics[:, 1:].max(axis=1)
    c_max = np.interp(limit, slowest, UART_CABLES)  # edge time rises monotonically with C
    rows = [check("UART V_low at Duet pin", metrics[:, 0].max(), "V", max=CRIT["v_il"])]
    for c_cable, (_, fall, rise) in zip(UART_CABLES, metrics, strict=True):
        rows.append(check(f"UART slowest edge, {c_cable * 1e12:g} pF", max(fall, rise) * 1e9, "ns",
                          max=limit * 1e9 if c_cable <= CRIT["c_cable_min"] else None))
    rows.append(check("UART max cable C for 5 % edges", c_max * 1e12, "pF"))
    return rows


def main():
    apply_style()
    rows = sim6_rows() + sim7_rows()
    if not write_summary(rows, P["results"] / "summary_sims.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
