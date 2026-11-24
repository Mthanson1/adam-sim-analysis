* +3V3 rail: behavioral TLV773 (sources only), minimum MCU/ADC load, TL431 clamp, rail capacitance.
* The including deck drives node ldo_set (LDO set-point) and defines params CRAIL (effective
* total rail capacitance), RESR and RLOAD. R7/R8 come from the parts table.
* LDO: 10 S transconductance toward the set-point, never sinks, 350 mA current limit (TLV773 min).
* It cannot sink, so fault current first feeds the load, then lifts the rail onto the TL431.
Bldo 0 rail I = min(0.35, max(0, 10 * (V(ldo_set) - V(rail))))
Rload rail 0 {RLOAD}
* 0 V source senses the TL431 cathode current, i(vk431).
Vk431 rail k431 0
XU3 k431 0 ref TL431
R7 rail ref {R7}
R8 ref 0 {R8}
Crail rail nesr {CRAIL}
Resr nesr 0 {RESR}
