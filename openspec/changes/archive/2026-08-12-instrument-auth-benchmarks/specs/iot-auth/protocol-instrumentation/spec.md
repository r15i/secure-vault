## Purpose

Provides trustworthy, microsecond-resolution measurement of how long each cryptographic phase of the device's authentication protocols actually takes on the device itself, isolated from network and parsing overhead, so that protocol cost comparisons rest on measured data rather than borrowed literature values.

## ADDED Requirements

### Requirement: Measured cryptographic latency

The device SHALL measure the execution time of every cryptographic phase of every authentication protocol using an on-device monotonic microsecond clock, and SHALL report those measurements. The device MUST NOT report any latency or energy figure that was not derived from a measurement taken on that device during that run.

Instrumented phases SHALL include, at minimum:

- Secure Vault: vault key derivation (multi-key XOR), AES-128 decryption of the client message, AES-128 encryption of the device response, HMAC-SHA256 computation, and vault rotation.
- Classical: AES-128 decryption of the challenge response.
- ECC: signature generation, and any key or nonce preparation performed per cycle.

#### Scenario: Latency is measured per phase

- **WHEN** a Secure Vault authentication cycle completes successfully
- **THEN** the device reports a distinct microsecond duration for each instrumented phase of that cycle
- **AND** each reported duration is greater than zero

#### Scenario: No hardcoded protocol cost

- **WHEN** any authentication cycle completes
- **THEN** the reported latency and energy for that cycle are computed from the clock readings taken during that cycle
- **AND** no literature-derived per-cycle cost constant contributes to the reported figures

#### Scenario: Timing survives a failed authentication

- **WHEN** an authentication cycle fails verification after cryptographic work was performed
- **THEN** the phases that did execute are still reported as measured
- **AND** the cycle is recorded as failed and excluded from success-only statistics

### Requirement: Separation of cryptographic time from transport time

The device SHALL report cryptographic time separately from transport and serialization time, so that protocol cost is attributable and not dominated by WiFi and HTTP overhead.

For each request the device SHALL report:

- **crypto time** — the summed duration of the instrumented cryptographic phases.
- **handler time** — the total time spent inside the request handler, including hex decoding, argument parsing, and response construction.

#### Scenario: Both timing scopes are reported

- **WHEN** a client completes an authentication request
- **THEN** the device reports a crypto time and a handler time for that request
- **AND** the crypto time is less than or equal to the handler time

#### Scenario: Transport time is not attributed to the protocol

- **WHEN** benchmark results are produced
- **THEN** the per-protocol cost figures used for comparison are derived from crypto time only
- **AND** any wall-clock round-trip time observed by the client is reported as a separate, clearly labelled quantity

### Requirement: Per-operation statistical accumulation

The device SHALL accumulate statistics per protocol and per instrumented phase across repeated cycles, and SHALL expose them. For each accumulated series the device SHALL report sample count, minimum, maximum, arithmetic mean, median, and standard deviation, all in microseconds.

#### Scenario: Statistics reported over many cycles

- **WHEN** at least 30 successful cycles of a protocol have been executed
- **THEN** the device reports count, min, max, mean, median, and standard deviation for that protocol and for each of its instrumented phases

#### Scenario: Single sample

- **WHEN** exactly one successful cycle of a protocol has been executed
- **THEN** min, max, mean, and median for that protocol are equal to that single measurement
- **AND** the standard deviation is reported as zero

#### Scenario: No samples yet

- **WHEN** no cycle of a protocol has been executed since the last reset
- **THEN** the device reports a sample count of zero for that protocol
- **AND** does not report fabricated or placeholder statistics for it

### Requirement: Statistics reset

The device SHALL provide a way to reset all accumulated timing statistics and cycle counters without reflashing, so that a benchmark run starts from a known-empty state.

#### Scenario: Reset clears accumulated data

- **WHEN** a reset is requested after cycles have been recorded
- **THEN** all sample counts return to zero
- **AND** subsequent statistics reflect only cycles executed after the reset

### Requirement: Timer correctness under overflow

Latency measurement SHALL remain correct across wraparound of the microsecond counter, and SHALL not emit negative or implausibly large durations.

#### Scenario: Measurement spans counter wraparound

- **WHEN** a measured phase begins before and ends after the microsecond counter wraps
- **THEN** the reported duration is the true elapsed time
- **AND** it is not reported as a negative or near-maximum value

### Requirement: Instrumentation overhead is bounded and disclosed

The measurement itself SHALL not materially distort the quantity being measured. The overhead of the timing instrumentation SHALL be characterised and reported once per benchmark run.

#### Scenario: Overhead is quantified

- **WHEN** a benchmark run is performed
- **THEN** the results include a measured cost of an empty instrumented region on that device
- **AND** that figure is available for comparison against the shortest measured cryptographic phase

#### Scenario: Overhead does not dominate the shortest phase

- **WHEN** the measured instrumentation overhead is not negligible relative to the shortest instrumented phase
- **THEN** that phase's results are reported with an explicit caveat identifying the overhead as a confound
