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

## Self-test

```powershell
python shared/spice_models/selftest.py
```

It simulates a 1 kΩ / 100 nF RC low-pass and checks the −3 dB corner against
1/(2πRC) to within 0.5 %. Run it after installing ngspice.
