# Secure Vault authentication on the ESP32-C3

Course project for Cyber-Physical Systems and IoT Security. Implements the Secure Vault
mutual-authentication protocol of **Gupta & Kumaraguru (TrustCom 2018)** on an
**ESP32-C3 SuperMini** (~EUR 4), and measures its cost against the three baselines the
paper compares it with: a classical pre-shared-key AES-128 challenge-response, the single
rotating password of its Figure 3, and ECDSA over P-256.

The question under test is the paper's efficiency claim — that Secure Vault buys key
rotation and replay resistance for a small constant-factor premium over plain symmetric
authentication, while asymmetric authentication costs orders of magnitude more.

Repository: <https://github.com/r15i/secure-vault>.

---

## Quick start

### With the board

```bash
cd ESP32_Auth_PIO
cp src/config.example.h src/config.h    # set WIFI_SSID and WIFI_PASSWORD
make venv                               # uv venv + host dependencies
make upload PORT=/dev/ttyACM0           # flash (check your port)
make monitor                            # note the IP printed at boot
make benchmark DEVICE_IP=<ip>           # -> results/<run-id>/
```

### Without the board

```bash
cd ESP32_Auth_PIO
make venv
make test-native      # unit-tests the measurement arithmetic; no device, no network
make smoke-test       # whole pipeline against the mock — SYNTHETIC, not results
```

`make help` lists every target with its current values.

The firmware also serves a dashboard on its root URL — live per-protocol statistics,
ratios against the paper, and buttons that trigger cycles and batches. It is shown in the
report as Appendix B, Figure B.4.

---

## What gets measured, and how

Energy is **derived from measured time**, never read from an instrument:

```
E = P · t          where P = V · I
E[µJ] = P[mW] × t[µs] / 1000
```

This is the reference paper's own method (its §VI-A, citing Prasithsangaree et al.), so
the two sets of figures are produced by the same procedure. Two power constants are
applied to the *same* latency and every figure says which one produced it:

| Model | Constant | Why |
| :--- | :--- | :--- |
| paper | 5.0 V × 19.9 mA = **99.5 mW** | puts results on the paper's axis |
| device | 3.3 V × 25 mA = **82.5 mW** | physically meaningful for this board |

**Ratios are the trustworthy part.** The power constant cancels in `E_A/E_B = t_A/t_B`,
so an inter-protocol ratio is a pure ratio of measured times, carrying no assumption.
Absolute energies depend on a constant that was declared, not measured.

**No power meter is used, by design.** The object of study is the *algorithm*, not this
board's consumption. A meter in the supply line measures the whole system — regulator,
radio, idle current, and how efficiently this particular silicon implements AES and SHA —
which would turn the comparison into one of hardware implementations, and would be hard to
align with the paper, which derives energy from time rather than measuring it. Resolution
is a secondary point: a USB meter samples at 1–2 Hz and an INA219 in the low kHz, against
microsecond operations.

Measuring the rail directly remains an **interesting next step**: it answers the
complementary question of what a *deployment* costs, including the radio and idle draw
this model deliberately excludes.

### Two independent measurement paths

| Path | What it is |
| :--- | :--- |
| **batch** (primary) | device runs K repetitions inside one timed region, divided by K — drives clock quantisation far below the differences being resolved |
| **network cycles** | real HTTP authentications the host verifies cryptographically |

The harness **fails the run** if the two disagree beyond the observed dispersion, or if
any protocol produced no successful network cycle. That cross-check is what makes the
amortised figure a protocol cost rather than an artefact of a loop.

---

## Provenance — read this before citing any number

`results/<run-id>/run.json` carries `device_kind`:

| Value | Meaning |
| :--- | :--- |
| `device` | real ESP32-C3. **Reportable.** |
| `mock` | `mock_device.py` — synthetic constants, **not measurements** |
| `unknown` | predates provenance recording; re-run before reporting |

submission from one without `--allow-mock`. The mock implements all four protocols
faithfully (same keys, same crypto, same vault rotation) so it can catch a broken client —
only its *timings* are invented.

> An earlier version of the mock returned the paper's own published numbers, which made
> the analysis print "+0.0% deviation" and read as a perfect reproduction. Never give the
> mock figures taken from the paper.

---

## Expect the ratios to differ from the paper

Measured `sv/classical` lands well above the paper's 1.30×, and the dominant cause is
**protocol composition, not hardware**:

| | Paper | This implementation (device side, per cycle) |
| :--- | :--- | :--- |
| Classical | 2 × AES-128 | **2** AES-128 ECB blocks (decrypt, then encrypt) |
| Rotating password | 3 × AES-128 | **3** AES-128 ECB blocks |
| Secure Vault | 2 × AES-128 + 1 HMAC | 4-key XOR derivation, **6** AES blocks, HMAC-SHA256 over the 256-byte vault, 256-byte rotation |
| ECC | one ECC public-key op | 1 ECDSA-P256 sign + 1 verify |

Hardware acceleration *does* explain the inflated ECC ratios (AES/SHA are accelerated on
this chip, P-256 is not), but it largely cancels between two symmetric protocols, so it
cannot account for the `sv/classical` gap.

---

## Layout

```
ESP32_Auth_PIO/          firmware + host harness
  src/                   firmware: auth_{sv,classical,ecc}.cpp, metrics, telemetry
  test_client.py         real protocol peer — mirrors the vault, verifies every reply
  benchmark.py           drives a run, cross-checks both paths, writes the dataset
  analyze.py             charts + deviation report from a dataset (no device needed)
  mock_device.py         functional stand-in; synthetic timings
  paper_reference.py     the paper's literature values — compared against, never reported
  test/test_metrics.cpp  host-side unit tests for the measurement arithmetic
  Makefile               every workflow; `make help`


results/<run-id>/        generated datasets (git-ignored; see results/README.md)
docs/                    architecture, measurement strategy, how to read results
openspec/                the change that produced the current instrumentation
```

Full command reference: `cd ESP32_Auth_PIO && make help`.
Architecture and endpoint shapes: `docs/Architecture and Endpoints.md`.

### The report

template) and `paper/Final_Report.pdf`. Twelve pages: the **body and references on 1–10**,
then three appendix pages — **A** terminology and notation, **B** the per-phase cost
breakdown and the device dashboard, **C** reproduction steps. Neither renderer contains
prose or numbers of its own, so the two documents cannot drift apart.

`make test-security` runs the rejection tests and writes `security.json` beside the
dataset; the report reads it and says the tests were not run if it is absent.
`make submission` builds the hand-in archive and refuses to produce one that contains the
WiFi credentials from `src/config.h`.

---

## Security notes

- WiFi credentials go in **one file and nowhere else**: `ESP32_Auth_PIO/src/config.h`,
  holding `WIFI_SSID` and `WIFI_PASSWORD`. It is git-ignored. Copy
  `src/config.example.h`, fill it in, and the build proceeds; if it is missing the build
  fails naming the absent fields, so there is no compiled-in fallback to leak.
- An earlier revision committed the credentials, so the repository history still
  contains them. The repository is private and the submitted archive is the working
  tree without `.git`, so they are not distributed. **If it is ever made public, rewrite
  the history and rotate the access-point password first** — deleting a file does not
  revoke a secret already pushed.
- `src/ecc_keys.h` contains a committed P-256 private key. This is a benchmark fixture:
  it authenticates nothing of value, and generating a keypair per cycle would dominate
  the measurement. Do not copy the pattern.
