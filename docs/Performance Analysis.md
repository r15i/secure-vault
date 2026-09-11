# Performance Analysis

**This file holds no numbers.** Measured figures live in `results/<run-id>/report.md`,
which `analyze.py` regenerates from a dataset, and in `paper/Final_Report.pdf`, which
`report_content.py` builds from the same dataset. A tracked copy of the numbers would go
stale the moment a new run happened — and a stale copy that still reads as current is how
this project once came to publish the reference paper's own values as though it had
measured them.

```bash
cd ESP32_Auth_PIO
make benchmark DEVICE_IP=<ip>   # run against the board -> results/<run-id>/
make plot                       # re-render charts + report.md from the newest dataset
make report                     # rebuild paper/Final_Report.{docx,pdf}
```

## Before trusting any figure

Check `device_kind` in `results/<run-id>/run.json`:

| Value | Meaning |
| :--- | :--- |
| `device` | A real ESP32-C3. Reportable. |
| `mock` | `mock_device.py`. Synthetic constants, **not measurements**. |
| `unknown` | Predates provenance recording. Re-run before reporting. |

Also check `invariant_violations` is `0`, `batch_vs_individual_disagreements` and
`protocols_without_crosscheck` are empty, and `device_rebooted_mid_run` is `false`.
`benchmark.py` exits non-zero on all of these and `generate_report.py` refuses to render
a run that failed them, so a run that produced a report has already passed.

## What was found

Four protocols are measured: Classical AES-128, the paper's single rotating password,
Secure Vault, and ECDSA P-256. **The ordering reproduces; no quantitative claim does.**
The comparison the paper leads with — Secure Vault against the rotating password, its
Figure 3 — comes out *reversed*: dearer here, where the paper has it cheaper.

Three causes, in order of size. All are argued in the report.

**1. The paper's cost model ignores message size.** Table 1 charges 248.75 µJ per AES-128
operation however many blocks that operation covers. Counted its way this implementation
matches the paper exactly — one decryption and one encryption per Secure Vault cycle. But
the protocol of §IV encrypts M3 (`r1 || t1 || C2 || r2`, four blocks) and M4
(`r2 || t2`, two blocks): six blocks executed, two operations billed. The rotating
password's three operations are single blocks, so it is billed at cost. Re-costing both
per block with the paper's own figures gives sv/srp = **2.20×** instead of 0.87× — most
of the reversal is implied by the paper's own data.

**2. Part of the protocol is billed as nothing.** Deriving the session key from the four
selected vault keys and rotating all sixteen afterwards is about 8% of a Secure Vault
cycle. Table 1 charges the vault update as one HMAC operation and has no row for the XOR
work on either side of it.

**3. Acceleration is asymmetric here.** AES and SHA run on hardware, P-256 does not. That
inflates every symmetric-versus-asymmetric ratio, and inverts the relation the paper's
argument depends on: an HMAC costs 0.60× an AES operation on its Arduino, and 4.1× an AES
block here.

There is no baseline mismatch on this side: since 2026-09-11 Classical performs the two AES
operations the paper counts, and the rotating password matches its three. The report leans
on the rotating password because it is the only baseline that also rotates key material.

## What the measurement does and does not cover

Energy is **derived**, never instrumented: `E = P × t / 1000` at two declared power
constants. This is the reference paper's own method (Prasithsangaree et al., §VI-A),
which is what makes the comparison valid. See `Measurement_Strategy_and_Hardware.md` for
why a USB power meter and an INA219 were both rejected — and note that the deeper reason
is scope: a meter measures the board, where the object of study is the algorithm.

The model cannot see current draw varying with instruction mix, and excludes radio energy
entirely; in a deployment the radio would dominate all four protocols. The `handler`
series measures HTTP parsing and response construction separately and is not part of
protocol cost.

## Two measurement paths, and why they differ

The batch path runs K repetitions inside one timed region on-chip; network cycles are
real authentications the host verifies. The harness rejects a run where the batch is
*slower* than a real cycle, which would mean it is timing work the protocol never does.

A cold cycle costing *more* than the warm batch is expected and is reported rather than
failed: each network cycle runs once, right after the HTTP and WiFi path has evicted the
cryptographic code and its tables from the flash cache. Radio interference was ruled out
twice — the cold samples are far too tightly clustered for scheduler preemption, and the
gap is unchanged after improving the link from −89 to −70 dBm.
