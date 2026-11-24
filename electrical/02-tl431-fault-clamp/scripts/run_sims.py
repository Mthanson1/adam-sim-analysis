"""TL431 fault clamp: DC fault sweep, clamp stability vs rail capacitance, and 3V3 power-up.

    python electrical/02-tl431-fault-clamp/scripts/run_sims.py

Writes results/summary_sims.csv, results/fault_sweep.csv (read by thermal_check.py) and
figures in results/figures/. Exits non-zero on any FAIL.
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
from adam_common.spice import run_ngspice, trace

P = study_paths(__file__)
DEV = load_specs(P["inputs"] / "devices.csv")
CRIT = load_specs(P["inputs"] / "criteria.csv")
PARTS = load_parts()

RAIL_CAPS = ("C6", "C7", "C18", "C20", "C21", "C22", "C23", "C24")
C_RAIL_NOM = sum(PARTS[ref]["value"] for ref in RAIL_CAPS)
C_SWEEP = np.array([1, 3, 4.5, 6.21, 8, 9, 10, 12, 15, 22]) * 1e-6
I_SWEEP = np.array([5, 10, 20]) * 1e-3  # plus the simulated 24 V clamp current
OVERSHOOTS = (0.0, 0.02, 0.04, 0.06)


def rail_params(c_rail=C_RAIL_NOM, vset=CRIT["vset"]):
    return {"VSET": vset, "CRAIL": c_rail, "RESR": CRIT["resr"], "RLOAD": CRIT["rload"]}


# ---------- Sim 4: DC fault sweep ----------

def fault_sweep():
    """Node voltages and branch currents vs fault voltage, as a dict of arrays."""
    raw = run_ngspice(P["model"] / "dc_fault_sweep.cir", P["results"], params=rail_params())
    v = {name: np.real(trace(raw, f"v({name})"))
         for name in ("fault", "rail", "s0", "c0", "s1", "c1", "ctx", "crx")}
    i_ch0 = (v["s0"] - v["c0"]) / PARTS["R25"]["value"]
    i_ch1 = (v["s1"] - v["c1"]) / PARTS["R27"]["value"]
    i_tx = (v["fault"] - v["ctx"]) / PARTS["R29"]["value"]
    i_rx = (v["fault"] - v["crx"]) / PARTS["R31"]["value"]
    return {
        **{f"v_{k}": val for k, val in v.items()},
        "i_ch0": i_ch0, "i_ch1": i_ch1, "i_tx": i_tx, "i_rx": i_rx,
        "i_clamp": i_ch0 + i_ch1 + i_tx + i_rx,
        "i_tl431": np.real(trace(raw, "i(vk431)")),
    }


def at_fault(sweep, key, v_fault):
    return float(np.interp(v_fault, sweep["v_fault"], sweep[key]))


def save_sweep(sweep):
    keys = list(sweep)
    with open(P["results"] / "fault_sweep.csv", "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(keys)
        writer.writerows(zip(*(sweep[k] for k in keys), strict=True))


def plot_sweep(sweep):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7), sharex=True)
    vf = sweep["v_fault"]
    for key, label in (("i_tx", "UART TX (R29)"), ("i_rx", "UART RX (R31)"),
                       ("i_ch0", "prox CH0"), ("i_clamp", "total into clamps"),
                       ("i_tl431", "TL431 cathode")):
        ax1.plot(vf, sweep[key] * 1e3, label=label)
    ax1.set_ylabel("Current [mA]")
    ax1.legend(fontsize=9)
    for key, label in (("v_ctx", "UART TX node"), ("v_crx", "UART RX node"),
                       ("v_c0", "prox CH0 node"), ("v_rail", "+3V3 rail")):
        ax2.plot(vf, sweep[key], label=label)
    ax2.axhline(DEV["stm32_vdd_max"], ls="--", c="r", lw=0.8, label="VDD max")
    for v_fault in (CRIT["v_fault"], CRIT["v_fault_high"]):
        ax1.axvline(v_fault, ls=":", c="k", lw=0.8)
        ax2.axvline(v_fault, ls=":", c="k", lw=0.8)
    ax2.set_xlabel("Fault voltage on all clamped inputs [V]")
    ax2.set_ylabel("Voltage [V]")
    ax2.legend(fontsize=9)
    save_figure(fig, P["figures"] / "clamp_fault_sweep")


def fault_rows(sweep):
    node_max = DEV["ads1220_avdd"] + DEV["ads1220_ain_max_over_avdd"]
    rows = []
    for v_fault in (CRIT["v_fault"], CRIT["v_fault_high"]):
        tag = f"at {v_fault:g} V"
        rows += [
            check(f"Total clamp current {tag}", at_fault(sweep, "i_clamp", v_fault) * 1e3, "mA"),
            check(f"TL431 cathode current {tag}", at_fault(sweep, "i_tl431", v_fault) * 1e3, "mA",
                  max=DEV["tl431_ika_max"] * 1e3),
            check(f"+3V3 rail {tag}", at_fault(sweep, "v_rail", v_fault), "V",
                  max=DEV["stm32_vdd_max"]),
            check(f"Prox clamp node {tag}", at_fault(sweep, "v_c0", v_fault), "V", max=node_max),
            check(f"UART TX clamp node {tag}", at_fault(sweep, "v_ctx", v_fault), "V"),
            check(f"UART RX clamp node {tag}", at_fault(sweep, "v_crx", v_fault), "V"),
        ]
    return rows


# ---------- Sim 5: clamp stability ----------

def step_response(c_rail, i_fault):
    params = {**rail_params(c_rail), "IFAULT": i_fault, "TRISE": CRIT["trise"]}
    raw = run_ngspice(P["model"] / "stability_tran.cir", P["results"], params=params,
                      name="stability_tran")
    return np.real(trace(raw, "time")), np.real(trace(raw, "v(rail)"))


def sustained_pp(t, v):
    """Rail pk-pk over the last 1 ms of the 4 ms run (3 ms after the step)."""
    return np.ptp(v[t > 3e-3])


def stability_grid(currents):
    """pk-pk ripple [V] per (current, C), plus waveforms (one per C) at the top current."""
    grid = np.zeros((len(currents), len(C_SWEEP)))
    waves = []
    for i, i_fault in enumerate(currents):
        for j, c_rail in enumerate(C_SWEEP):
            t, v = step_response(c_rail, i_fault)
            grid[i, j] = sustained_pp(t, v)
            if i == len(currents) - 1:
                waves.append((t, v))
    return grid, waves


def plot_stability(currents, grid, waves):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7))
    for c_rail in (3e-6, 6.21e-6, 10e-6):
        t, v = waves[int(np.argmin(np.abs(C_SWEEP - c_rail)))]
        ax1.plot((t - 1e-3) * 1e3, v, label=f"{c_rail * 1e6:g} µF")
    ax1.set_xlim(-0.2, 3)
    ax1.set_xlabel(f"Time after {currents[-1] * 1e3:.1f} mA fault step [ms]")
    ax1.set_ylabel("+3V3 rail [V]")
    ax1.legend(title="effective C_rail", fontsize=9)
    floor = 1e-6  # stable cases settle to ~0 pk-pk; floor them so they show on a log axis
    for i, i_fault in enumerate(currents):
        ax2.semilogy(C_SWEEP * 1e6, np.maximum(grid[i], floor) * 1e3, "o-",
                     label=f"{i_fault * 1e3:.1f} mA")
    ax2.axhline(CRIT["osc_pp_max"] * 1e3, ls="--", c="r", lw=0.8, label="limit")
    ax2.axvline(C_RAIL_NOM * 1e6, ls=":", c="k", lw=0.8)
    ax2.text(C_RAIL_NOM * 1e6, 50, " nominal", fontsize=9)
    ax2.set_xlabel("Effective rail capacitance [µF]")
    ax2.set_ylabel("Sustained pk-pk ripple [mV]")
    ax2.legend(title="fault current", fontsize=9)
    save_figure(fig, P["figures"] / "clamp_stability")


def min_stable_c(grid):
    """Smallest swept capacitance that is stable at every current (and all larger ones too)."""
    stable = (grid <= CRIT["osc_pp_max"]).all(axis=0)
    for j in range(len(C_SWEEP)):
        if stable[j:].all():
            return C_SWEEP[j]
    return np.nan


# ---------- Sim 8: power-up and LDO / TL431 margin ----------

def threshold_min(temp_span):
    """Lowest TL431 clamp threshold: low Vref, temperature drift, R7 low / R8 high."""
    drift = DEV["tl431_vdev"] * temp_span / DEV["tl431_temp_span_full"]
    r7 = PARTS["R7"]["value"] * (1 - PARTS["R7"]["tol_pct"] / 100)
    r8 = PARTS["R8"]["value"] * (1 + PARTS["R8"]["tol_pct"] / 100)
    return (DEV["tl431_vref_min"] - drift) * (1 + r7 / r8)


def powerup(vset, overshoot):
    params = {**rail_params(vset=vset), "VPK": vset * (1 + overshoot), "TSTR": DEV["ldo_tstr"]}
    raw = run_ngspice(P["model"] / "powerup.cir", P["results"], params=params, name="powerup")
    return (np.real(trace(raw, "time")), np.real(trace(raw, "v(rail)")),
            np.real(trace(raw, "i(vk431)")))


def plot_powerup(results):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 6), sharex=True)
    for overshoot, (t, v, i_k) in results.items():
        ax1.plot(t * 1e3, v, label=f"{overshoot:.0%}")
        ax2.plot(t * 1e3, i_k * 1e3)
    ax1.set_ylabel("+3V3 rail [V]")
    ax1.legend(title="LDO overshoot", fontsize=9)
    ax2.set_xlabel("Time [ms]")
    ax2.set_ylabel("TL431 current [mA]")
    save_figure(fig, P["figures"] / "powerup")


def powerup_rows():
    vset_max = CRIT["vset"] * (1 + DEV["ldo_tol_25C"])
    results = {os: powerup(vset_max, os) for os in OVERSHOOTS}
    plot_powerup(results)

    lab_margin = threshold_min(CRIT["temp_span_lab"]) - vset_max
    full_margin = (threshold_min(DEV["tl431_temp_span_full"])
                   - CRIT["vset"] * (1 + DEV["ldo_tol_full"]))
    rows = [check(f"TL431 peak current, LDO +2 % with {os:.0%} overshoot",
                  results[os][2].max() * 1e3, "mA") for os in OVERSHOOTS]
    rows += [
        check("Clamp threshold min - LDO max, lab (25 C +/- 10 K)", lab_margin * 1e3, "mV", min=0),
        check("Clamp threshold min - LDO max, -40 to 85 C", full_margin * 1e3, "mV"),
    ]
    return rows


def main():
    apply_style()
    sweep = fault_sweep()
    save_sweep(sweep)
    plot_sweep(sweep)
    rows = fault_rows(sweep)

    i_clamp_24 = at_fault(sweep, "i_clamp", CRIT["v_fault"])
    currents = np.append(I_SWEEP, i_clamp_24)
    grid, waves = stability_grid(currents)
    plot_stability(currents, grid, waves)
    j_nom = int(np.argmin(np.abs(C_SWEEP - C_RAIL_NOM)))
    rows += [
        check("Nominal rail capacitance", C_RAIL_NOM * 1e6, "uF"),
        check("Sustained ripple at nominal C, 24 V fault current", grid[-1, j_nom] * 1e3, "mV",
              max=CRIT["osc_pp_max"] * 1e3),
        check("Smallest effective C stable at all currents", min_stable_c(grid) * 1e6, "uF"),
    ]

    rows += powerup_rows()
    if not write_summary(rows, P["results"] / "summary_sims.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
