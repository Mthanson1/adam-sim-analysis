"""Load cell contact detection: force resolution, trigger threshold and detection latency.

    python electrical/03-loadcell-contact-detect/scripts/contact_latency.py

Signal chain, in force units:
  contact force F(t) -> analog filter (SPICE step response, convolved) -> ADS1220 turbo
  2000 SPS -> threshold compare in firmware -> Z_DRV.
The ADS1220 filter settles in a single conversion, so each output is modeled as the plain
average of the input over its own conversion period (the real FIR weighting is not public;
a boxcar is the simplest model with the same one-cycle memory). The contact instant is
swept across one conversion period, because latency depends on where it lands.
Noise is treated as white and Gaussian, independent from sample to sample.
"""
import sys
from math import erfc, sqrt

import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import fftconvolve

from adam_common import apply_style, check, load_specs, save_figure, study_paths, write_summary
from adam_common.spice import run_ngspice, trace

P = study_paths(__file__)
ADS = load_specs(P["inputs"] / "ads1220.csv")
CRIT = load_specs(P["inputs"] / "criteria.csv")

DT = 1e-6
T_CONV = ADS["conv_clk_turbo_2000"] / ADS["f_clk"]
RAMP_RATES = (1.0, 10.0, 100.0)  # g/ms
STEP_FORCE = 50.0  # g, an effectively instant contact


def grams_per_volt():
    full_scale_v = CRIT["sens_mV_per_V"] * 1e-3 * CRIT["v_exc"]
    return CRIT["capacity_g"] / full_scale_v


def false_trigger_interval(k_sigma):
    """Mean time between noise-only threshold crossings (one-sided Gaussian), in hours."""
    p_sample = 0.5 * erfc(k_sigma / sqrt(2))
    return T_CONV / p_sample / 3600


def analog_step_response(n):
    """Normalized filter step response on the DT grid, length n."""
    raw = run_ngspice(P["model"] / "step.cir", P["results"], params={"RBRDG": CRIT["r_bridge"]})
    t = np.real(trace(raw, "time")) - 100e-6
    v = np.real(trace(raw, "v(p)") - trace(raw, "v(n)"))
    grid = np.arange(n) * DT
    return np.interp(grid, t, v / v[-1], left=0.0)


def force_profile(t, t0, rate):
    """Contact force in g: a ramp at `rate` g/ms from t0, or a STEP_FORCE step if rate is None."""
    if rate is None:
        return np.where(t >= t0, STEP_FORCE, 0.0)
    return np.clip((t - t0) * rate * 1e3, 0, None)


def detect(t, force, step_resp, threshold):
    """Analog-filtered force, ADC outputs (times, values) and the detection time (s)."""
    analog = fftconvolve(np.diff(force, prepend=0.0), step_resp)[: len(t)]
    per_conv = int(round(T_CONV / DT))
    n_conv = len(t) // per_conv
    adc = analog[: n_conv * per_conv].reshape(n_conv, per_conv).mean(axis=1)
    adc_t = (np.arange(n_conv) + 1) * per_conv * DT  # result is ready at the end of its window
    hit = np.nonzero(adc >= threshold)[0]
    t_detect = adc_t[hit[0]] + CRIT["t_firmware"] if hit.size else np.nan
    return analog, adc_t, adc, t_detect


def latency_sweep(rate, step_resp, threshold, t):
    """Latency for each contact phase within one conversion period."""
    phases = np.linspace(0, T_CONV, int(CRIT["n_phase"]), endpoint=False)
    t0s = 2 * T_CONV + phases
    return np.array([detect(t, force_profile(t, t0, rate), step_resp, threshold)[3] - t0
                     for t0 in t0s])


def plot_example(t, step_resp, threshold, rate=10.0):
    t0 = 2 * T_CONV + 0.3 * T_CONV
    force = force_profile(t, t0, rate)
    analog, adc_t, adc, t_det = detect(t, force, step_resp, threshold)
    fig, ax = plt.subplots()
    ms = 1e3
    ax.plot((t - t0) * ms, force, label="contact force")
    ax.plot((t - t0) * ms, analog, label="after analog filter")
    ax.step((adc_t - t0) * ms, adc, where="post", label="ADC output (2000 SPS)")
    ax.axhline(threshold, ls="--", c="r", lw=0.8, label=f"threshold {threshold:.2f} g")
    latency_ms = (t_det - t0) * ms
    ax.axvline(latency_ms, ls=":", c="k", lw=0.8, label=f"Z_DRV set: {latency_ms:.2f} ms")
    ax.set_xlim(-0.6, 3)
    ax.set_ylim(-0.5, 4 * threshold)
    ax.set_xlabel(f"Time after contact [ms] ({rate:g} g/ms ramp)")
    ax.set_ylabel("Force [g]")
    ax.legend(fontsize=9)
    save_figure(fig, P["figures"] / "contact_timeline")


def plot_latency(results):
    fig, ax = plt.subplots()
    labels = list(results)
    ax.boxplot([results[k] * 1e3 for k in labels], tick_labels=labels, whis=(0, 100))
    ax.set_xlabel("Contact force profile")
    ax.set_ylabel("Detection latency [ms]")
    save_figure(fig, P["figures"] / "contact_latency")


def main():
    apply_style()
    sigma_g = ADS["noise_rms_g128_t2000"] * grams_per_volt()
    threshold = CRIT["threshold_sigma"] * sigma_g

    # Long enough for the slowest ramp to reach threshold, plus filter and conversion delay.
    t_needed = threshold / (min(RAMP_RATES) * 1e3) + 8 * T_CONV
    t = np.arange(0, t_needed, DT)
    step_resp = analog_step_response(len(t))
    plot_example(t, step_resp, threshold)

    results = {f"{r:g} g/ms": latency_sweep(r, step_resp, threshold, t) for r in RAMP_RATES}
    results["step"] = latency_sweep(None, step_resp, threshold, t)
    plot_latency(results)

    rows = [
        check("Force noise (rms)", sigma_g, "g"),
        check("Force resolution (noise-free, pk-pk)", ADS["noise_pp_g128_t2000"] * grams_per_volt(),
              "g"),
        check("Trigger threshold", threshold, "g"),
        check("Mean time between false triggers", false_trigger_interval(CRIT["threshold_sigma"]),
              "h"),
        check("Conversion period", T_CONV * 1e3, "ms"),
    ]
    speed = CRIT["probe_speed"]
    for label, lat in results.items():
        rows += [
            check(f"Latency {label}, mean", lat.mean() * 1e3, "ms"),
            check(f"Latency {label}, max", lat.max() * 1e3, "ms"),
            check(f"Overtravel {label} at {speed:g} mm/s, max", lat.max() * speed * 1e3, "um",
                  max=CRIT["overtravel_max"] * 1e3),
        ]
    if not write_summary(rows, P["results"] / "summary_latency.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
