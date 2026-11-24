# 05: Reverse polarity and hot-plug

**Domain:** electrical
**Tool(s):** ngspice 47, Python 3.13
**Owner:** [@Mthanson1](https://github.com/Mthanson1)
**Status:** in progress

## Goal
Check the 24 V input stage (schematic sheet 2): J1 → F1 → SMAJ33CA → Q1 (SI2309CDS high-side
PMOS, R3 gate pull-down, ZD1 15 V gate clamp) → board +24 V.

1. **Reversed supply (sim 9):** −24 V plugged in. The supply's rise time is swept from 1 µs
   to 1 ms, because a fast edge couples through Q1's C_rss onto its gate.
   - board rail stays **≥ −0.3 V**
   - Q1 |V_GS| **≤ 20 V**
   - steady current limited to leakage
2. **Forward hot-plug:** +24 V plugged in, also swept over rise time.
   - inrush into C1 against Q1's pulsed rating, **I_DM 8 A**
   - Q1 drop and the gate clamp in steady state

## Setup
- Model files:
  - [`model/rev_pol.cir`](model/rev_pol.cir): the input stage, with a 480 Ω load and C1
    from the parts table.
  - [`model/input_devices.lib`](model/input_devices.lib): **fitted stand-ins, not vendor
    models.**
    - SI2309CDS: Level 1 fit to the Vishay datasheet. R_DS(on) is the 0.345 Ω max, and
      V_TO = −1.5 V, a low threshold that turns on most easily from capacitive coupling.
      Ciss 210 pF, Crss 20 pF.
    - SMAJ33CA: two series zeners at 36.7 V.
    - BZT52C15: a 15 V zener.
- F1 is a fixed 0.8 Ω (its initial resistance). PTC tripping is not modeled; it acts over
  seconds, far slower than these events.
- Criteria: [`inputs/criteria.csv`](inputs/criteria.csv).

## Assumptions
- The board draws 50 mA from +24 V.
- The supply is ideal, with a linear ramp. **There is no cable inductance and no supply output
  impedance.** Both would slow the edge and limit inrush, so the forward inrush numbers are an
  upper bound for each rise time.
- −0.3 V is used as a generic IC supply-pin minimum. Verify it against the LMR51606
  datasheet.
- I_DSS comes from the datasheet (1 µA max at 25 °C), because the Level 1 model has no
  leakage.

## How to reproduce
```powershell
python electrical/05-reverse-polarity/scripts/run_sims.py
```

## Results
![](results/figures/hot_plug.png)

| Reversed supply (−24 V) | 1 µs rise | 10 µs | 100 µs | 1 ms | Limit |
|---|---|---|---|---|---|
| Board rail minimum | −4.2 mV | −0.2 mV | ~0 | ~0 | ≥ −0.3 V **PASS** |
| Q1 \|V_GS\| peak | 1.96 V | 1.64 V | 0.47 V | 0.05 V | ≤ 20 V **PASS** |
| Supply current peak | 50 mA | 4.4 mA | 0.19 mA | 0.02 mA | info |
| Steady reverse current | ≤ 1 µA (Q1 I_DSS, datasheet) | | | | info |

A fast reversal couples about −2 V onto Q1's gate through C_rss. That is enough to turn it
partly on for roughly 20 µs (the R3·Ciss time constant). The 22 µF C1 absorbs the charge, so
the board rail only reaches −4 mV. **Q1 blocks the reversed supply.** In steady state the
board sees only the PMOS leakage.

| Forward hot-plug (+24 V) | 1 µs rise | 10 µs | 100 µs | 1 ms | Limit |
|---|---|---|---|---|---|
| Inrush peak | 28.1 A | 22.2 A | 5.3 A | 0.62 A | ≤ 8 A |
| | **FAIL** | **FAIL** | PASS | PASS | |

| Forward steady state | Result | Limit | |
|---|---|---|---|
| Q1 drop at 50 mA | 10.9 mV | n/a | info |
| Q1 \|V_GS\| (ZD1 clamped) | 14.9 V | ≤ 20 V | **PASS** |

With an ideal fast-rising supply, only F1's 0.8 Ω limits the inrush into C1, and the peak
exceeds Q1's 8 A pulsed rating. The current flows through Q1's body diode before the channel
turns on, so slowing the gate would not help. In a real plug-in, cable inductance and the
supply's own output impedance stretch the edge. The model leaves both out, so these peaks are
pessimistic. A ≥ 70 µs edge keeps the peak under 8 A.

## Conclusions
- **Reverse polarity protection works.** The board rail stays within millivolts of ground even
  for a 1 µs reversal, and steady leakage is ≤ 1 µA.
- Hot-plugging a stiff 24 V supply into the 22 µF C1 can exceed Q1's pulsed rating if the edge
  is faster than about 70 µs. Options:
  - Measure the real plug-in edge with the intended supply and cable.
  - Add inrush limiting, for example a small series resistance or NTC, or a higher-rated FET.
  - Reduce C1, if the TVS clamping allows it.
- Next step: model the cable inductance once the harness is known.
