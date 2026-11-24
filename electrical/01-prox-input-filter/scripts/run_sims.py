"""Prox input filter: AC response, Monte Carlo CM-to-DM conversion, and step settling.

    python electrical/01-prox-input-filter/scripts/run_sims.py

Writes results/summary_sims.csv and figures in results/figures/. Exits non-zero on any FAIL.
"""
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
from adam_common.spice import monte_carlo, run_ngspice, trace, uniform_tol

P = study_paths(__file__)
ADS = load_specs(P["inputs"] / "ads1220.csv")
CRIT = load_specs(P["inputs"] / "criteria.csv")
PARTS = load_parts()
MC_PARTS = ("R13", "R14", "R25", "R26", "C28", "C29", "C32")


def db(x):
    return 20 * np.log10(np.abs(x))


def at_freq(f, y, f0):
    """Interpolate y at f0 on a log-frequency axis."""
    return np.interp(np.log10(f0), np.log10(f), y)


def ac_responses(raw):
    """Frequency, DM transfer (out_diff / vin) and CM-to-DM conversion (out_diff / vcm)."""
    f = np.real(trace(raw, "frequency"))
    h_dm = trace(raw, "v(a_p)") - trace(raw, "v(a_n)")
    h_cm = trace(raw, "v(b_p)") - trace(raw, "v(b_n)")
    return f, h_dm, h_cm


def ac_metrics(f, h_dm, h_cm):
    """Corner, attenuation at f_mod and CM conversion at line and buck frequencies (dB)."""
    rel_db = db(h_dm) - db(h_dm[0])
    corner = np.interp(3.0103, -rel_db, f)
    return {
        "corner": corner,
        "atten_fmod": -at_freq(f, rel_db, ADS["f_mod"]),
        "cm_line": at_freq(f, db(h_cm), CRIT["f_line"]),
        "cm_buck": at_freq(f, db(h_cm), CRIT["f_buck"]),
    }


def sample_parts(rng):
    return {ref: uniform_tol(rng, PARTS[ref]["value"], PARTS[ref]["tol_pct"]) for ref in MC_PARTS}


def settling_time(t, v, t_step, frac):
    """Time after t_step until v stays within frac of its final value."""
    outside = np.abs(v - v[-1]) > frac * abs(v[-1])
    return t[np.nonzero(outside)[0][-1]] - t_step


def plot_ac(f, h_dm, h_cm, mc, h_dm_fix, h_cm_fix):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7), sharex=True)
    rel = db(h_dm) - db(h_dm[0])
    mc_rel = np.array([db(h) - db(h[0]) for _, h, _ in mc])
    ax1.fill_between(f, mc_rel.min(axis=0), mc_rel.max(axis=0), alpha=0.3, label="MC envelope")
    ax1.semilogx(f, rel, label="nominal")
    ax1.semilogx(f, db(h_dm_fix) - db(h_dm_fix[0]), "--", label="proposed R26")
    ax1.axvline(ADS["f_mod"], ls="--", c="k", lw=0.8)
    ax1.text(ADS["f_mod"], -10, " f_mod", fontsize=9)
    ax1.set_ylabel("DM gain rel. DC [dB]")
    ax1.set_ylim(-80, 5)
    ax1.legend()

    mc_cm = np.array([db(h) for _, _, h in mc])
    ax2.fill_between(f, mc_cm.min(axis=0), mc_cm.max(axis=0), alpha=0.3, label="MC envelope")
    ax2.semilogx(f, db(h_cm), label="nominal")
    ax2.semilogx(f, db(h_cm_fix), "--", label="proposed R26")
    limit_db = 20 * np.log10(ADS["noise_rms"] / CRIT["v_cm"])
    ax2.axhline(limit_db, ls="--", c="r", lw=0.8, label="noise floor / v_cm")
    for f0 in (CRIT["f_line"], CRIT["f_buck"]):
        ax2.axvline(f0, ls=":", c="k", lw=0.8)
    ax2.set_xlabel("Frequency [Hz]")
    ax2.set_ylabel("CM-to-DM conversion [dB]")
    ax2.legend()
    save_figure(fig, P["figures"] / "prox_filter_ac")


def plot_step(t, v, t_step, t_cal, t_16):
    fig, ax = plt.subplots()
    t_ms = (t - t_step) * 1e3
    ax.plot(t_ms, v)
    ax.axvline(t_cal * 1e3, ls="--", c="k", lw=0.8, label=f"0.1 %: {t_cal * 1e3:.2f} ms")
    ax.axvline(t_16 * 1e3, ls=":", c="k", lw=0.8, label=f"16 bit: {t_16 * 1e3:.2f} ms")
    ax.axvline(CRIT["sensor_response"] * 1e3, ls="-.", c="r", lw=0.8, label="sensor response")
    ax.set_xlim(-0.5, 8)
    ax.set_xlabel("Time after 0 to 10 V step [ms]")
    ax.set_ylabel("ADC differential input [V]")
    ax.legend()
    save_figure(fig, P["figures"] / "prox_filter_step")


def step_response(out, params, name):
    raw = run_ngspice(P["model"] / "step.cir", out, params=params, name=name)
    return np.real(trace(raw, "time")), np.real(trace(raw, "v(p)") - trace(raw, "v(n)"))


def main():
    apply_style()
    out = P["results"]

    f, h_dm, h_cm = ac_responses(run_ngspice(P["model"] / "ac_mc.cir", out))
    nominal = ac_metrics(f, h_dm, h_cm)

    runs = monte_carlo(P["model"] / "ac_mc.cir", out, sample_parts, int(CRIT["mc_runs"]),
                       extract=ac_responses)
    mc = [responses for _, responses in runs]
    mc_metrics = [ac_metrics(*r) for r in mc]
    worst = {
        "atten_fmod": min(m["atten_fmod"] for m in mc_metrics),
        "cm_line": max(m["cm_line"] for m in mc_metrics),
        "cm_buck": max(m["cm_buck"] for m in mc_metrics),
        "corner_lo": min(m["corner"] for m in mc_metrics),
        "corner_hi": max(m["corner"] for m in mc_metrics),
    }
    fix = {"R26": CRIT["r26_balanced"]}
    _, h_dm_fix, h_cm_fix = ac_responses(run_ngspice(P["model"] / "ac_mc.cir", out, params=fix,
                                                     name="ac_mc_fix"))
    proposed = ac_metrics(f, h_dm_fix, h_cm_fix)
    plot_ac(f, h_dm, h_cm, mc, h_dm_fix, h_cm_fix)

    t, v = step_response(out, {}, "step")
    t_step = 100e-6
    t_cal = settling_time(t, v, t_step, CRIT["settle_frac_cal"])
    t_16 = settling_time(t, v, t_step, 2.0 ** -CRIT["settle_bits"])
    plot_step(t, v, t_step, t_cal, t_16)
    t_fix, v_fix = step_response(out, fix, "step_fix")
    t_cal_fix = settling_time(t_fix, v_fix, t_step, CRIT["settle_frac_cal"])

    # CM conversion limit: a v_cm disturbance must convert to less than the ADC rms noise.
    cm_limit = 20 * np.log10(ADS["noise_rms"] / CRIT["v_cm"])
    rows = [
        check("DM corner (nominal)", nominal["corner"], "Hz"),
        check("DM corner MC min", worst["corner_lo"], "Hz"),
        check("DM corner MC max", worst["corner_hi"], "Hz"),
        check("Attenuation at f_mod, MC worst", worst["atten_fmod"], "dB",
              min=CRIT["atten_fmod_min"]),
        check("CM-to-DM at buck freq (nominal)", nominal["cm_buck"], "dB"),
        check("CM-to-DM at buck freq, MC worst", worst["cm_buck"], "dB", max=cm_limit),
        check("CM-to-DM at 60 Hz, analog only (nominal)", nominal["cm_line"], "dB"),
        check("CM-to-DM at 60 Hz, analog only, MC worst", worst["cm_line"], "dB"),
        check("CM-to-DM at 60 Hz incl. 20 SPS notch, MC worst",
              worst["cm_line"] - ADS["nmrr_60Hz"], "dB", max=cm_limit),
        check("Settling to 0.1 %", t_cal * 1e3, "ms"),
        check("Settling to 16 bit", t_16 * 1e3, "ms"),
        check("DC gain", v[-1] / 10, "V/V"),
        check("Proposed R26: DM corner", proposed["corner"], "Hz"),
        check("Proposed R26: CM-to-DM at buck freq", proposed["cm_buck"], "dB", max=cm_limit),
        check("Proposed R26: CM-to-DM at 60 Hz, analog only", proposed["cm_line"], "dB"),
        check("Proposed R26: settling to 0.1 %", t_cal_fix * 1e3, "ms"),
    ]
    if not write_summary(rows, out / "summary_sims.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
