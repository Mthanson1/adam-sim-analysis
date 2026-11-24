"""Input stage hot-plug: reversed supply (Q1 must block) and forward inrush.

    python electrical/05-reverse-polarity/scripts/run_sims.py

The supply ramps from 0 to +/-24 V over a range of rise times, because a fast edge couples
through Q1's Crss onto its gate. The board (V2) has C35 = 10 nF gate-source to stop that; the
reversed case is also run without C35 (board V1) for comparison. Writes
results/summary_sims.csv and figures.
"""
import sys

import matplotlib.pyplot as plt
import numpy as np

from adam_common import apply_style, check, load_specs, save_figure, study_paths, write_summary
from adam_common.spice import run_ngspice, trace

P = study_paths(__file__)
CRIT = load_specs(P["inputs"] / "criteria.csv")
T_START = 100e-6
RISE_TIMES = (1e-6, 10e-6, 100e-6, 1e-3)


def hot_plug(v_in, t_rise, without_c35=False):
    params = {"VIN": v_in, "TRISE": t_rise, "RLOAD": CRIT["rload"]}
    if without_c35:
        params["C35"] = CRIT["c35_absent"]
    raw = run_ngspice(P["model"] / "rev_pol.cir", P["results"], name="rev_pol", params=params)
    t = np.real(trace(raw, "time"))
    v_out = np.real(trace(raw, "v(vout)"))
    return {
        "t": t,
        "v_out": v_out,
        "v_gs": np.real(trace(raw, "v(g)")) - v_out,
        "v_ds": np.real(trace(raw, "v(vin_p)")) - v_out,
        "i_in": -np.real(trace(raw, "i(vin)")),  # current delivered by the supply
    }


def plot(reverse, reverse_v1, forward):
    fig, axes = plt.subplots(3, 1, figsize=(7, 9), sharex=True)
    for t_rise, r in reverse.items():
        label = f"{t_rise * 1e6:g} µs"
        axes[0].plot((r["t"] - T_START) * 1e6, r["v_out"], label=label)
        axes[1].plot((r["t"] - T_START) * 1e6, r["v_gs"], label=label)
    fast = min(reverse_v1)
    r = reverse_v1[fast]
    v1_label = f"{fast * 1e6:g} µs, without C35 (V1)"
    axes[0].plot((r["t"] - T_START) * 1e6, r["v_out"], "k--", label=v1_label)
    axes[1].plot((r["t"] - T_START) * 1e6, r["v_gs"], "k--", label=v1_label)
    for t_rise, r in forward.items():
        axes[2].plot((r["t"] - T_START) * 1e6, r["i_in"], label=f"{t_rise * 1e6:g} µs")
    axes[0].set_ylabel("Board +24 V rail [V]\n(-24 V plugged in)")
    axes[1].set_ylabel("Q1 V_GS [V]\n(-24 V plugged in)")
    axes[2].set_ylabel("Inrush current [A]\n(+24 V plugged in)")
    axes[2].axhline(CRIT["q1_idm"], ls="--", c="r", lw=0.8, label="Q1 I_DM")
    axes[2].set_xlabel("Time after plug-in starts [µs]")
    axes[2].set_xlim(-10, 300)
    for ax in axes:
        ax.legend(title="rise time", fontsize=8)
    save_figure(fig, P["figures"] / "hot_plug")


def main():
    apply_style()
    reverse = {tr: hot_plug(-CRIT["v_in"], tr) for tr in RISE_TIMES}
    reverse_v1 = {tr: hot_plug(-CRIT["v_in"], tr, without_c35=True) for tr in RISE_TIMES}
    forward = {tr: hot_plug(CRIT["v_in"], tr) for tr in RISE_TIMES}
    plot(reverse, reverse_v1, forward)

    rows = []
    for tr, r in reverse.items():
        tag = f"reverse, {tr * 1e6:g} us rise"
        rows += [
            check(f"Board rail min ({tag})", r["v_out"].min(), "V", min=CRIT["vout_min"]),
            check(f"Q1 |V_GS| max ({tag})", np.abs(r["v_gs"]).max(), "V", max=CRIT["vgs_max"]),
            check(f"Supply current peak ({tag})", np.abs(r["i_in"]).max(), "A"),
        ]
    for tr, r in reverse_v1.items():
        rows.append(check(f"Board rail min (reverse, {tr * 1e6:g} us, without C35)",
                          r["v_out"].min(), "V"))
    rows.append(check("Reverse leakage, Q1 IDSS (datasheet max)", CRIT["idss_max"] * 1e6, "uA"))
    for tr, r in forward.items():
        rows.append(check(f"Inrush peak (forward, {tr * 1e6:g} us rise)", r["i_in"].max(), "A",
                          max=CRIT["q1_idm"]))
    steady = forward[RISE_TIMES[-1]]
    fast = forward[RISE_TIMES[0]]
    on = np.abs(fast["v_gs"]) >= CRIT["vgs_on"]
    t_on = fast["t"][np.argmax(on)] - T_START if on.any() else np.nan
    rows.append(check(f"Forward: time to |V_GS| > {CRIT['vgs_on']:g} V (1 us plug-in)",
                      t_on * 1e3, "ms"))
    rows += [
        check("Forward: Q1 drop at load current", steady["v_ds"][-1] * 1e3, "mV"),
        check("Forward: Q1 |V_GS| (zener clamped)", np.abs(steady["v_gs"][-1]), "V",
              max=CRIT["vgs_max"]),
    ]
    if not write_summary(rows, P["results"] / "summary_sims.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
