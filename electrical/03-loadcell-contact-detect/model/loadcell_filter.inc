* Load cell input chain (sheet 3): bridge -> 1k Rs -> Ccm/Cdiff -> ADS1220 AIN1/AIN2.
* The bridge is modeled as its differential output split +/- around mid-supply, each leg with
* half the bridge output resistance (RBRDG is the differential output resistance).
* Pins: vd = differential bridge signal (V), outp/outn = ADS1220 inputs.
.subckt loadcell_filter vd outp outn
Vcm cm 0 2.5
Ep bp cm vd 0 0.5
En bn cm vd 0 -0.5
Rbp bp sp {RBRDG/2}
Rbn bn sn {RBRDG/2}
R10 sp outp {R10}
R11 sn outn {R11}
C10 outp 0 {C10}
C11 outn 0 {C11}
C12 outp outn {C12}
* ADS1220 inputs with the PGA enabled: a few pF
Cinp outp 0 5p
Cinn outn 0 5p
.ends loadcell_filter
