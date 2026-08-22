# ldo comp data (generated, public-sources-only)

Generated 2026-08-20 from the upstream comp library's `ldo.md` entry by an internal, private-repo-only tool. This is a derived, filtered copy — regenerate rather than hand-edit. Every row below cites a public vendor datasheet or a public distributor pricing page; nothing internal survived extraction.

## Comparable parts

| Vendor | Part | Class | Output | Dropout | Iq | PSRR | Package | Price | Source |
|---|---|---|---|---|---|---|---|---|---|
| Texas Instruments | TLV70018 | Low-IQ LDO, 200 mA | 1.8 V fixed | 43 mV @ 50 mA (2.8 V variant, datasheet condition) | 31 µA typ | 68 dB @ 1 kHz | SC70-5 / SOT23-5 / SON-6 (1.5×1.5 mm) | $0.1924 (5+), $0.0956 (5000+) — TLV70018DBVR | Datasheet: [ti.com/lit/ds/symlink/tlv700.pdf](https://www.ti.com/lit/ds/symlink/tlv700.pdf) (SLVSA00E). Pricing: [LCSC C86185](https://www.lcsc.com/product-detail/Voltage-Regulators-Linear-Regulators-LDO_Texas-Instruments-TLV70018DBVR_C86185.html) |
| Texas Instruments | TPS7A02 | Nanopower LDO, 200 mA | 0.8–5.0 V in 50 mV steps (incl. 1.8 V) | 270 mV max @ 200 mA / 3.3 V (no 50 mA figure published; scales lower) | 25 nA typ, 3 nA shutdown | not separately headlined; < 10 µs / 100 mV undershoot on a 1–50 mA transient | X2SON 1.0×1.0 mm / SOT23-5 / DSBGA 0.64×0.64 mm | not fetched | Datasheet: [ti.com/lit/ds/symlink/tps7a02.pdf](https://www.ti.com/lit/ds/symlink/tps7a02.pdf) (SBVS277C) |
| Diodes Incorporated | AP7215 | 600 mA CMOS LDO | 3.3 V fixed only (no 1.8 V option in this family) | not numerically headlined ("very low") | 50 µA typ | not headlined | SOP-8L / SOT89-3L | not fetched | Datasheet: [diodes.com/assets/Datasheets/AP7215.pdf](https://www.diodes.com/assets/Datasheets/AP7215.pdf) |
| Diodes Incorporated | AP2210 | 300 mA RF ULDO | 2.5/2.8/3.0/3.3/3.6/4.0/5.0 V or ADJ (no 1.8 V standard option; ADJ covers it) | 250 mV typ @ 300 mA (no 50 mA figure published) | < 1 µA standby | 75 dB @ 100 Hz, 100 µA load | SOT23-3 / SOT23-5 | not fetched | Datasheet: [diodes.com/assets/Datasheets/AP2210.pdf](https://www.diodes.com/assets/Datasheets/AP2210.pdf) |

## Sources

| URL | Establishes | Fetched |
|---|---|---|
| https://www.ti.com/lit/ds/symlink/tlv700.pdf | TLV700 family dropout/Iq/PSRR/package | 2026-08-20 |
| https://www.lcsc.com/product-detail/Voltage-Regulators-Linear-Regulators-LDO_Texas-Instruments-TLV70018DBVR_C86185.html | TLV70018DBVR distributor pricing (LCSC C86185) | 2026-08-20 |
| https://www.ti.com/lit/ds/symlink/tps7a02.pdf | TPS7A02 nanopower Iq/dropout/output range | 2026-08-20 |
| https://www.diodes.com/assets/Datasheets/AP7215.pdf | AP7215 output/current/Iq | 2026-08-20 |
| https://www.diodes.com/assets/Datasheets/AP2210.pdf | AP2210 dropout/Iq/PSRR/package | 2026-08-20 |

