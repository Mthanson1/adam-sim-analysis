"""Prox channel DC error budget at full scale, converted to sensor distance.

    python electrical/01-prox-input-filter/scripts/error_budget.py

Two views:
  uncalibrated   every term at its datasheet/tolerance limit
  calibrated     after a two-point (offset + gain) calibration at one temperature, the
                 fixed parts of divider, reference, gain and offset errors are removed;
                 what is left is drift over `temp_span`, INL, noise and leakage.
Terms are combined both as a worst-case sum and RSS. ADC settings: normal mode, 20 SPS,
gain 1, PGA bypassed (required because AINN sits at AVSS).
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

P = study_paths(__file__)
ADS = load_specs(P["inputs"] / "ads1220.csv")
CRIT = load_specs(P["inputs"] / "criteria.csv")
PARTS = load_parts()

R_TOP, R_BOT = PARTS["R13"]["value"], PARTS["R14"]["value"]
TOL_TOP, TOL_BOT = PARTS["R13"]["tol_pct"] / 100, PARTS["R14"]["tol_pct"] / 100
RS = PARTS["R25"]["value"]
GAIN = R_BOT / (R_TOP + R_BOT)
R_TH = R_TOP * R_BOT / (R_TOP + R_BOT)
V_FS_ADC = CRIT["sensor_span_V"] * GAIN
V_PER_MM = CRIT["sensor_span_V"] / CRIT["sensor_range_mm"]


def to_mm(v_adc):
    return v_adc / GAIN / V_PER_MM


def leakage_error(i_leak):
    """Worst case: equal currents in opposite directions on the two legs."""
    return i_leak * (R_TH + RS) + i_leak * RS


def error_terms():
    """Error terms in volts at the ADC input: (name, uncalibrated, after calibration)."""
    dT = CRIT["temp_span"]
    divider_sens = 1 - GAIN  # dG/G per unit change in either resistor
    inl = ADS["inl"] * 2 * ADS["vref"]
    return [
        ("Divider ratio", divider_sens * (TOL_TOP + TOL_BOT) * V_FS_ADC,
         divider_sens * 2 * CRIT["resistor_tcr"] * dT * V_FS_ADC),
        ("Reference", ADS["vref_tol"] * V_FS_ADC, ADS["vref_drift"] * dT * V_FS_ADC),
        ("ADC gain", ADS["gain_err"] * V_FS_ADC, ADS["gain_drift"] * dT * V_FS_ADC),
        ("ADC offset", ADS["offset"], ADS["offset_drift"] * dT),
        ("ADC INL", inl, inl),
        ("ADC input current", leakage_error(ADS["i_abs"]), leakage_error(ADS["i_abs"])),
        ("Clamp leakage", leakage_error(CRIT["clamp_leak"]), leakage_error(CRIT["clamp_leak"])),
        ("Noise (pk-pk, 20 SPS)", ADS["noise_pp"], ADS["noise_pp"]),
    ]


def max_input_voltage():
    """Largest V_IN that stays inside the ADC range with worst-case divider and reference."""
    gain_max = R_BOT * (1 + TOL_BOT) / (R_TOP * (1 - TOL_TOP) + R_BOT * (1 + TOL_BOT))
    vref_min = ADS["vref"] * (1 - ADS["vref_tol"])
    return vref_min / gain_max


def plot_terms(terms):
    names = [t[0] for t in terms]
    uncal = np.array([to_mm(t[1]) for t in terms]) * 1e3
    cal = np.array([to_mm(t[2]) for t in terms]) * 1e3
    y = np.arange(len(names))
    fig, ax = plt.subplots()
    ax.barh(y + 0.2, uncal, height=0.4, label="uncalibrated")
    ax.barh(y - 0.2, cal, height=0.4, label=f"after 2-point cal, ±{CRIT['temp_span']:.0f} K")
    ax.set_yticks(y, names)
    ax.set_xscale("log")
    ax.set_xlabel("Error at full scale [µm of sensor distance]")
    ax.invert_yaxis()
    ax.legend()
    save_figure(fig, P["figures"] / "prox_error_budget")


def main():
    apply_style()
    terms = error_terms()
    plot_terms(terms)

    uncal = np.array([t[1] for t in terms])
    cal = np.array([t[2] for t in terms])
    rows = [check(f"{name}, uncalibrated", to_mm(u) * 1e3, "um") for name, u, _ in terms]
    rows += [check(f"{name}, after cal", to_mm(c) * 1e3, "um") for name, _, c in terms]
    rows += [
        check("Total uncalibrated, worst case", to_mm(uncal.sum()) * 1e3, "um"),
        check("Total uncalibrated, RSS", to_mm(np.sqrt((uncal**2).sum())) * 1e3, "um"),
        check("Total after cal, worst case", to_mm(cal.sum()) * 1e3, "um",
              max=CRIT["cal_error_max_mm"] * 1e3),
        check("Total after cal, RSS", to_mm(np.sqrt((cal**2).sum())) * 1e3, "um"),
        check("Max V_IN inside ADC range (worst case)", max_input_voltage(), "V",
              min=CRIT["sensor_span_V"]),
    ]
    if not write_summary(rows, P["results"] / "summary_error_budget.csv"):
        sys.exit(1)


if __name__ == "__main__":
    main()
