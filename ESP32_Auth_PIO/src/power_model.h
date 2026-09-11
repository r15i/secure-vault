// The dual power model.
//
// Energy is never measured directly. It is derived from measured latency using
// the reference paper's own method (Prasithsangaree et al., adopted in Gupta &
// Kumaraguru §VI-A): total energy = average current x supply voltage x
// execution time.
//
// Two constants are applied to the SAME measured latency, and every energy
// figure the device reports is labelled with which one produced it:
//
//   PAPER  — the reference platform's draw. Purpose: put this device's results
//            on the same axis as the paper's Table 1.
//   DEVICE — this board's active draw. Purpose: a physically plausible figure
//            for the hardware actually used.
//
// Both are tracked source, not local config: an ignored file would not survive
// a fresh clone, and neither value is a secret.
//
// NOTE: every RATIO in the analysis is invariant to both constants. Changing
// them moves absolute energies and nothing else.
#pragma once

// --- Paper-equivalent model ---------------------------------------------
// Gupta & Kumaraguru, TrustCom 2018, §VI-A: "Arduino uses 19.9 mA of average
// current when supplied with 5V voltage." 19.9 mA x 5 V = 99.5 mW.
#ifndef PAPER_POWER_MW
  #define PAPER_POWER_MW 99.5
#endif
#define PAPER_CURRENT_MA 19.9
#define PAPER_VOLTAGE_V  5.0
#define PAPER_POWER_SOURCE "Gupta & Kumaraguru, TrustCom 2018, section VI-A (19.9 mA @ 5 V)"

// --- Device-real model ---------------------------------------------------
// ESP32-C3 at 3.3 V, CPU active at 160 MHz with the radio associated but not
// transmitting -- the actual condition during a measured crypto phase.
// 25 mA x 3.3 V = 82.5 mW.
//
// Override at build time if you calibrate it:  -D DEVICE_POWER_MW=90.0
//
// Note: docs/Measurement_Strategy_and_Hardware.md previously asserted ~260 mW
// with no cited source. 260 mW at 3.3 V implies ~79 mA, which is closer to
// sustained radio activity than to CPU-bound crypto. See design.md Decision 6.
#ifndef DEVICE_POWER_MW
  #define DEVICE_POWER_MW 82.5
#endif
#define DEVICE_CURRENT_MA 25.0
#define DEVICE_VOLTAGE_V  3.3
#define DEVICE_POWER_SOURCE "ESP32-C3 datasheet, CPU active @160 MHz, WiFi associated (25 mA @ 3.3 V)"

// Microjoules -> watt-hours (1 Wh = 3.6e9 uJ).
constexpr double UJ_TO_WH = 1.0 / 3.6e9;

// The single energy conversion used by every figure the device reports:
//   E(uJ) = P(mW) x t(us) / 1000
// Reproducible by hand from any reported latency and power constant.
inline double energyUj(double power_mw, double latency_us) {
    return power_mw * latency_us / 1000.0;
}
