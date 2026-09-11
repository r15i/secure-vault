# Tasks and Next Steps

## Current state: measured

Four protocols run on the board and are measured end to end. The most recent run passes
every validity gate — `device_kind: device`, no invariant violations, no reboot, no
failed cycles, batch and network paths consistent — so `make report` renders without an
override. See `Performance Analysis.md` for what was found and `paper/Final_Report.pdf`
for the write-up.

- [x] Firmware: Secure Vault, Classical AES-128, single rotating password, ECDSA P-256.
- [x] Host client that is a real cryptographic peer for all four, not a driver.
- [x] Two independent measurement paths with a cross-check that fails the run.
- [x] Provenance recording, so a mock run cannot be reported as a measurement.
- [x] The paper's own Figure 3 baseline implemented, so its central claim is tested
      rather than inherited.
- [x] Rejection tests (`security_tests.py`, `make test-security`): replay, wrong key,
      tampered, out-of-order and malformed requests refused by every protocol, device
      failure counters corroborate, genuine cycle succeeds afterwards. Written to
      `results/<run-id>/security.json` and reported.

## Remaining before submission

- [ ] Read the report end to end.
- [x] Length held at twelve pages: body and references on 1-10, three appendix pages.
- [x] Headline per-cycle figure is the device-side phase sum, which is what the paper
      counts. The whole-region batch figure (peer simulation included) stays in the
      dataset as an upper bound.
- [x] `make submission` builds the archive and refuses one containing the WiFi
      credentials from `src/config.h`, which a plain zip of the working tree would ship.
- [ ] At submission: copy to a clean folder, create the new public repository, put its
      URL in `REPO_URL` (`report_content.py`), rebuild the report, then `make submission`.

## Known limitations, deliberately not fixed

- ~~**The Classical baseline performs one AES operation where the paper counts two.**~~
  Fixed on 2026-09-11: Classical is now a mutual challenge-response with one decrypt and
  one encrypt, matching the paper's simplest scheme. The rotating password matches its
  three operations, and is the baseline the argument leans on.
- **The ECC batch truncates** at the device's 2 s per-request budget (16 of 20 requested
  iterations). Disclosed in the report; lowering `--ecc-k` to 15 would remove the caveat.
- **Secure Vault deviates from the paper in three small ways** — the HMAC is keyed with
  `r1` alone, AES runs in ECB, and the vault is partitioned by key length rather than hash
  length. None changes the operation counts, so none changes the measured cost. Enumerated
  in the report. Two further deviations (indices not drawn distinct, C2 folded with
  `% NUM_KEYS` and allowed to equal C1) were removed on 2026-09-11 because they weakened
  security; the device now rejects such a C2 with `bad_challenge`, and `make test-security`
  exercises that.

- **The batch time budget does not bind for ECC.** `MAX_BATCH_MS` is 2000 ms but the
  check runs once per `CHUNK` of 16 iterations, and one ECC chunk is ~5.4 s, so a request
  can block the server for 5 s. Harmless to the figures (the batch still completes and is
  divided by what completed) but the stated ceiling is not enforced. Fix: check the budget
  every iteration for protocols whose per-op cost exceeds the chunk budget.
- ~~**Single pending session per protocol.**~~ Fixed on 2026-09-11: `src/sessions.h`
  keys sessions by a random 32-bit identifier with four slots per protocol, so neither a
  forged verify nor an `/init` flood can cancel a peer's pending session. The rejection
  tests include a case that passes only if the peer completes on its own session.

## Possible extensions

- [ ] **Power-saving mode:** light or modem sleep between cycles, to compare idle against
      active draw. IoT devices are idle most of the time, so this is where a deployment's
      energy actually goes.
- [ ] **Direct power measurement.** A high-rate current probe would capture what the
      derived model excludes — radio, regulator, idle draw, and the real current
      difference between an accelerated AES block and a software big-integer multiply. A
      complementary experiment, not a correction to this one.
- [ ] **Secure Vault as a 2FA authenticator** for a password manager, with a CLI that
      performs the vault handshake. `test_client.py` already does the handshake, so this
      is mostly presentation.

## Retired approaches

The original Phase 1 plan was to record a USB power meter on video and correlate the
footage against timestamped logs by hand.

- ~~**Camera rig** recording the USB Amp/Watt meter display.~~
- ~~**Video export and sync** against `test_log.csv` timestamps.~~
- ~~**INA219 integration** over I2C for automated telemetry.~~

**Why retired.** USB meters sample at 1–2 Hz and an INA219 in the low kHz, against
operations that complete in microseconds: neither instrument can see the events at all,
only a long-run average of the whole board. Manual video correlation would have added
transcription error on top of a measurement that was never capable of resolving the
difference. The deeper reason is scope — a meter measures the board, and the object of
study is the algorithm. Replaced by on-chip microsecond instrumentation; see
`Measurement_Strategy_and_Hardware.md`.
