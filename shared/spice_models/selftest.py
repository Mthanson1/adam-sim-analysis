"""Check the ngspice install and adam_common.spice on an RC low-pass with a known corner."""
import sys

import numpy as np

from adam_common import REPO_ROOT
from adam_common.spice import find_ngspice, run_ngspice, trace

R, C = 1e3, 100e-9
TOLERANCE = 0.005

netlist = REPO_ROOT / "shared" / "spice_models" / "rc_lowpass.cir"
out_dir = REPO_ROOT / "shared" / "spice_models" / "results"

print(f"ngspice: {find_ngspice()}")
raw = run_ngspice(netlist, out_dir, params={"Rt": R, "Ct": C}, board=None)
f = np.real(trace(raw, "frequency"))
gain_db = 20 * np.log10(np.abs(trace(raw, "v(out)")))

f_sim = np.interp(10 * np.log10(2), -gain_db, f)  # attenuation rises monotonically
f_calc = 1 / (2 * np.pi * R * C)
error = f_sim / f_calc - 1
print(f"-3 dB corner: sim {f_sim:.1f} Hz, calc {f_calc:.1f} Hz, error {error:+.3%}")
if abs(error) > TOLERANCE:
    sys.exit("FAIL")
print("PASS")
