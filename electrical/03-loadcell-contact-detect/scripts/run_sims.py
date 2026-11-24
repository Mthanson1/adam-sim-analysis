"""Load cell input filter: AC response, group delay and step response.

    python electrical/03-loadcell-contact-detect/scripts/run_sims.py

Writes results/summary_sims.csv and figures in results/figures/.
"""
import sys

import matplotlib.pyplot as plt
import numpy as np

from adam_common import apply_style, check, load_specs, save_figure, study_paths, write_summary
from adam_common.spice import run_ngspice, trace

P = study_paths(__file__)
ADS = load_specs(P["inputs"] / "ads1220.csv")
CRIT = load_specs(P["inputs"] / "criteria.csv")
PARAMS = {"RBRDG": CRIT["r_bridge"]}


def ac_response():
    raw = run_ngspice(P["model"] / "ac.cir", P["results"], params=PARAMS)
    f = np.real(trace(raw, "frequency"))
    return f, trace(raw, "v(p)") - trace(raw, "v(n)")


def step_response():
    """Time after the step [s] and normalized differential output."""
    raw = run_ngspice(P["model"] / "step.cir", P["results"], params=PARAMS)
    t = np.real(trace(raw, "time")) - 100e-6
    v = np.real(trace(raw, "v(p)") - trace(raw, "v(n)"))
    return t, v / v[-1]


def crossing_time(t, y, level):
    """First time y reaches level (y rising)."""
    return t[np.argmax(y >= level)]


def group_delay(f, h):
    phase = np.unwrap(np.angle(h))
    return -np.gradient(phase, 2 * np.pi * f)


def plot(f, h, tau_g, t, y):
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(7, 9))
    gain_db = 20 * np.log10(np.abs(h) / np.abs(h[0]))
    ax1.semilogx(f, gain_db)
    ax1.axvline(ADS["f_mod_turbo"], ls="--", c="k", lw=0.8)
    ax1.text(ADS["f_mod_turbo"], -10, " f_mod (turbo)", fontsize=9)
    ax1.set_ylim(-80, 5)
    ax1.set_xlabel("Frequency [Hz]")
    ax1.set_ylabel("Gain rel. DC [dB]")
    ax2.semilogx(f, tau_g * 1e3)
    ax2.set_xlim(1, 1e5)
    ax2.set_xlabel("Frequency [Hz]")
    ax2.set_ylabel("Group delay [ms]")
    ax3.plot(t * 1e3, y)
    ax3.set_xlim(-0.2, 3)
    ax3.set_xlabel("Time after bridge step [ms]")
    ax3.set_ylabel("ADC input / final")
    save_figure(fig, P["figures"] / "loadcell_filter")


def main():
    apply_style()
    f, h = ac_response()
    rel_db = 20 * np.log10(np.abs(h) / np.abs(h[0]))
    corner = np.interp(3.0103, -rel_db, f)
    atten_fmod = -np.interp(np.log10(ADS["f_mod_turbo"]), np.log10(f), rel_db)
    tau_g = group_delay(f, h)
    t, y = step_response()
    plot(f, h, tau_g, t, y)

    rows = [
        check("DM corner", corner, "Hz"),
        check("Group delay at DC", tau_g[0] * 1e3, "ms"),
        check("Attenuation at turbo f_mod (512 kHz)", atten_fmod, "dB", min=50),
        check("Step: time to 50 %", crossing_time(t, y, 0.5) * 1e3, "ms"),
        check("Step: time to 90 %", crossing_time(t, y, 0.9) * 1e3, "ms"),
    ]
    if not write_summary(rows, P["results"] / "summary_sims.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
