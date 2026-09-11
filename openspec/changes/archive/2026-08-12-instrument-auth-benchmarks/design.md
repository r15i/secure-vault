## Context

See `proposal.md` → Why for motivation. The design-relevant constraints:

- **Platform.** ESP32-C3 SuperMini, Arduino framework on PlatformIO (`ESP32_Auth_PIO/platformio.ini`, board `esp32-c3-devkitm-1`). Single RISC-V core at 160 MHz, `WebServer` handling requests from the Arduino loop, WiFi associated throughout. Device context per `AGENTS.md`: `192.168.1.128`, `/dev/ttyACM1`, 115200 baud.
- **Crypto is already mbedTLS.** `main.cpp` uses `mbedtls/aes.h` and `mbedtls/md.h`. ESP-IDF's mbedTLS binds AES and SHA to the chip's hardware accelerators, so an AES-128 ECB block operation costs single-digit microseconds — not the 2.5 ms the reference paper measured on an Arduino.
- **That speed is the central measurement problem.** At ~1 µs clock granularity, timing one AES block gives 10–30% quantisation error. The instrumentation has to be designed around this, not merely added.
- **Existing measurement decision stands.** `docs/Measurement_Strategy_and_Hardware.md` already rejected USB power meters (1–2 Hz sampling) and INA219 wiring in favour of software timing with the paper's own energy model. This design implements that decision properly.
- **The reference paper's method and numbers** (Gupta & Kumaraguru, TrustCom 2018, §VI-A and Table 1): energy = average current × voltage × execution time, on an Arduino drawing 19.9 mA at 5 V = **99.5 mW**. AES-128 operation 2.5 ms / 248.75 µJ; HMAC 1.5 ms / 149.25 µJ; ECC 1105 ms / 109,950 µJ. Composite: Classical (2 AES) 497.5 µJ, Secure Vault (2 AES + 1 HMAC) 646.75 µJ.
- **Current firmware state.** No timing exists; the three verify handlers add the paper's constants to accumulators and `handleECCVerify()` performs no cryptography at all.

## Goals / Non-Goals

**Goals:**

- Measure per-primitive cost with an error small enough that the ~1.3× Secure-Vault-over-Classical difference is resolvable rather than lost in timer noise.
- Keep the paper's energy model intact — only the latency input changes from literature to measurement.
- Make ratio comparison the load-bearing claim, since it is invariant to the power constant and therefore survives the platform mismatch.
- Make a full run fast enough to iterate on: seconds for the symmetric protocols, well under a minute overall.

**Non-Goals:**

- Auditing or correcting the cryptographic construction of the protocols themselves. The Secure Vault implementation deviates from the paper in places (AES-ECB, `C2 % NUM_KEYS` index folding, and a vault rotation that XORs `hmac[j % 32] ^ i` rather than replacing key material from the HMAC output). These are recorded here so they are not mistaken for measurement artifacts, but changing them would change what is being measured and belongs in a separate change.
- External power measurement hardware, sleep/low-power modes, and the Phase 3 application (all excluded in the proposal).
- Constant-time or side-channel-hardened implementations. Timing variance is data here, not a vulnerability to fix.

## Decisions

### 1. Timing primitive: `esp_timer_get_time()`, not raw `micros()`

Use the 64-bit monotonic microsecond counter `esp_timer_get_time()` for all measurement.

*Why:* it is the same clock — Arduino-ESP32's `micros()` is `esp_timer_get_time()` truncated to `uint32_t` — so this keeps the microsecond-resolution approach the project committed to, while removing the 71.6-minute wraparound entirely. Long unattended runs are a stated use case (`make test-*-long`), so a wraparound-correct design is not optional.

*Alternative considered:* keep `micros()` and rely on `uint32_t` subtraction being wraparound-correct. It is correct, but only if every arithmetic step stays unsigned — one `int` promotion reintroduces the bug silently. The 64-bit clock makes the class of error unreachable. `cycles`/`esp_cpu_get_cycle_count()` would give finer resolution but is not comparable across clock-frequency states and complicates the energy model; rejected for that reason.

### 2. Two measurement modes: amortised batch (primary) and single-shot per cycle (secondary)

- **Amortised batch — the number that gets reported.** A dedicated benchmark path runs K repetitions of a protocol's cryptographic work inside one timed region and divides by K. With K = 1000, a 1 µs clock granularity becomes 0.001 µs of quantisation error on the per-operation figure — three orders of magnitude below the difference being resolved.
- **Single-shot per cycle — the reality check.** The live authentication handlers each time their own phases once per request. These figures are noisier but prove the batch path is representative of real authentications, and they carry the crypto-vs-handler split.

*Why both:* the batch alone could drift from reality (warm caches, no request parsing); the single-shot alone cannot resolve a 1.3× difference at microsecond granularity. Requiring them to agree within dispersion (spec: *Batch is equivalent to individual cycles*) makes each a check on the other.

*Alternative considered:* single-shot only, with a large sample count and reliance on the mean to average out quantisation. Quantisation error at this scale is not zero-mean with respect to the comparison — it is bounded by the clock tick, which is itself comparable to the AES phase duration. Rejected.

### 3. Defend the batch loop against the optimiser

The batch loop must not be eliminated or hoisted. Each iteration writes into a `volatile`-qualified sink and consumes the previous iteration's output as part of its next input, so the repetitions form a dependency chain the compiler cannot collapse.

*Why:* a benchmark that measures a loop the compiler deleted reports a suspiciously fast, entirely fictional number. This is the single most likely way for this change to produce plausible-looking wrong data. The build's optimisation level is recorded with the results so the figures are interpretable.

### 4. Warm-up iterations are discarded and reported separately

The first repetitions of any primitive pay flash-cache misses and mbedTLS context setup. A fixed warm-up count is executed and excluded from the reported statistics; the warm-up cost is reported as its own labelled figure.

*Why:* including it inflates the mean and inflates it unequally across protocols (ECC's setup dwarfs AES's), which would distort exactly the ratios the report defends. Reporting rather than merely discarding it keeps the cold-start cost visible, since it is real for a device that authenticates once and sleeps.

### 5. On-device statistics: Welford streaming, plus a bounded ring buffer for the median

- `count`, `min`, `max`, `mean`, and variance via **Welford's online algorithm** — O(1) memory per series, numerically stable, no sample storage.
- **Median** from a fixed 256-sample ring buffer of the most recent samples per series.

*Why:* storing every sample does not fit. Roughly a dozen instrumented series at 1000+ samples each would need tens of kilobytes of the SRAM left over after WiFi and the web server. Welford gives exact mean/stddev over all samples for free. The median is inherently order-statistic-bound, so it is computed over a bounded recent window, and **the output labels the median with the window size** so nobody reads it as a whole-run median.

*Alternative considered:* streaming all raw samples to the host and computing statistics there. Cleanest statistically, but pushing per-sample data over WiFi during a run injects transport work into the measured window. Rejected for the primary path; the batch path may return a raw sample block for a single protocol on request, since that transfer happens after the timed region.

### 6. Dual power model as two build-time constants

```
PAPER_POWER_MW  = 99.5     // 19.9 mA @ 5 V — reference paper §VI-A
DEVICE_POWER_MW = <value>  // ESP32-C3, CPU active @160 MHz, WiFi associated
```

Energy is `energy_uJ = power_mW × latency_us / 1000`. Both constants are emitted in every telemetry response and every result row (spec: *Power constants are declared, not implicit*), so no figure is orphaned from the assumption that produced it.

**Recommended default for `DEVICE_POWER_MW`: 82.5 mW** (3.3 V × 25 mA, ESP32-C3 modem-sleep CPU-active draw at 160 MHz with the radio associated — the actual condition during a measured crypto phase).

*Note a conflict to resolve:* `docs/Measurement_Strategy_and_Hardware.md` currently asserts "~260mW during active processing" with no cited source. 260 mW at 3.3 V implies ~79 mA, which is closer to sustained radio activity than to CPU-bound crypto with the radio idle. The constant is a single build-time definition precisely so this can be changed with one edit and one re-run — and because **every ratio in the report is invariant to it**, the headline conclusions do not move when it does.

*Alternative considered:* a single-model report using only the paper's constant. Simpler, but it would put a number on the page that this board does not consume; the dual model was selected explicitly to avoid that.

### 7. ECC: mbedTLS ECDSA over P-256, fixed keys, sign + verify per cycle

- Curve `MBEDTLS_ECP_DP_SECP256R1` with SHA-256, via `mbedtls/ecdsa.h`.
- **Fixed test key pair compiled in** for the device, plus the host's public key. Key generation is performed once at boot and reported as a labelled setup phase, never folded into per-cycle cost.
- Each cycle performs **one sign and one verify on the device**, mirroring the two-primitive structure of the symmetric protocols (Classical: 2 AES; Secure Vault: 2 AES + HMAC) so the ratio comparison is structurally like-for-like rather than comparing one asymmetric operation against two symmetric ones.
- RNG for ECDSA signing: an `f_rng` callback wrapping the hardware RNG (`esp_fill_random`), avoiding a CTR-DRBG instance in the timed path.

*Why fixed keys:* per-cycle keygen would dominate and would make runs non-deterministic. Compiled-in private keys are unacceptable in production and acceptable in a benchmark; the design records that explicitly rather than leaving it as an implicit smell.

*Alternative considered:* ECDH key agreement instead of ECDSA. ECDH is arguably closer to the paper's "ECC based public key encryption", but ECDSA challenge-response maps directly onto the challenge-response shape of the other two protocols, keeping the comparison clean. Recorded as a deliberate substitution to disclose in the analysis.

### 8. Hardware-acceleration status is recorded, not assumed

The build records which mbedTLS operations bind to hardware on this chip (AES and SHA are accelerated; the ESP32-C3 has ECC point-multiplication hardware whose use by mbedTLS depends on build configuration), and the benchmark output carries that record.

*Why:* it is the primary explanation for divergence from the paper's ratios, and it is the difference between "ECC is 170× Secure Vault" and a materially different figure. An unverified assumption here would undermine the deviation analysis, which must name causes (spec: *Each divergence has an attributed cause*). If the accelerated path cannot be confirmed for ECC, the analysis states the measured figure was taken on the software path.

### 9. Batch requests are time-bounded and subdivided

A batch request is capped by wall-clock duration (target ≤ 2 s of work per request). If K repetitions would exceed it, the work is split across internal chunks with the watchdog serviced between them, or the request is rejected with a stated maximum.

*Why:* the symmetric protocols are microseconds per operation, so K = 1000 costs milliseconds. ECDSA is tens of milliseconds per operation, so the same K would block the `WebServer` loop for a minute and trip the task watchdog. Different K per protocol, plus a hard duration bound, keeps the fast path fast without making the slow path unstable.

### 10. Host harness: one command, run-scoped output, charts from the dataset only

- `test_client.py` gains ECDSA verification (host side) and statistics retrieval; a separate analysis script owns CSV loading and chart rendering.
- The **host generates the run identifier** (the device has no RTC) and stamps every row with it.
- Charts read the CSV and nothing else, so any chart can be regenerated from an archived dataset without the device present.
- New Makefile targets drive it; the existing `test-sv-long` / `test-cl-long` / `test-ecc-long` targets documented in `AGENTS.md` keep working.
- ECC uses log-scaled axes where it shares an axis with the symmetric protocols — three orders of magnitude of range otherwise flattens Secure Vault and Classical into the baseline.

*Why separate scripts:* collection touches the device and can fail on the network; rendering is pure and must stay re-runnable. Coupling them would mean a plotting bug costs another device run.

### 11. Clean up before instrumenting, not after

The hygiene, configuration, and firmware-split work lands **first**, before any measurement code is written.

*Why:* the instrumentation touches nearly every file that carries the existing problems — `main.cpp`, the Makefile, `test_client.py`, and the docs. Retrofitting timing into a 232-line monolith and then splitting it means writing the same code twice and reviewing it twice. Ordering also protects the measurement work: a portable build and single-source configuration are what make "re-running reproduces results" (spec `benchmark-harness`) achievable on a second machine at all.

*Alternative considered:* instrument first, clean up afterwards as a follow-up. Rejected because the follow-up predictably never happens once results exist, and because the credential exposure should not wait behind a benchmark.

### 12. Configuration: an ignored local header plus a committed example

- **Firmware:** `src/config.h` (git-ignored) holding WiFi credentials, with `src/config.example.h` committed carrying every field and placeholder values. The build fails with a message naming the missing file if it is absent — never a compiled-in fallback credential (spec `project-configuration` → *Missing configuration fails clearly*).
- **Host:** one configuration module owning the device address, port, and defaults, overridable per invocation by environment variable or CLI flag.
- **Shared constants:** the two power constants are defined once on the firmware side, emitted in telemetry, and recorded by the host into the dataset from what the device reported — so host and firmware cannot silently disagree.

*Why an ignored header over build flags:* PlatformIO `build_flags` would work, but string credentials in `platformio.ini` put them back in a tracked file, which is the problem being solved. An ignored header keeps the secret-free tracked example useful as documentation of what must be supplied.

*Note on the exposure:* the SSID and password currently in `main.cpp:7-8` are in git history. This design does **not** rewrite history (explicitly excluded in the proposal), so removing the lines does not revoke them — the password must be rotated at the access point. The migration plan records this as an action outside the repository.

### 13. Firmware split into focused translation units

Target layout under `ESP32_Auth_PIO/src/`:

- `main.cpp` — setup, WiFi bring-up, route registration, loop. Nothing else.
- `config.h` / `config.example.h` — credentials and device settings.
- `metrics.h` / `.cpp` — the timing helper, the statistics accumulator, and the energy conversion (Decisions 1, 2, 5, 6).
- `auth_sv.{h,cpp}`, `auth_classical.{h,cpp}`, `auth_ecc.{h,cpp}` — one protocol each, owning its handlers, session state, and key material.
- `benchmark.{h,cpp}` — the batch path (Decision 9).
- `telemetry.{h,cpp}` — `/api/status`, `/api/energy`, the reset endpoint, and JSON construction.
- `dashboard.h` — the page markup as a single raw string literal, not thirty `html +=` concatenations.

*Why this cut:* it puts one protocol per file so the per-protocol instrumentation and its phase boundaries are reviewable in isolation, and it separates the measurement machinery from the protocols that use it, so the accumulator can be unit-reasoned about without WiFi in the picture. The dashboard becomes a raw literal because string-concatenation markup is where the current file is least maintainable and most error-prone to edit.

*Alternative considered:* keep one file and use section comments. Rejected — the file already exceeds what one screen of review can hold, and this change adds instrumentation, ECDSA, batching, and richer telemetry to it.

### 14. Repository hygiene, going forward only

- Add a `.gitignore` (the repository currently has none): `.pio/`, `.venv*/`, `__pycache__/`, `*.pyc`, `src/config.h`, and the results directory.
- `git rm -r --cached ESP32_Auth_PIO/.pio` to stop tracking ~40 MB of build output, and drop the stale root copy of the reference PDF now living under `docs/references/`.
- Consolidate to **one** virtualenv for host tooling with a dependency manifest covering `requests`, `pycryptodome`, `pandas`, `matplotlib`, and the ECC library; keep PlatformIO's environment separate since it is a toolchain, not a project dependency.
- Makefile: `PIO ?= pio` with the documented local path as a fallback rather than a hardcoded absolute, `PORT ?=` as today, and the **missing `test-ecc-long` target added** to match `AGENTS.md`.
- Results go to an ignored `results/` directory, replacing `test_log.csv` at the firmware project root.

*Why not rewrite history:* purging blobs and the credential from all commits would shrink the repository and remove the secret from history, but rewrites every SHA and requires a force-push. The user chose the non-destructive path; the credential is handled by rotation instead, which is the action that actually revokes it.

### 15. Documentation: one owner per fact

`docs/` remains the vault of record. `AGENTS.md` stops restating device and endpoint facts and points at the owning document, keeping only what an agent needs to act. The INA219 recommendations in `docs/Project Strategy and Grading.md` and `docs/Automation and Integration Guide.md` are marked superseded by the software-timing decision in `docs/Measurement_Strategy_and_Hardware.md` rather than left contradicting it.

*Why mark superseded rather than delete:* the reasoning for rejecting external power hardware is itself worth keeping — it is a defensible methodological decision the report will need to justify.

## Risks / Trade-offs

- **Compiler eliminates the batch loop → fabricated fast results.** → `volatile` sink plus an inter-iteration dependency chain (Decision 3); cross-check batch figures against single-shot handler measurements, which cannot be optimised away; record the optimisation level with the results. A batch/single-shot disagreement beyond dispersion fails the run rather than being reported.
- **Modelled energy is not measured energy.** Constant-power × time ignores that current draw varies with the instruction mix, and excludes radio energy entirely. → This is the paper's own method, applied identically, which is what makes the comparison valid; the analysis states the limitation explicitly (spec: *Modelling limits are disclosed*). Ratios, the load-bearing claim, are unaffected by the absolute constant.
- **Absolute energies will diverge from the paper by orders of magnitude.** → Expected and by design; the platform is ~150× faster per AES operation and has an AES accelerator the Arduino lacked. The report tests ratios and tabulates the absolute divergence with named causes rather than hiding it.
- **Measured ratios may not reproduce the paper's 1.3× / 170×.** Hardware AES compresses the symmetric side; whether ECC hits a hardware path shifts it further. The Secure-Vault-over-Classical ratio in particular depends on how HMAC-SHA256 over the full 256-byte vault compares against two accelerated AES blocks — it could land materially above 1.3×. → This is a finding, not a failure. The deviation analysis is specified to attribute it, and the honest result is more defensible than a matching one. It should not be tuned toward 1.3×.
- **ECC firmware growth breaks the flash/RAM budget.** → Check size after adding ECDSA; the P-256-only curve set keeps the footprint bounded. If it does not fit, reduce the enabled curve set before touching the measurement design.
- **`DEVICE_POWER_MW` is unresolved between 82.5 mW and the docs' 260 mW.** → Single build-time constant, stated in every output, and ratio conclusions invariant to it. Worst case is one edit and one re-run.
- **Compiled-in ECDSA private key.** → Acceptable for a benchmark, unacceptable as a deployment pattern; disclosed in the analysis so it is not read as a proposed design.
- **Statistics survive only until reboot.** RAM-resident counters are lost on reset, and a mid-run reboot silently truncates a long run. → The host resets statistics at run start and records the device uptime with the results, so a reboot mid-run is detectable rather than invisible.
- **Median is windowed, not whole-run.** → Labelled with its window size wherever it appears; mean and stddev remain exact over all samples.
- **The committed WiFi password stays valid until rotated.** Removing it from the working tree changes nothing about the credential's exposure in history. → The migration plan lists rotation at the access point as a required action outside the repository; the change does not claim removal revokes it.
- **The firmware split is a large diff landing before any measurement exists**, so a regression introduced by the reorganisation would be hard to distinguish from an instrumentation bug later. → Split and verify against current behaviour first — all three protocols authenticate end to end via `test_client.py` with the existing endpoints — and only then add timing. The split is behaviour-preserving by construction; no logic changes in the same step.
- **Untracking `.pio` does not shrink the repository**, and the old blobs remain in history. → Accepted deliberately (Decision 14); the benefit is that builds stop producing tracked churn from here on.
- **Ignoring `src/config.h` means a fresh checkout does not build until it is created.** → The committed example plus a build-time failure that names the missing file and its required fields makes this a one-step, self-explaining setup rather than a mystery.
- **Consolidating virtualenvs can break the working PlatformIO setup**, which currently resolves through `.venv_pio` at an absolute path. → Keep the PlatformIO environment as-is and make `PIO` overridable with that path as the fallback default, so the current machine keeps working while other machines are no longer excluded.

## Migration Plan

0. **Clean and reorganise first** (Decision 11): add `.gitignore` and untrack build output; extract configuration to the ignored header with its committed example; split `main.cpp` behaviour-preservingly; make the Makefile portable and add the missing `test-ecc-long` target; add the dependency manifest. Verify all three protocols still authenticate end to end before writing any measurement code. **Rotate the WiFi password at the access point** — this is outside the repository and nothing in the plan substitutes for it.
1. Land instrumentation and the dual-model energy path; keep `/api/energy` responding, with the new response shape and the constants included. This is the breaking API change flagged in the proposal — update `AGENTS.md` and `docs/Architecture and Endpoints.md` in the same step so the documented contract never lags the device.
2. Land real ECDSA behind the existing `/api/auth/ecc/*` endpoints; verify flash and RAM fit before proceeding.
3. Run the harness and generate the first real dataset and charts.
4. Rewrite `docs/Performance Analysis.md` from generated output. Preserve the superseded fabricated figures under an explicitly labelled historical note rather than deleting them — the fact that the earlier numbers were the paper's constants is itself worth recording. Move `ESP32_Auth_PIO/test_log.csv` aside; its schema changes and its existing rows carry no timing data.
5. Update `docs/Measurement_Strategy_and_Hardware.md` with both constants and their provenance, and retire the camera-rig and INA219 items in `docs/Tasks and Next Steps.md`.
6. Reconcile the remaining documentation to one owner per fact (Decision 15): mark the INA219 guidance in `docs/Project Strategy and Grading.md` and `docs/Automation and Integration Guide.md` as superseded, and reduce `AGENTS.md` to pointers plus what an agent needs to act.

*Rollback:* the measurement work is additive to the firmware apart from the `/api/energy` response shape and the ECC handler body. Reverting the firmware commit and reflashing restores the prior behaviour; generated datasets and charts are inert files under the results directory and can be discarded independently. The step-0 reorganisation is a separate, behaviour-preserving commit, so it can be kept when the measurement work is rolled back — which is the point of landing it on its own.

## Open Questions

- **Final value for `DEVICE_POWER_MW`** — 82.5 mW is recommended with datasheet provenance (Decision 6). Answerable at any point without touching the specs, the approach, or the task breakdown, since every ratio is invariant to it and it is one build-time constant.
- **Whether mbedTLS on this build routes P-256 point multiplication through the ESP32-C3's ECC hardware.** Determined empirically during implementation (Decision 8); the outcome changes what the deviation analysis attributes ECC's cost to, not what gets built or measured.
- **Whether to additionally report an ECDH variant** alongside ECDSA for closer correspondence to the paper's "ECC public key encryption" framing. Purely additive if wanted later; the substitution is disclosed either way.
