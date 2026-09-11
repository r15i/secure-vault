# Strategy and Grading Optimization

To achieve the best possible grade while completing the project efficiently, you should focus on demonstrating engineering rigor, empirical data analysis, and a clear understanding of IoT constraints.

## 🚀 The Fastest Path to Completion

The current bottleneck in Phase 1 is **manual video syncing** (recording a USB power meter and matching it to logs). This is tedious, error-prone, and slow. 

**The shortcut actually taken (software timing, no hardware):**

> An earlier version of this section recommended an INA219 / INA226 I2C power sensor.
> That recommendation was **not followed** and is superseded — see
> `docs/Measurement_Strategy_and_Hardware.md`. An INA219 still cannot resolve a
> microsecond-scale operation, and to avoid perturbing the measurement it would need to
> monitor a second board.

1. **Time the crypto on-chip.** The firmware brackets every cryptographic phase with the
   microsecond clock and reports latency directly. No sensor, no wiring.
2. **Amortise to beat the clock.** `GET /api/benchmark?protocol=…&k=1000` runs K
   repetitions inside one timed region and divides — quantisation error drops three
   orders of magnitude below the differences being measured.
3. **Automate end to end.** `make benchmark` writes the dataset; `make analyze` renders
   the charts and the deviation report. No manual correlation anywhere.

## 🏆 How to Get the Best Grade Possible

Professors and evaluators look for **methodology, clear data presentation, and understanding of trade-offs**. Here is how to maximize your score:

### 1. Show, Don't Just Tell (Visual Evidence)
*   Include high-quality graphs comparing the energy spikes of **Classical vs. Secure Vault vs. ECC**.
*   Create a bar chart showing the total energy consumed over 1,000 cycles for each method. 
*   **Bonus:** Graph the time-to-authenticate (latency) alongside energy consumption.

### 2. Implement Deep Sleep / Power Saving (Phase 2)
*   IoT devices spend 99% of their time idle. Implementing **Modem Sleep** or **Light Sleep** between authentication cycles demonstrates a deep understanding of real-world IoT requirements.
*   Measure the baseline power consumption during sleep and compare it to the active authentication spikes.

### 3. Acknowledge Security vs. Energy Trade-offs
*   The paper reports Secure Vault at ~30% over basic AES. **Do not assert that as your
    result before measuring it** — on this chip AES and SHA are hardware-accelerated,
    which changes the balance, and the measured ratio may land well above 1.3x. Report
    what you measure and explain the difference.

*   **Write a strong conclusion:** Emphasize that while AES is the cheapest, Secure Vault prevents replay and side-channel attacks by rotating keys, making the 30% energy tax a highly worthwhile trade-off for critical infrastructure.

### 4. Pivot Phase 3 (Time-Saver)
*   Building a full Password Manager (Phase 3) is time-consuming and might distract from the core research. 
*   **Alternative:** Instead of a full password manager, build a simple **Python CLI** that acts as a "smart door lock" or "secure vault unlocker". As long as the ESP32 authenticates and the PC script outputs "Vault Unlocked", you have successfully proven the real-world application with 10% of the effort.

## Recommended Order of Execution
1. ~~Buy/use an INA219 sensor.~~ Superseded — the software timer reaches the required
   resolution with no hardware.
2. **Run the benchmark** (`make benchmark`) and generate the charts (`make analyze`).
3. **Implement Light Sleep** on the ESP32 and measure the idle baseline against the
   active spikes.
4. **Write the final report** around the charts and the trade-off analysis. Lead with the
   *ratios*, and explain the absolute divergence from the paper by naming its causes —
   the ESP32-C3's hardware AES/SHA and its lack of hardware ECC.
5. *(Optional)* Build the simple Python CLI proof-of-concept.
