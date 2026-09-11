# Project Configuration & Guidelines

IoT authentication benchmarking on the ESP32-C3: implements the Secure Vault protocol
from Gupta & Kumaraguru (TrustCom 2018) and measures it against Classical AES-128 and
ECC baselines. Objective per `Projects Final - Sheet1.pdf`: *Internet of Things →
Authentication → implement the authentication protocol*.

**`docs/` is the source of truth** for architecture, methodology, and findings. This file
holds only what an agent needs in order to act, and points at the owner of every fact
rather than restating it — so changing a value cannot make this document wrong.

| I need to know… | Read |
| :--- | :--- |
| What the project is for, and the protocols | `docs/Project Goal.md` |
| Endpoints and their response shapes | `docs/Architecture and Endpoints.md` |
| How cost is measured, and why not with a power meter | `docs/Measurement_Strategy_and_Hardware.md` |
| Measured results | `docs/Performance Analysis.md` (generated) |
| What is being worked on now | `openspec/changes/instrument-auth-benchmarks/` |
| The reference paper | `docs/references/` |

## Setup (required before the first build)

```bash
cd ESP32_Auth_PIO
cp src/config.example.h src/config.h     # then set WIFI_SSID and WIFI_PASSWORD
../.venv/bin/pip install -r requirements.txt
```

`src/config.h` is **git-ignored and must never be committed** — it holds WiFi
credentials. The build fails with a message naming the missing fields if it is absent.
There is no compiled-in fallback credential.

## Configuration: where values are defined

Nothing here is duplicated; each value has one home.

| Value | Defined in | Override with |
| :--- | :--- | :--- |
| WiFi credentials | `ESP32_Auth_PIO/src/config.h` (ignored) | edit the file |
| Device address | `ESP32_Auth_PIO/host_config.py` | `--ip <addr>` or `ESP32_IP=<addr>` |
| Serial port | `host_config.py`, `Makefile` `PORT` | `make upload PORT=/dev/ttyUSB0` |
| PlatformIO binary | `Makefile` `PIO` (local venv, else `PATH`) | `make build PIO=/path/to/pio` |
| Power constants | `ESP32_Auth_PIO/src/power_model.h` | `-D DEVICE_POWER_MW=…` |
| ECC test keys | `src/ecc_keys.h` + `ecc_keys.py` (generated fixtures) | `python3 tools/gen_ecc_keys.py` |

The device uses DHCP and reports its actual address over serial at boot and via
`GET /api/status`, so treat the configured address as a convenience default.

## Commands

Run from `ESP32_Auth_PIO/`. `make help` prints these with their current values.

| Command | Does |
| :--- | :--- |
| `make build` / `make upload` / `make monitor` | Build, flash, serial monitor (115200) |
| `make test-native` | Unit-tests the measurement arithmetic — **no device needed** |
| `make test-security` | Rejection tests → `results/<run-id>/security.json`; the report cites it |
| `make submission` | Hand-in archive; refuses to build one carrying `src/config.h` credentials |
| `make benchmark` | Full run → `results/<run-id>/benchmark.csv` + `run.json` |
| `make analyze CSV=<path>` | Charts + deviation report from a dataset — no device needed |
| `make test` | One authentication cycle per protocol |
| `make test-sv-long` / `test-cl-long` / `test-ecc-long` | Continuous cycles, one protocol |
| `make test-batch` / `test-all-batch` | Fixed-count batches |

## API

All JSON. Full response shapes in `docs/Architecture and Endpoints.md`.

- Every `/init` returns a `sid`; the matching `/verify` must pass it as `?sid=<n>`.
- **Monitoring:** `GET /api/status`, `GET /api/energy`
- **Benchmark:** `GET /api/benchmark?protocol=<sv|classical|ecc>&k=<N>`, `POST /api/reset`
- **Auth:** `GET|POST /api/auth/{sv,classical,ecc}/{init,verify}`

## Things worth knowing before you change something

- **Energy is derived, never measured directly:** `E(µJ) = P(mW) × t(µs) / 1000`, applied
  at two declared power constants. Every reported figure is labelled with its model. Do
  not add an energy figure whose power model is unstated, and do not reintroduce a
  per-cycle literature constant — the paper's values belong in `paper_reference.py`, which
  exists to be compared against, not reported.
- **Ratios carry the argument, not absolute energies.** Ratios are invariant to the power
  constants; absolute values diverge from the paper by orders of magnitude because this
  chip has hardware AES/SHA and no hardware ECC. Never tune parameters to move a measured
  ratio toward the paper's value.
- **The batch path is the primary measurement.** One AES block costs single-digit
  microseconds, so single-shot timing at 1 µs granularity cannot resolve the differences
  that matter. If you touch the batch loop, keep the `volatile` sink and the
  iteration-to-iteration dependency chain: without them the optimiser can delete the loop,
  and the benchmark will report a beautiful fictional number.
- The Secure Vault implementation deviates from the paper in places (AES-ECB, `C2 %
  NUM_KEYS` index folding, XOR-based vault rotation). Known and deliberately out of scope —
  changing it changes what is being measured.
