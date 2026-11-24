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
| `bav199_nexperia.lib` | BAV199 (model `BAV199`, one junction of the double diode) | Nexperia | supplied by the team from nexperia.com/product/BAV199 | 2026-11-24 | One edit: a stray `.ENDS` with no `.SUBCKT` is commented out (ngspice rejects it) |
| `2n7002_onsemi.lib` | 2N7002 (subckt `F2N7002`, pins D G S) | onsemi | supplied by the team (onsemi 2N7002 BSIM3 model, Rev 1.0, Jul 2022) | 2026-11-24 | Unmodified. ngspice warns that BSIM3 v3.1 is run as v3.2.x; results match the datasheet R_DS(on) |
| `si2309cds_vishay.lib` | Si2309CDS (subckt `Si2309CDS`, pins D G S) | Vishay | supplied by the team (Si2309CDS_PS, ECN S14-1400 Rev. B) | 2026-11-24 | Unmodified. The PSpice `_PS` variant; the `_PS_RC` thermal variant is not used |
| `nmos_2n7002.lib` | 2N7002 worst case (subckt `N2N7002_WORST`; `N2N7002` typ fit kept for reference) | **fitted, not vendor** | onsemi 2N7000/2N7002/NDS7002A datasheet | 2026-11-24 | The vendor model is typical-only; this Level 1 fit covers the datasheet's worst-case V_GS(th) 2.5 V and R_DS(on) 7.5 Ω |

## Self-test

```powershell
python shared/spice_models/selftest.py
```

It simulates a 1 kΩ / 100 nF RC low-pass and checks the −3 dB corner against
1/(2πRC) to within 0.5 %. Run it after installing ngspice.
