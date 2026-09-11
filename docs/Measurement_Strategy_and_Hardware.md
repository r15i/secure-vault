# Measurement Strategy: Software Timing vs. Hardware Meters

## Hardware Measurement Considerations (UM24C, UM25C, INA219)
Initially, external hardware measurement tools were considered for benchmarking the energy consumption of the ESP32-C3 during authentication cycles.

*   **USB Power Meters (UM24C / UM25C)**: These devices sit inline with the USB connection. While easy to use, their sampling rate is extremely low (1-2 Hz). Cryptographic operations (AES, ECC) execute in microseconds or milliseconds. A USB meter cannot capture these microsecond-level power spikes; it only measures the average power of the entire development board over a long period. Therefore, they are entirely unsuitable for profiling fast authentication protocols.
*   **INA219 / INA226 Modules**: These are dedicated I2C power monitoring sensors. While they offer much higher precision and sampling rates than USB meters, they require physical wiring and additional code complexity.

## Chosen Approach: Software Timing (`micros()`)
Instead of external hardware, we are adopting a pure software-based timing approach. This is a standard and well-accepted method in academic literature for embedded systems.

### Methodology
1.  **Latency Measurement**: The firmware times every cryptographic phase with the
    chip's microsecond clock (`esp_timer_get_time()`, which is what Arduino's
    `micros()` reads — the 64-bit value is used directly so the ~71.6-minute
    `uint32_t` wraparound cannot corrupt a long run).
2.  **Resolution**: A single AES-128 block on this chip's hardware accelerator costs
    single-digit microseconds, so timing one operation at ~1 µs granularity would
    carry 10–30% quantisation error — enough to swallow the ~1.3x Secure-Vault-over-
    Classical difference the project exists to measure. The primary figure therefore
    comes from an **amortised batch**: K repetitions inside one timed region, divided
    by K (`GET /api/benchmark?protocol=…&k=…`). Per-cycle single-shot timings are also
    recorded and must agree with the batch figure within dispersion, or the run fails.
3.  **Paper Alignment (`K=100`/`K=3`)**: The hardware AES on the ESP32-C3 executes symmetric cryptographic blocks more than 100x faster than the 8-bit Arduino referenced in the paper. To rigorously compare equivalent execution windows, the `benchmark-paper-time` harness job executes batches where `K=100` for symmetric (Classical/SV) and `K=3` for ECC. This perfectly aligns the total absolute wall-clock time spent in the ESP32's batch operation with the execution time of *just one single operation* on the paper's original platform.
4.  **Energy Estimation**: `Energy = Power × Time`, the reference paper's own method
    (Prasithsangaree et al., adopted in its section VI-A). Applied at **two** declared
    power constants, with every reported figure labelled by which one produced it:

| Model | Constant | Basis | Purpose |
| :--- | :--- | :--- | :--- |
| **Paper-equivalent** | **99.5 mW** | 19.9 mA @ 5 V — the paper's Arduino, its section VI-A | Puts our results on the same axis as its Table 1 |
| **Device-real** | **82.5 mW** | 25 mA @ 3.3 V — ESP32-C3, CPU active @160 MHz, radio associated but not transmitting | A physically plausible figure for the board actually used |

Both are defined once, in `ESP32_Auth_PIO/src/power_model.h`, and are emitted with
every telemetry response so no figure is ever separated from its assumption.

> **Correction.** An earlier version of this document asserted "~260mW during active
> processing" with no cited source. At 3.3 V that implies ~79 mA, which is closer to
> sustained radio activity than to CPU-bound crypto with the radio idle. It has been
> replaced by the sourced 82.5 mW above. Note that **every ratio in the analysis is
> invariant to this constant** — changing it moves absolute energies and nothing else,
> which is precisely why the ratios are the load-bearing claim.

### Advantages
- **Zero Cost & No Hardware**: No external sensors to buy, wire, or ship.
- **Sufficient Precision**: Amortised batch timing drives quantisation error three
  orders of magnitude below the differences being resolved.
- **Validity**: It is the reference paper's own estimation method, applied identically —
  which is what makes the comparison meaningful across two very different platforms.

### Limitations, stated plainly
- Energy is **modelled, not measured.** Constant-power × time ignores that current
  draw varies with instruction mix — a hardware-accelerated AES block and a software
  big-integer multiply do not draw the same current, and this model cannot see that.
- **Radio and transport energy are excluded** entirely. Cryptographic time is recorded
  separately from handler time so protocol cost is not confounded with WiFi.
- Absolute energies will diverge from the paper by orders of magnitude. This is
  expected, is reported explicitly, and is why ratios carry the argument.
