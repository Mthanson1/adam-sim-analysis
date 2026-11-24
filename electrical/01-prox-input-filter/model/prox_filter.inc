* Prox CH0 input chain: sensor divider -> Rs -> Ccm/Cdiff -> ADS1220 pins.
* Pins: vin = sensor output, gs = sensor return (board GND at the connector),
*       outp/outn = ADS1220 AINP/AINN. Node 0 is the ADC ground (AVSS).
* Values are board refdes params (shared/board/adam_cal_v2.csv).
* BAV199 clamps are left out: ~2 pF and nA leakage next to 10 nF; leakage is in error_budget.py.
.subckt prox_filter vin gs outp outn
Rtop vin sp {R13}
Rbot sp gs {R14}
Rsp sp outp {R25}
Rsn gs outn {R26}
Ccmp outp 0 {C28}
Ccmn outn 0 {C29}
Cdiff outp outn {C32}
* ADS1220 input pin with the PGA bypassed: a few pF, current handled in error_budget.py
Cinp outp 0 5p
Cinn outn 0 5p
.ends prox_filter
