# SPICE models

Vendor device models shared by the electrical studies. `adam_common.spice.run_ngspice`
searches this folder for any `.include` / `.lib` file a netlist names without a path,
so netlists can write `.include bav199.lib`.

Each model is added in the PR of the first study that needs it, and gets a row here.
Most vendor models are PSpice syntax. `run_ngspice` runs ngspice with
`set ngbehavior=psa` (PSpice/LTspice compatibility) so they load unchanged.
**Encrypted models (common for newer TI parts) do not work in ngspice.** Use a
behavioral stand-in for those, and say so in the study README.

| File | Part | Vendor | Source | Downloaded | Notes |
|------|------|--------|--------|------------|-------|
| `rc_lowpass.cir` | (self-test) | n/a | n/a | n/a | Used by `selftest.py` |
| `tl431.lib` | TL431 (subckt `TL431 K A REF`) | Texas Instruments | [SLVM071B](https://www.ti.com/lit/zip/slvm071) (`TL431.lib` from the zip, unmodified apart from line endings) | 2026-11-24 | Unencrypted PSpice transient + AC model, TI "as is" terms in the file header |
| `bav199.lib` | BAV199 (model `BAV199`, one junction) | **fitted, not vendor** | Nexperia BAV199 datasheet max Vf points | 2026-11-24 | Nexperia's SPICE download blocks automated access; see the file header for the fit |

## Self-test

```powershell
python shared/spice_models/selftest.py
```

It simulates a 1 kΩ / 100 nF RC low-pass and checks the −3 dB corner against
1/(2πRC) to within 0.5 %. Run it after installing ngspice.
