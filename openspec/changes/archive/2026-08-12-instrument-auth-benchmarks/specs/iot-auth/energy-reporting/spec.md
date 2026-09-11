## Purpose

Turns measured cryptographic latency into energy figures using the reference paper's own estimation method, reported simultaneously under two explicitly declared power constants so that results are both directly comparable to the paper's published table and honest about what this board consumes.

## ADDED Requirements

### Requirement: Energy is derived from measured latency

Energy SHALL be computed as the product of a declared constant power draw and a measured execution time, following the estimation method the reference paper adopts (total energy = average current × supply voltage × execution time). Energy MUST NOT be accumulated from per-cycle literature constants.

The conversion SHALL be `energy_uJ = power_mW × latency_us / 1000`.

#### Scenario: Energy tracks measured time

- **WHEN** a protocol's measured mean crypto latency changes between two runs
- **THEN** the reported energy for that protocol changes proportionally
- **AND** the ratio of reported energy to measured latency equals the declared power constant

#### Scenario: Conversion is reproducible by hand

- **WHEN** a reader takes any reported latency and the reported power constant
- **THEN** applying the documented formula reproduces the reported energy figure to within display rounding

### Requirement: Dual power model

Every energy figure SHALL be reported twice, once under each of two power models, and each figure SHALL be labelled with the model it belongs to. A single unlabelled energy number is not acceptable output.

The two models are:

- **Paper-equivalent model** — the reference paper's platform draw of 19.9 mA at 5 V, i.e. **99.5 mW**. Its purpose is direct comparability with the paper's published energy table.
- **Device-real model** — a documented active-power constant for the ESP32-C3 under the benchmark's operating conditions. Its purpose is a physically plausible figure for the hardware actually used.

#### Scenario: Both models reported per protocol

- **WHEN** energy results are requested for any protocol
- **THEN** a per-cycle energy value is reported under the paper-equivalent model
- **AND** a per-cycle energy value is reported under the device-real model
- **AND** each value states which model produced it

#### Scenario: Models differ only by the constant

- **WHEN** both energy values for one protocol are compared
- **THEN** their ratio equals the ratio of the two power constants
- **AND** the underlying latency is identical for both

### Requirement: Power constants are declared, not implicit

Both power constants SHALL be visible in the reported output and traceable to a stated source. The device and the analysis output SHALL agree on the constants used.

Each declared constant SHALL carry: its value, its unit, the current and voltage it derives from where applicable, and its provenance (reference paper section, or datasheet/measurement basis for the device constant).

#### Scenario: Constants accompany the results

- **WHEN** energy results are retrieved from the device or read from generated output
- **THEN** the two power constants and their provenance are present in that same output
- **AND** a reader can identify which constant produced which figure without inspecting source code

#### Scenario: Constant is changed

- **WHEN** a power constant is changed and the benchmark is re-run
- **THEN** all energy figures under that model change accordingly
- **AND** the newly reported constant reflects the new value

### Requirement: Energy telemetry API

The device SHALL expose accumulated and per-cycle energy through its JSON telemetry interface, for all three protocols, under both power models, alongside the latency statistics the figures derive from.

For each protocol the response SHALL include: successful cycle count, measured latency statistics, per-cycle energy under each model, and accumulated total energy under each model. Totals SHALL be reported in microjoules, and MAY additionally be reported in watt-hours for continuity with prior reporting.

#### Scenario: Telemetry returns dual-model energy

- **WHEN** a client requests energy telemetry
- **THEN** the response contains, for each of Secure Vault, Classical, and ECC, the cycle count, latency statistics, per-cycle energy under both models, and accumulated energy under both models

#### Scenario: Accumulated total is consistent with the cycles

- **WHEN** accumulated energy is compared against the reported cycle count and mean per-cycle energy for the same protocol
- **THEN** the accumulated total equals count × mean per-cycle energy to within display rounding

#### Scenario: Telemetry before any cycles

- **WHEN** energy telemetry is requested with no cycles recorded
- **THEN** counts and accumulated energy are reported as zero
- **AND** the power constants are still reported

### Requirement: Dashboard presents both models

The device's web dashboard SHALL present the dual-model energy figures and the measured latency for each protocol, and SHALL NOT present a single energy figure whose power model is unstated.

#### Scenario: Dashboard shows labelled figures

- **WHEN** the dashboard is loaded and cycles have been recorded
- **THEN** it displays, per protocol, the measured mean latency and the energy under both power models, each labelled with its model
