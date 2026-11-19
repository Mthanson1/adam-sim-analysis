"""Post-process results for this study. Rename or replace as needed."""
import matplotlib.pyplot as plt
import numpy as np

from adam_common import apply_style, save_figure, study_paths

p = study_paths(__file__)
apply_style()

# Example only: replace with real data loaded from p["results"] or p["inputs"]
t = np.linspace(0, 1e-3, 500)
v = 5 * (1 - np.exp(-t / 1e-4))

fig, ax = plt.subplots()
ax.plot(t * 1e3, v)
ax.set_xlabel("Time [ms]")
ax.set_ylabel("Voltage [V]")
ax.set_title("Example")
save_figure(fig, p["figures"] / "example")
