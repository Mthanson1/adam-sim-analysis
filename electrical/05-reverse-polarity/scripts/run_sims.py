"""Input stage hot-plug: reversed supply (Q1 must block) and forward inrush.

    python electrical/05-reverse-polarity/scripts/run_sims.py

The supply ramps from 0 to +/-24 V over a range of rise times, because a fast edge couples
through Q1's Crss onto its gate. The reversed case is run as built and with the proposed
gate-source capacitor. Writes results/summary_sims.csv and figures.
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


def hot_plug(v_in, t_rise, c_gs=CRIT["cgs_ext_none"]):
    raw = run_ngspice(P["model"] / "rev_pol.cir", P["results"], name="rev_pol",
                      params={"VIN": v_in, "TRISE": t_rise, "RLOAD": CRIT["rload"],
                              "CGSEXT": c_gs})
    t = np.real(trace(raw, "time"))
    v_out = np.real(trace(raw, "v(vout)"))
    return {
        "t": t,
        "v_out": v_out,
        "v_gs": np.real(trace(raw, "v(g)")) - v_out,
        "v_ds": np.real(trace(raw, "v(vin_p)")) - v_out,
        "i_in": -np.real(trace(raw, "i(vin)")),  # current delivered by the supply
    }


def plot(reverse, reverse_fix, forward):
    fig, axes = plt.subplots(3, 1, figsize=(7, 9), sharex=True)
    for t_rise, r in reverse.items():
        label = f"{t_rise * 1e6:g} µs"
        axes[0].plot((r["t"] - T_START) * 1e6, r["v_out"], label=label)
        axes[1].plot((r["t"] - T_START) * 1e6, r["v_gs"], label=label)
    fast = min(reverse_fix)
    r = reverse_fix[fast]
    fix_label = f"{fast * 1e6:g} µs + {CRIT['cgs_ext_proposed'] * 1e9:g} nF C_GS"
    axes[0].plot((r["t"] - T_START) * 1e6, r["v_out"], "k--", label=fix_label)
    axes[1].plot((r["t"] - T_START) * 1e6, r["v_gs"], "k--", label=fix_label)
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
    reverse_fix = {tr: hot_plug(-CRIT["v_in"], tr, CRIT["cgs_ext_proposed"]) for tr in RISE_TIMES}
    forward = {tr: hot_plug(CRIT["v_in"], tr) for tr in RISE_TIMES}
    plot(reverse, reverse_fix, forward)

    rows = []
    for tr, r in reverse.items():
        tag = f"reverse, {tr * 1e6:g} us rise"
        rows += [
            check(f"Board rail min ({tag})", r["v_out"].min(), "V", min=CRIT["vout_min"]),
            check(f"Q1 |V_GS| max ({tag})", np.abs(r["v_gs"]).max(), "V", max=CRIT["vgs_max"]),
            check(f"Supply current peak ({tag})", np.abs(r["i_in"]).max(), "A"),
        ]
    fix_nf = CRIT["cgs_ext_proposed"] * 1e9
    for tr, r in reverse_fix.items():
        rows.append(check(f"Board rail min (reverse, {tr * 1e6:g} us, {fix_nf:g} nF C_GS)",
                          r["v_out"].min(), "V", min=CRIT["vout_min"]))
    rows.append(check("Reverse leakage, Q1 IDSS (datasheet max)", CRIT["idss_max"] * 1e6, "uA"))
    for tr, r in forward.items():
        rows.append(check(f"Inrush peak (forward, {tr * 1e6:g} us rise)", r["i_in"].max(), "A",
                          max=CRIT["q1_idm"]))
    steady = forward[RISE_TIMES[-1]]
    rows += [
        check("Forward: Q1 drop at load current", steady["v_ds"][-1] * 1e3, "mV"),
        check("Forward: Q1 |V_GS| (zener clamped)", np.abs(steady["v_gs"][-1]), "V",
              max=CRIT["vgs_max"]),
    ]
    if not write_summary(rows, P["results"] / "summary_sims.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
