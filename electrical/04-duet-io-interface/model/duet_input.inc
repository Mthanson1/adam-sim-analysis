* Duet IO.IN network as drawn on sheet 6: pull-up RPU from 3.3 V on the connector node,
* then 10k series into the Duet pin (~10 pF). RPU = 4.7k (opto input) or 27k (non-opto).
* Pins: ext = connector node, in = Duet pin.
.subckt duet_input ext in
Vpu pu 0 3.3
Rpu ext pu {RPU}
Rser ext in 10k
Cin in 0 10p
.ends duet_input
