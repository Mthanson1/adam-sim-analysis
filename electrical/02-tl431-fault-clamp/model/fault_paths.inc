* Every clamped input shorted to node `fault` (+24 V onto the connector pins), each through its
* series resistance into a BAV199 pair clamping to `rail` and GND.
* Prox CH0 (sheet 4/7): fault on the sensor output pin, divider, then Rs to the clamp node.
R13 fault s0 {R13}
R14 s0 0 {R14}
R25 s0 c0 {R25}
D12h c0 rail BAV199
D12l 0 c0 BAV199
* Prox CH1
R15 fault s1 {R15}
R16 s1 0 {R16}
R27 s1 c1 {R27}
D11h c1 rail BAV199
D11l 0 c1 BAV199
* UART TX (sheet 8): MCU pin left out (worst case for node voltage; see README).
R29 fault ctx {R29}
D13ah ctx rail BAV199
D13al 0 ctx BAV199
* UART RX: PA10 assumed 5 V-tolerant (no internal diode to VDD).
R31 fault crx {R31}
D13bh crx rail BAV199
D13bl 0 crx BAV199
