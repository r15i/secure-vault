## 1. Repository hygiene and portable build

Do this group first (design Decision 11) — the measurement work rewrites these same files.

- [ ] 1.1 **Rotate the WiFi password at the access point.** The value in `ESP32_Auth_PIO/src/main.cpp:8` is in git history and this change does not rewrite history; removing the line does not revoke it. This is an action outside the repository and nothing else in this plan substitutes for it.
- [x] 1.2 Add a `.gitignore` (none exists in the repository today) covering `.pio/`, `.venv*/`, `__pycache__/`, `*.pyc`, `src/config.h`, and `results/`.
- [x] 1.3 `git rm -r --cached ESP32_Auth_PIO/.pio` to stop tracking roughly 40 MB of build output; confirm a subsequent build produces no tracked or unignored churn (spec `project-configuration` → *Build output is ignored and untracked*).
- [x] 1.4 Drop the stale tracked root copy of `Authentication_of_IoT_Device_and_IoT_Server_Using_Secure_Vaults.pdf`, now living at `docs/references/`.
- [x] 1.5 Replace the absolute `PIO = /home/r15i/.../.venv_pio/bin/pio` in `ESP32_Auth_PIO/Makefile:2` with `PIO ?= pio`, keeping the current local path as a documented fallback so this machine keeps working (design Decision 14).
- [x] 1.6 Add the missing `test-ecc-long` Makefile target, which `AGENTS.md:20` documents but the Makefile does not define (spec `project-configuration` → *Documented targets are present*).
- [x] 1.7 Add a Python dependency manifest declaring `requests`, `pycryptodome`, `pandas`, `matplotlib`, and the ECC library; verify a fresh install from it can run the client (spec → *Declared dependencies*).
- [x] 1.8 Consolidate host tooling onto one virtualenv, leaving PlatformIO's environment separate as a toolchain rather than a project dependency.
- [x] 1.9 Create the ignored `results/` directory convention for generated datasets and charts, replacing `test_log.csv` at the firmware project root.

## 2. Single-source configuration

- [x] 2.1 Add `ESP32_Auth_PIO/src/config.example.h` with every required field and placeholder values, committed; and `src/config.h`, git-ignored, as the real local source (design Decision 12).
- [x] 2.2 Remove the hardcoded `ssid` and `password` from `main.cpp:7-8`; read them from the config header. Verify no tracked file contains either value (spec `project-configuration` → *Tracked files contain no credentials*).
- [x] 2.3 Make a missing `src/config.h` fail the build with a message naming the file and the fields it must contain, with no compiled-in fallback credential (spec → *Missing configuration fails clearly*).
- [x] 2.4 Move the device address out of `test_client.py:12` into one host configuration module, overridable by environment variable or CLI flag, and make every host consumer read from it.
- [x] 2.5 Update the documentation to name where each configuration value is defined instead of reproducing it — `AGENTS.md`, `docs/Architecture and Endpoints.md`, and `docs/Performance Analysis.md` currently restate the device IP in five places (spec → *Documentation does not restate values*).

## 3. Firmware structure

Behaviour-preserving only — no logic changes in this group (design Decision 13).

- [x] 3.1 Split `main.cpp` into `main.cpp` (setup, WiFi, route registration, loop), `metrics`, `auth_sv`, `auth_classical`, `auth_ecc`, `benchmark`, `telemetry`, and `dashboard.h`.
- [x] 3.2 Move the dashboard markup into a single raw string literal in `dashboard.h`, replacing the ~30 `html +=` concatenations.
- [x] 3.3 Move each protocol's session state, key material, and handlers into its own translation unit.
- [ ] 3.4 Verify all three protocols still authenticate end to end via `test_client.py` against the unchanged endpoints, before any measurement code is added (design Risks: reorganisation regressions must not be confusable with instrumentation bugs).

## 4. Measurement foundation

- [x] 4.1 Add a timing helper over `esp_timer_get_time()` returning 64-bit microsecond durations, with a scoped begin/end pair usable inside request handlers (design Decision 1).
- [x] 4.2 Add a per-series statistics accumulator: count/min/max plus Welford mean and variance, and a 256-sample ring buffer for the windowed median (design Decision 5).
- [x] 4.3 Define the instrumented series set as named constants: per-protocol aggregates (`sv`, `classical`, `ecc`) and per-phase series (SV vault-key-derivation, SV AES decrypt, SV AES encrypt, SV HMAC-SHA256, SV vault rotation; Classical AES decrypt; ECC sign, ECC verify), plus `crypto` and `handler` scopes per protocol.
- [x] 4.4 Add the empty-region overhead characterisation: measure an instrumented region containing no work and store it as its own series (spec `protocol-instrumentation` → *Instrumentation overhead is bounded and disclosed*).
- [x] 4.5 Verify wraparound correctness and that durations are never negative or near-maximum, by unit-testing the duration arithmetic against synthetic counter values (spec → *Timer correctness under overflow*).

## 5. Dual energy model

- [x] 5.1 Define `PAPER_POWER_MW = 99.5` and `DEVICE_POWER_MW` (default 82.5) as build-time constants with a source comment each (design Decision 6).
- [x] 5.2 Implement `energy_uJ = power_mW × latency_us / 1000` as a single shared conversion used by every energy figure the device reports.
- [x] 5.3 Add a constants-provenance block (value, unit, derived current/voltage, source) emitted with every telemetry response (spec `energy-reporting` → *Power constants are declared, not implicit*).
- [x] 5.4 Remove the hardcoded per-cycle accumulators `energy_sv_uj += 646.75`, `energy_classical_uj += 497.5`, and `energy_ecc_uj += 109950.0`, replacing them with measured-latency-derived accumulation under both models.
- [x] 5.5 Have the host record the power constants into the dataset from what the device reported, and error on a firmware/host mismatch rather than reconciling silently (spec `project-configuration` → *Firmware and host agree on shared constants*).

## 6. Instrument the symmetric protocols

- [x] 6.1 Instrument the Secure Vault verify path: time vault key derivation, AES-128 decrypt of M3, AES-128 encrypt of M4, HMAC-SHA256, and vault rotation as separate phases.
- [x] 6.2 Instrument the Classical verify path: time the AES-128 decrypt phase.
- [x] 6.3 Record `crypto` time (sum of instrumented phases) separately from `handler` time (full handler duration including hex decode, argument parsing, response construction) for both protocols, and assert crypto ≤ handler (spec `protocol-instrumentation` → *Separation of cryptographic time from transport time*).
- [x] 6.4 Record phases that executed before a verification failure, and exclude failed cycles from success-only statistics while counting them as failures (spec → *Timing survives a failed authentication*).

## 7. Real ECC authentication

- [x] 7.1 Confirm the build's mbedTLS exposes `MBEDTLS_ECDSA_C` and `MBEDTLS_ECP_DP_SECP256R1_ENABLED`; add the needed flags to `platformio.ini` if absent.
- [x] 7.2 Add an `f_rng` callback wrapping the hardware RNG (`esp_fill_random`) for ECDSA signing (design Decision 7).
- [x] 7.3 Compile in the device P-256 key pair and the host's public key; load them once at boot and time that setup as a distinct labelled setup phase, excluded from per-cycle cost (spec `ecc-authentication` → *Key material availability*).
- [x] 7.4 Extend `/api/auth/ecc/init` to issue a fresh random device challenge each cycle and to accept the peer's challenge.
- [x] 7.5 Replace the `handleECCVerify()` stub with a real exchange: SHA-256 + ECDSA sign over the peer's challenge, and ECDSA verify of the peer's signature over the device's challenge; time both operations separately (spec → *Two-operation exchange structure*).
- [x] 7.6 Return success only when verification succeeds; reject replayed signatures and stale sessions with responses that distinguish malformed request, uninitialised session, and verification failure (spec → *Error reporting is distinguishable*).
- [x] 7.7 Check flash and RAM footprint after adding ECDSA and confirm it fits the ESP32-C3 budget; reduce the enabled curve set if it does not.
- [x] 7.8 Record which mbedTLS primitives bind to hardware on this build (AES, SHA, and whether P-256 point multiplication uses the chip's ECC hardware) and expose that record in telemetry (design Decision 8).

## 8. On-device batch benchmark path

- [x] 8.1 Add a batch benchmark endpoint accepting a protocol and repetition count K, executing K repetitions of that protocol's cryptographic work in one timed region and returning per-operation statistics (spec `benchmark-harness` → *On-device batch execution for throughput*).
- [x] 8.2 Make the batch path reuse the same primitives and key material as the live authentication handlers, so batch results are representative.
- [x] 8.3 Defend the loop against the optimiser: `volatile` sink plus an inter-iteration dependency chain; record the build's optimisation level in the response (design Decision 3).
- [x] 8.4 Execute and discard a fixed warm-up count, reporting the warm-up cost as its own labelled figure (design Decision 4).
- [x] 8.5 Bound batch work by wall-clock duration (target ≤ 2 s per request), subdividing into chunks with the watchdog serviced between them, or rejecting oversized K with a stated maximum (design Decision 9).
- [x] 8.6 Add a statistics reset endpoint that zeroes all series and counters (spec `protocol-instrumentation` → *Statistics reset*).

## 9. Telemetry and dashboard

- [x] 9.1 Rewrite the `GET /api/energy` response: per protocol, the success and failure counts, latency statistics (count/min/max/mean/median/stddev in µs, median labelled with its window size), per-cycle energy under both models, and accumulated energy under both models in µJ (with Wh retained for continuity).
- [x] 9.2 Expose per-phase latency statistics and the instrumentation-overhead and warm-up figures through telemetry.
- [x] 9.3 Include the power-constants provenance block and the hardware-acceleration record in the telemetry response.
- [x] 9.4 Update the dashboard to show, per protocol, measured mean latency and both labelled energy figures; remove any unlabelled single energy value (spec `energy-reporting` → *Dashboard presents both models*).
- [x] 9.5 Add device uptime to telemetry so a mid-run reboot is detectable by the harness.
- [x] 9.6 Update `AGENTS.md` and `docs/Architecture and Endpoints.md` to the new endpoint contract in the same step as the API change (design Migration Plan step 1).

## 10. Host harness

- [x] 10.1 Add host-side P-256 ECDSA signing and verification to `test_client.py` so the ECC exchange completes and the device's signature is independently verified.
- [x] 10.2 Add a statistics-retrieval path and per-cycle wall-clock round-trip recording, reported as a separate labelled quantity from device crypto time.
- [x] 10.3 Add a single benchmark command that generates a run identifier, resets device statistics, runs the configured cycle count per protocol via the batch path, and collects results (spec `benchmark-harness` → *Single-command benchmark run*).
- [x] 10.4 Also run a smaller set of individual network-driven cycles per protocol, and compare their mean crypto latency against the batch figure; report disagreement beyond dispersion as a run failure (spec → *Batch is equivalent to individual cycles*).
- [x] 10.5 Fail with a clear message naming the attempted address when the device is unreachable, and never emit a partial dataset as a completed benchmark.
- [x] 10.6 Record the device uptime at run start and end; flag the run if the device rebooted mid-run.

## 11. Results dataset and charts

- [x] 11.1 Define and write the CSV schema: run identifier, protocol, phase/aggregate label, sample count, failure count, min/max/mean/median/stddev µs, per-cycle energy under each model, and the power constant used for each model (spec `benchmark-harness` → *Machine-readable result dataset*).
- [x] 11.2 Write results under the run-scoped path in `results/` so successive runs do not overwrite or conflate each other.
- [x] 11.3 Add a separate analysis script that reads only the CSV and renders charts, with no device dependency.
- [x] 11.4 Chart: per-cycle energy by protocol under both power models, log-scaled where ECC shares an axis with the symmetric protocols, with the scale stated and all axis units labelled.
- [x] 11.5 Chart: latency by protocol with the per-phase breakdown visible.
- [x] 11.6 Chart: measured inter-protocol ratios alongside the reference paper's ratios.

## 12. Paper comparison and deviation analysis

- [x] 12.1 Record the paper's reference figures with their source (§VI-A / Table 1): AES-128 op 2.5 ms / 248.75 µJ, HMAC 1.5 ms / 149.25 µJ, ECC 1105 ms / 109,950 µJ, Classical 497.5 µJ, Secure Vault 646.75 µJ, at 99.5 mW.
- [x] 12.2 Generate the ratio comparison table: measured SV/Classical, ECC/SV, and ECC/Classical against the paper's ≈1.30, ≈170, and ≈221, with the deviation stated for each (spec `benchmark-harness` → *Paper-ratio comparison*).
- [x] 12.3 State in the output that ratios are invariant to the choice of power constant, and present the absolute per-cycle divergence from the paper explicitly rather than omitting it.
- [x] 12.4 Write the deviation analysis attributing each divergence to a named cause: processor and clock-speed difference, hardware AES/SHA acceleration, the two supply/current bases behind the power constants, exclusion of radio and transport energy from the model, and the ECDSA-for-ECC-encryption substitution.
- [x] 12.5 State the modelling limits: energy is derived from latency under a constant-power assumption, not measured with a power meter, and what that excludes.
- [x] 12.6 Report measured ratios as found — do not tune parameters, K, or phase boundaries to move a ratio toward the paper's value (design Risks).

## 13. Validation and documentation reconciliation

- [ ] 13.1 Run the benchmark twice under identical conditions and confirm mean per-protocol latencies agree within reported standard deviations and ratios agree to the reported precision (spec `benchmark-harness` → *Re-running reproduces results within dispersion*).
- [ ] 13.2 Confirm the instrumentation overhead figure is negligible against the shortest measured phase; if not, add the specified caveat to that phase's results.
- [x] 13.3 Confirm no reported figure derives from a literature constant, by checking that every energy value in telemetry and CSV recomputes from its own latency and power-constant columns.
- [x] 13.4 Rewrite `docs/Performance Analysis.md` entirely from generated output, retaining the superseded figures under a labelled historical note recording that they were the paper's constants multiplied by a cycle count (design Migration Plan step 4).
- [x] 13.5 Move `ESP32_Auth_PIO/test_log.csv` aside; its schema is superseded and its rows carry no timing data.
- [x] 13.6 Update `docs/Measurement_Strategy_and_Hardware.md` with both power constants and their provenance, replacing the unsourced "~260mW" claim.
- [x] 13.7 Retire the camera-rig and INA219 items in `docs/Tasks and Next Steps.md` as superseded by this change.
- [x] 13.8 Mark the INA219 guidance in `docs/Project Strategy and Grading.md` and `docs/Automation and Integration Guide.md` as superseded by the software-timing decision, so no document recommends what another records as rejected (spec `project-configuration` → *Superseded measurement guidance is reconciled*).
- [x] 13.9 Reduce `AGENTS.md` to pointers plus what an agent needs to act, with `docs/` owning device, endpoint, and command facts (spec → *One owner per fact*).
- [x] 13.10 Re-verify every command listed in `AGENTS.md` and `docs/Architecture and Endpoints.md` exists and does what it claims (spec → *Documented commands exist and work*).
