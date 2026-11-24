"""Prox channel DC error budget along the sensor curve, converted to target distance.

    python electrical/01-prox-input-filter/scripts/error_budget.py

Error terms are computed in volts at the ADC input. Terms that scale with the signal
(divider ratio, reference, ADC gain) are evaluated at the sensor voltage for each distance;
the rest (offset, INL, input current, leakage, noise) are constant. Dividing by the local
slope of the sensor curve gives the distance error, so accuracy is best where the curve is
steepest and falls apart where it flattens into saturation.

Two views:
  uncalibrated   every term at its tolerance limit
  calibrated     after a two-point (offset + gain) calibration at one temperature: only
                 drift over `temp_span`, INL, noise and leakage remain
Both use a worst-case sum. Two divider options: standard 1 % thick film and 0.1 % precision.

Sensor curve: Steel FE360 (the standard rating target) digitized by eye from the
DW-AS-509-M12-309 typical curves (inputs/prox_sensor_curve.csv, ~0.1 V reading accuracy),
scaled from the plot's 5.78 V saturation to the 10.35 V measured on the real sensor.
ADC settings: normal mode, 20 SPS, gain 1, PGA bypassed (AINN sits at AVSS).
"""
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import PchipInterpolator

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
ADS = load_specs(P["inputs"] / "ads1220.csv")
CRIT = load_specs(P["inputs"] / "criteria.csv")
PARTS = load_parts()

R_TOP, R_BOT = PARTS["R13"]["value"], PARTS["R14"]["value"]
RS = PARTS["R25"]["value"]
GAIN = R_BOT / (R_TOP + R_BOT)
R_TH = R_TOP * R_BOT / (R_TOP + R_BOT)
DIVIDER_SENS = 1 - GAIN  # dG/G per unit relative change of either resistor
OPTIONS = {
    "1 % thick film": (PARTS["R13"]["tol_pct"] / 100, CRIT["resistor_tcr"]),
    "0.1 % thin film": (CRIT["resistor_tol_precision"] / 100, CRIT["resistor_tcr_precision"]),
}


def sensor_curve():
    """Sensor output [V] and slope [V/mm] as functions of distance [mm], scaled to the real unit."""
    d, v = np.loadtxt(P["inputs"] / "prox_sensor_curve.csv", delimiter=",", skiprows=1,
                      unpack=True)
    scale = CRIT["sensor_span_V"] / CRIT["sensor_sat_datasheet"]
    curve = PchipInterpolator(d, v * scale)
    return curve, curve.derivative()


def leakage_error(i_leak):
    """Worst case: equal currents in opposite directions on the two legs."""
    return i_leak * (R_TH + RS) + i_leak * RS


def error_terms(tol, tcr):
    """(name, kind, uncalibrated, calibrated) in volts at the ADC at full scale.

    kind "prop" terms scale with the signal; "const" terms do not.
    """
    dT = CRIT["temp_span"]
    v_fs = CRIT["sensor_span_V"] * GAIN
    inl = ADS["inl"] * 2 * ADS["vref"]
    return [
        ("Divider ratio", "prop", DIVIDER_SENS * 2 * tol * v_fs,
         DIVIDER_SENS * 2 * tcr * dT * v_fs),
        ("Reference", "prop", ADS["vref_tol"] * v_fs, ADS["vref_drift"] * dT * v_fs),
        ("ADC gain", "prop", ADS["gain_err"] * v_fs, ADS["gain_drift"] * dT * v_fs),
        ("ADC offset", "const", ADS["offset"], ADS["offset_drift"] * dT),
        ("ADC INL", "const", inl, inl),
        ("ADC input current", "const", leakage_error(ADS["i_abs"]), leakage_error(ADS["i_abs"])),
        ("Clamp leakage", "const", leakage_error(CRIT["clamp_leak"]),
         leakage_error(CRIT["clamp_leak"])),
        ("Noise (pk-pk, 20 SPS)", "const", ADS["noise_pp"], ADS["noise_pp"]),
    ]


def error_mm(terms, column, v_sensor, slope):
    """Worst-case distance error [mm] at each point of the curve. column: 2 = uncal, 3 = cal."""
    frac = v_sensor / CRIT["sensor_span_V"]
    v_err = sum(t[column] * (frac if t[1] == "prop" else 1) for t in terms)
    return v_err / GAIN / slope


def usable_range(d, err):
    """First and last distance where the error meets the requirement."""
    ok = d[err <= CRIT["cal_error_max_mm"]]
    return (ok.min(), ok.max()) if ok.size else (np.nan, np.nan)


def max_input_voltage(tol):
    """Largest V_IN that stays inside the ADC range with worst-case divider and reference."""
    gain_max = R_BOT * (1 + tol) / (R_TOP * (1 - tol) + R_BOT * (1 + tol))
    return ADS["vref"] * (1 - ADS["vref_tol"]) / gain_max


def plot_curve_errors(d, v_sensor, errors):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7, 7), sharex=True)
    ax1.plot(d, v_sensor)
    ax1.axhspan(CRIT["measured_dip_V"], CRIT["sensor_span_V"], alpha=0.15,
                label="measured sweep range")
    ax1.legend(fontsize=9)
    ax1.set_ylabel("Sensor output [V]\n(FE360, scaled to measured)")
    for label, err in errors.items():
        ax2.semilogy(d, err * 1e3, label=label)
    ax2.axhline(CRIT["cal_error_max_mm"] * 1e3, ls="--", c="r", lw=0.8, label="5 µm requirement")
    ax2.set_ylim(0.5, 500)
    ax2.set_xlabel("Target distance [mm]")
    ax2.set_ylabel("Worst-case error [µm]")
    ax2.legend(fontsize=9)
    save_figure(fig, P["figures"] / "prox_error_vs_distance")


def plot_terms(terms, slope_max):
    names = [t[0] for t in terms]
    to_um = 1e3 / GAIN / slope_max
    y = np.arange(len(names))
    fig, ax = plt.subplots()
    ax.barh(y + 0.2, [t[2] * to_um for t in terms], height=0.4, label="uncalibrated")
    ax.barh(y - 0.2, [t[3] * to_um for t in terms], height=0.4,
            label=f"after 2-point cal, ±{CRIT['temp_span']:.0f} K")
    ax.set_yticks(y, names)
    ax.set_xscale("log")
    ax.set_xlabel("Error at full-scale terms, steepest point of the curve [µm]")
    ax.invert_yaxis()
    ax.legend()
    save_figure(fig, P["figures"] / "prox_error_budget")


def main():
    apply_style()
    curve, slope_fn = sensor_curve()
    d = np.linspace(0.05, 6.0, 600)
    v_sensor, slope = curve(d), slope_fn(d)
    i_steep = int(np.argmax(slope))
    i_dip = int(np.argmin(np.abs(v_sensor - CRIT["measured_dip_V"])))

    errors, rows = {}, []
    for label, (tol, tcr) in OPTIONS.items():
        terms = error_terms(tol, tcr)
        cal = error_mm(terms, 3, v_sensor, slope)
        errors[f"after cal, {label}"] = cal
        lo, hi = usable_range(d, cal)
        rows += [
            check(f"Uncal error at steepest point, {label}",
                  error_mm(terms, 2, v_sensor, slope)[i_steep] * 1e3, "um"),
            check(f"Cal error at steepest point, {label}", cal[i_steep] * 1e3, "um",
                  max=CRIT["cal_error_max_mm"] * 1e3),
            check(f"Cal error at measured dip ({CRIT['measured_dip_V']:g} V), {label}",
                  cal[i_dip] * 1e3, "um", max=CRIT["cal_error_max_mm"] * 1e3),
            check(f"Distance range meeting 5 um, {label}: from", lo, "mm"),
            check(f"Distance range meeting 5 um, {label}: to", hi, "mm"),
            check(f"Max V_IN inside ADC range, {label}", max_input_voltage(tol), "V",
                  min=CRIT["sensor_span_V"]),
        ]
        if label.startswith("1 %"):
            plot_terms(terms, slope[i_steep])
    plot_curve_errors(d, v_sensor, errors)

    rows = [
        check("Steepest sensor slope (scaled FE360 curve)", slope[i_steep], "V/mm"),
        check("Distance at steepest slope", d[i_steep], "mm"),
        check("Distance at measured dip (scaled curve)", d[i_dip], "mm"),
        check("Slope at measured dip", slope[i_dip], "V/mm"),
        *rows,
    ]
    if not write_summary(rows, P["results"] / "summary_error_budget.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
