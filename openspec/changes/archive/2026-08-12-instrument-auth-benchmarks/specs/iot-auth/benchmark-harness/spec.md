## Purpose

Provides a repeatable, automated way to run the three authentication protocols at scale, collect their measured results into machine-readable form, render the comparison charts the report depends on, and evaluate those results against the reference paper's published figures so that any divergence is explained rather than hidden.

## ADDED Requirements

### Requirement: Single-command benchmark run

A complete benchmark SHALL be executable with one command that requires no manual instrumentation, no video recording, and no wiring of external measurement hardware. The command SHALL reset accumulated statistics, execute a configurable number of cycles for each protocol, collect results, and produce all output artifacts.

#### Scenario: One command produces all artifacts

- **WHEN** the benchmark command is run against a reachable device
- **THEN** it resets prior statistics, exercises all three protocols, and writes the result dataset and the comparison charts
- **AND** it reports where each artifact was written

#### Scenario: Cycle count is configurable

- **WHEN** the operator specifies a number of cycles per protocol
- **THEN** exactly that many successful cycles per protocol are attempted and recorded, or the run terminates with a stated reason

#### Scenario: Device unreachable

- **WHEN** the device does not respond
- **THEN** the run fails with a message naming the address it attempted
- **AND** no partial or empty result dataset is presented as a completed benchmark

### Requirement: On-device batch execution for throughput

To keep runs fast and to keep WiFi latency out of the measured quantity, the device SHALL support executing a requested number of repetitions of a protocol's cryptographic work internally, in one request, returning the accumulated statistics for that batch.

The batch path SHALL exercise the same cryptographic operations, on the same key material, as the corresponding network-driven authentication path, so that batch results are representative of real cycles.

#### Scenario: Batch request returns statistics

- **WHEN** a batch of N repetitions of a protocol is requested
- **THEN** the device executes N repetitions of that protocol's cryptographic work and returns the resulting latency statistics
- **AND** the reported sample count equals N

#### Scenario: Batch is equivalent to individual cycles

- **WHEN** batch-derived mean crypto latency is compared with the mean crypto latency of individually requested cycles of the same protocol
- **THEN** the two agree within the reported dispersion of the measurements
- **AND** any systematic difference is reported rather than silently accepted

#### Scenario: Oversized batch is bounded

- **WHEN** a batch size is requested that would exceed the device's request-handling time budget
- **THEN** the device either rejects the request with a stated maximum or subdivides the work without exceeding that budget

### Requirement: Machine-readable result dataset

Benchmark results SHALL be written to a machine-readable dataset suitable for direct analysis, containing one row per measured series with all fields needed to reproduce the reported figures without re-reading the device.

Each row SHALL carry: protocol, phase or aggregate label, sample count, min, max, mean, median, and standard deviation latency in microseconds, per-cycle energy under each power model, the power constant used for each model, and a run identifier.

#### Scenario: Dataset is self-describing

- **WHEN** the result dataset is opened without access to the device
- **THEN** every reported energy figure can be recomputed from the latency and power constant columns in that same dataset

#### Scenario: Runs are distinguishable

- **WHEN** two benchmark runs are recorded
- **THEN** their rows are distinguishable by run identifier
- **AND** neither run's data overwrites or is conflated with the other's

#### Scenario: Failures are recorded

- **WHEN** cycles fail during a run
- **THEN** the dataset records the count of failed cycles per protocol
- **AND** failed cycles are excluded from the success-only latency statistics

### Requirement: Comparison charts

The harness SHALL generate comparison charts from the result dataset, without manual editing, covering at minimum:

- Per-cycle energy by protocol, shown under both power models.
- Measured latency by protocol, with the phase breakdown visible.
- Measured cost ratios between protocols alongside the reference paper's ratios.

Charts SHALL be legible on a logarithmic scale where the ECC magnitude would otherwise flatten the symmetric protocols to invisibility, and every axis SHALL state its unit.

#### Scenario: Charts are generated from the dataset

- **WHEN** chart generation is run against a result dataset
- **THEN** the required charts are written as image files
- **AND** each is derived solely from that dataset

#### Scenario: ECC magnitude does not hide symmetric results

- **WHEN** ECC and the symmetric protocols appear on the same axis
- **THEN** the symmetric protocols' values remain readable
- **AND** the scale used is stated on the chart

### Requirement: Paper-ratio comparison

The harness SHALL evaluate measured results against the reference paper's published figures on a ratio basis, and SHALL present both sets side by side. The comparison SHALL treat ratios, not absolute energies, as the claim being tested.

The reference figures SHALL be recorded with their source, and are: Classical AES-128 authentication 497.5 µJ, Secure Vault 646.75 µJ, and ECC 109,950 µJ, at the paper's platform draw of 99.5 mW — giving reference ratios of Secure Vault to Classical ≈ 1.30, ECC to Secure Vault ≈ 170, and ECC to Classical ≈ 221.

#### Scenario: Ratios are tabulated against the paper

- **WHEN** the comparison output is produced
- **THEN** it presents the measured Secure-Vault-to-Classical, ECC-to-Secure-Vault, and ECC-to-Classical ratios next to the paper's corresponding ratios
- **AND** the deviation for each is stated

#### Scenario: Ratio conclusions are model-independent

- **WHEN** a measured ratio is computed
- **THEN** it is identical under both power models
- **AND** the output states that ratios are invariant to the choice of power constant

#### Scenario: Absolute divergence is expected and stated

- **WHEN** measured absolute per-cycle energy is compared with the paper's
- **THEN** the output presents the divergence explicitly rather than omitting it
- **AND** does not claim absolute agreement with the paper

### Requirement: Deviation analysis

The harness output SHALL include a written analysis accounting for divergence between measured results and the reference paper's, attributing each divergence to a named cause on the measurement platform rather than leaving it unexplained.

The analysis SHALL address at minimum: the difference in processor and clock speed between the platforms, the presence of a hardware AES accelerator on the measurement device, the difference in supply voltage and current draw underlying the two power constants, the exclusion of radio and transport energy from the modelled figure, and any measured ratio that diverges materially from the paper's.

#### Scenario: Each divergence has an attributed cause

- **WHEN** a measured ratio differs materially from the paper's corresponding ratio
- **THEN** the analysis names a specific platform or methodological cause for that difference

#### Scenario: Modelling limits are disclosed

- **WHEN** the analysis is read
- **THEN** it states that energy is modelled from latency under a constant-power assumption rather than measured with a power meter
- **AND** it states what that assumption excludes

### Requirement: Reproducibility of reported results

Every figure that appears in the project's written analysis SHALL be traceable to a generated artifact of a specific benchmark run. Hand-entered results are not acceptable.

#### Scenario: Reported figures trace to a run

- **WHEN** a figure in the project documentation is checked
- **THEN** it is present in, or directly computed from, a generated result artifact identifying the run that produced it

#### Scenario: Re-running reproduces results within dispersion

- **WHEN** the benchmark is run twice under the same conditions and configuration
- **THEN** the mean per-protocol latencies agree within the reported standard deviations
- **AND** the measured ratios agree to the precision reported
