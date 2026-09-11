# Architecture and Endpoints

## Device Context

Configuration values live in code so that a change cannot silently invalidate this document.

*   **Device address:** defined in `ESP32_Auth_PIO/host_config.py` (`DEFAULT_DEVICE_IP`);
    override with `--ip` or `$ESP32_IP`. DHCP, so the device reports its real address over
    serial at boot and via `GET /api/status`.
*   **Serial port:** `ESP32_Auth_PIO/host_config.py` (`DEFAULT_SERIAL_PORT`) and `PORT` in the
    Makefile. Baud rate 115200.
*   **WiFi credentials:** `ESP32_Auth_PIO/src/config.h`, git-ignored. Template at
    `src/config.example.h`.
*   **Web Dashboard:** the device root `/` (real-time RSSI, Uptime, and Energy tracking).
*   **Auto-Refresh:** UI updates every 1-60s (user-configurable).

## Standardized API Endpoints
All endpoints are JSON.

### Monitoring & Telemetry
*   `GET /api/status`: WiFi RSSI, uptime, device IP.
*   `GET /api/energy`: measured latency statistics (count / min / max / mean / median /
    stddev in µs) per protocol and per cryptographic phase, and energy under **both**
    power models — derived from those measurements, never from literature constants.
    Carries the two power constants with their provenance, the formula, the
    hardware-acceleration record, and the instrumentation overhead.

    The median is computed over the most recent 256 samples and is labelled with that
    window; mean and standard deviation are exact over all samples.

### Benchmarking
*   `GET /api/benchmark?protocol=<sv|classical|ecc>&k=<N>`: runs N repetitions of the
    protocol's cryptographic work inside one timed region and returns the amortised
    per-operation cost, plus a separately reported warm-up figure that is excluded
    from the statistics. Bounded to 2 s of work per request; truncation is reported
    explicitly rather than silently.
*   `POST /api/reset`: clears accumulated statistics; re-measures instrumentation overhead.

### Authentication
Every `/init` returns a random 32-bit `sid`, and the matching `/verify` must carry it as
a query parameter (`?sid=<n>`). Only the request holding a session's identifier consumes
it, and the device keeps four slots per protocol, so neither a forged verify nor a flood
of `/init` can cancel a peer's pending session. Lookup is outside every timed phase.

*   **SV:** `GET /api/auth/sv/init`, `POST /api/auth/sv/verify?sid=<n>`
*   **Classical:** `GET /api/auth/classical/init`, `POST /api/auth/classical/verify`
*   **ECC:** `GET /api/auth/ecc/init`, `POST /api/auth/ecc/verify` — real ECDSA P-256
    (one sign + one verify on the device per cycle). Request body is
    `peer_challenge(32) || peer_signature(64)` as hex.

Every authentication response carries the measured `crypto_us` and `handler_us` for that
cycle and its energy under both models. Failure responses carry a `cause` field
distinguishing `no_session`, `malformed_request`, `verification_failed`, `bad_challenge`
(Secure Vault: C2 out of range, with a repeated index, or the same set as C1), and
`no_key_material`.

## Testing & Synchronization
### High-Precision Logging
The Python test client logs every event to `test_log.csv` with `HH:MM:SS.mmm` timestamps. This allows alignment with video footage from USB power meters.

### Makefile Commands
*   `make upload`: Flash firmware (Port defaults to `/dev/ttyACM1`).
*   `make test-sv-long`: Continuous Secure Vault cycles.
*   `make test-cl-long`: Continuous Classical cycles.
*   `make test-ecc-long`: Continuous ECC cycles.
*   `make monitor`: Open Serial Monitor at 115200 baud.
