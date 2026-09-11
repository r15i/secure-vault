## Why

The project's stated objective (per `Projects Final - Sheet1.pdf`, *Internet of Things → Authentication*) is to **implement the authentication protocol** from *Authentication of IoT Device and IoT Server Using Secure Vaults* (Gupta & Kumaraguru, TrustCom 2018) and evaluate it. The three protocols are implemented in firmware, but **the evaluation is fabricated rather than measured**:

- `ESP32_Auth_PIO/src/main.cpp` does not time anything. Each successful authentication adds a *literal constant copied out of the paper* to an accumulator — `energy_sv_uj += 646.75`, `energy_classical_uj += 497.5`, `energy_ecc_uj += 109950.0`. Every reported number is therefore the paper's Arduino result multiplied by a cycle count, and `docs/Performance Analysis.md` ("150 cycles") is that multiplication, not data from this device.
- `handleECCVerify()` executes **zero cryptography**. It sets `active = false`, adds the 109,950 µJ constant, and returns success. The 220× ECC overhead the analysis reports was never computed on the chip.
- Consequently the project cannot answer the one question it exists to answer — what the Secure Vault protocol actually costs on constrained hardware — and any reviewer comparing `main.cpp` to `docs/Performance Analysis.md` will find the numbers are not measurements.

This change replaces fabricated constants with real on-chip `micros()` instrumentation, implements the missing ECC path so it can be measured, and reports energy through a **dual model** that keeps the results comparable to the paper's Table 1 while remaining physically honest about this board.

## What Changes

**BREAKING** — the semantics of `GET /api/energy` change: values become derived from measured latency instead of accumulated paper constants. Existing `test_log.csv` data and `docs/Performance Analysis.md` figures are superseded and must be regenerated.

- **Real latency instrumentation.** Bracket every cryptographic phase of all three protocols with `micros()` and report per-phase microsecond latency: AES-128 ECB decrypt, AES-128 ECB encrypt, HMAC-SHA256, vault rotation, and (new) ECDSA operations. Measure the *crypto work only*, separated from HTTP parsing, hex conversion, and WiFi transmission, so protocol cost is not swamped by network time.
- **Real ECC.** Replace the `handleECCVerify()` stub with an actual mbedTLS ECDSA P-256 challenge-response (device signs a server nonce; signature verified host-side), so the asymmetric baseline is executed and timed rather than asserted.
- **Dual energy model.** Energy is computed as `latency × power`, using the paper's own method (Prasithsangaree et al.: energy = average current × voltage × execution time), evaluated at two hardcoded power constants:
  - **Paper-equivalent model** — 99.5 mW (the paper's Arduino: 19.9 mA at 5 V, §VI-A). Places this device's results on the same axis as Table 1.
  - **Device-real model** — a documented ESP32-C3 active-power constant. Reports what this board plausibly consumes.
  Both are reported for every protocol, side by side, with the constants stated in the output rather than buried in code.
- **On-device statistics.** Accumulate min / mean / median / max / stddev and sample count per operation across N cycles, so results carry dispersion instead of a single number. Exposed through the telemetry API and the web dashboard.
- **Automated benchmark harness.** A host-side runner that drives a configurable number of cycles per protocol, pulls the on-device statistics, and emits a machine-readable CSV plus comparison charts (per-cycle energy under both models, latency breakdown, and ratio-to-paper). Replaces the manual camera-and-USB-meter workflow that `docs/Tasks and Next Steps.md` still lists as Phase 1.
- **Ratio-based deviation analysis.** Because the ESP32-C3 has a hardware AES accelerator and runs at 160 MHz, its absolute per-operation latency is orders of magnitude below the paper's Arduino (paper: 2.5 ms per AES-128 operation). Absolute µJ therefore cannot and should not match. The comparison the report defends is the **ratio structure** — Secure Vault ≈ 1.3× Classical, ECC ≈ 170× Secure Vault — with measured ratios tabulated against the paper's and every divergence explained by a named hardware cause.
- **Documentation reconciliation.** `docs/Performance Analysis.md` is rewritten from generated output; `docs/Measurement_Strategy_and_Hardware.md` is updated to state the two power constants and their provenance; the obsolete camera-rig and INA219 tasks are retired.

The same pass also makes the project maintainable, because the instrumentation work rewrites nearly every file that currently carries these problems:

- **Repository hygiene.** The repository has **no `.gitignore` anywhere**, and `ESP32_Auth_PIO/.pio/` — roughly 40 MB of `.o`, `.d`, and `.sconsign314.dblite` build output — is **tracked in git** and churns on every build. Two virtualenvs (`.venv`, `.venv_pio`, 31 MB combined) sit inside the project untracked and unignored. Build output, environments, and generated results become ignored and untracked going forward.
- **Credentials out of source.** **BREAKING** — `ESP32_Auth_PIO/src/main.cpp` hardcodes a live WiFi SSID and password in tracked source. They move to an ignored local configuration header with a committed example template, so a fresh checkout has a documented, secret-free path to a working build. The already-committed credential must be **rotated at the access point**; removing the lines does not remove them from history, and this change does not rewrite history.
- **Portable build.** `ESP32_Auth_PIO/Makefile` pins `PIO` to the absolute path `/home/r15i/Desktop/local_projects/cyberphisical/project2/.venv_pio/bin/pio`, so the build works only for one user at one checkout path. Tool and port locations become overridable with working defaults, and Python dependencies — currently declared nowhere despite `requests` and `pycryptodome` being required — get a manifest.
- **Single source for device configuration.** The device address is duplicated across `test_client.py`, `AGENTS.md`, and two files under `docs/`. Configuration collapses to one authoritative definition per side that the documentation points at instead of restating.
- **Firmware structure.** `main.cpp` is a 232-line monolith holding WiFi setup, all three protocols, energy accounting, HTTP routing, and ~30 lines of dashboard HTML built by string concatenation. It is split into focused translation units so the new instrumentation lands in organised code rather than being retrofitted into one file and reorganised later.
- **Test interface consistency.** `AGENTS.md` documents `make test-ecc-long`, which **does not exist in the Makefile**. Documented commands and real targets are brought into agreement, and the docs' contradictory INA219 guidance is reconciled with the software-timing decision that superseded it.

Explicitly out of scope: INA219 or any external power-meter hardware (superseded by the software-timing decision already recorded in `docs/Measurement_Strategy_and_Hardware.md`), light/deep-sleep power modes, the Phase 3 password-manager application, and any rewriting of git history (the tracked build output and the committed credential are addressed going forward only).

## Capabilities

### New Capabilities

- `iot-auth/protocol-instrumentation`: On-device `micros()` timing of every cryptographic phase of the Secure Vault, Classical AES-128, and ECC protocols, with crypto time isolated from transport time, and per-operation statistics (min/mean/median/max/stddev/count) accumulated across cycles.
- `iot-auth/energy-reporting`: Derivation and exposure of energy figures from measured latency under two explicitly declared power constants (paper-equivalent 99.5 mW and device-real ESP32-C3 active power), including the telemetry API contract and dashboard presentation.
- `iot-auth/ecc-authentication`: A real ECDSA P-256 challenge-response authentication exchange on the device, replacing the no-op stub, so the asymmetric baseline is genuinely executed and measurable.
- `iot-auth/benchmark-harness`: Automated host-side benchmark execution, CSV result schema, comparison chart generation, and the paper-ratio deviation report.
- `iot-auth/project-configuration`: Single-source configuration of device address, credentials, and measurement constants; secrets kept out of tracked files; a build and test interface that works from a fresh checkout at any path with documented commands that exist.

### Modified Capabilities

None — this repository has no `openspec/specs/` capabilities yet, so all five are introduced here.

## Impact

- **Firmware** — `ESP32_Auth_PIO/src/main.cpp`: all three verify handlers, the energy accumulators, `/api/energy`, and the dashboard HTML/JS. Adds mbedTLS ECDSA (`mbedtls/ecdsa.h`, `mbedtls/ecp.h`, entropy/CTR-DRBG) usage; flash and RAM footprint grows and must be checked against the ESP32-C3 budget. The file is also split into multiple translation units, so this is a structural rewrite rather than an in-place edit.
- **Build** — `ESP32_Auth_PIO/platformio.ini`: possible mbedTLS ECP curve/feature flags and build-time definition of the two power constants. `ESP32_Auth_PIO/Makefile`: the hardcoded absolute `PIO` path becomes overridable, and the missing `test-ecc-long` target is added.
- **Version control** — a new `.gitignore` (none exists today); `ESP32_Auth_PIO/.pio/` and the stale root copy of the reference PDF are untracked; the two in-project virtualenvs and generated results are ignored. History is left intact, so repository size does not shrink.
- **Secrets** — the WiFi SSID and password leave `main.cpp` for an ignored local config header with a committed example. The already-committed credential requires rotation at the access point, outside this repository.
- **Host tooling** — `ESP32_Auth_PIO/test_client.py`: gains ECDSA signature verification, statistics retrieval, and structured result output; a new analysis/plotting script and its dependencies (`pandas`, `matplotlib`, plus an ECC-capable crypto library alongside the existing `pycryptodome`).
- **Test interface** — `ESP32_Auth_PIO/Makefile`: benchmark targets aligned with the harness; the existing `test-*-long` targets from `AGENTS.md` continue to work.
- **API** — `GET /api/energy` response shape changes (dual model + statistics); new or extended telemetry for per-phase timings. `AGENTS.md` and `docs/Architecture and Endpoints.md` must be updated to match.
- **Data and docs** — `ESP32_Auth_PIO/test_log.csv` schema; `docs/Performance Analysis.md`, `docs/Measurement_Strategy_and_Hardware.md`, `docs/Tasks and Next Steps.md`. Also `docs/Project Strategy and Grading.md` and `docs/Automation and Integration Guide.md`, whose INA219 guidance contradicts the software-timing decision, and `AGENTS.md`, which currently restates device and endpoint facts owned by `docs/`.
- **Host tooling layout** — generated datasets and charts move to a dedicated ignored results directory instead of a CSV at the firmware project root.
- **Device context** — unchanged per `AGENTS.md`: ESP32-C3 SuperMini at `192.168.1.128`, serial `/dev/ttyACM1`, 115200 baud.
