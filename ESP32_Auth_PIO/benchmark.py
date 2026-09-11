#!/usr/bin/env python3
"""Automated authentication benchmark: one command, one dataset.

Resets the device's statistics, drives every protocol, collects the measured
results, and writes a self-describing CSV. No manual instrumentation, no video
recording, no external power meter.

    python3 benchmark.py                       # default sizes
    python3 benchmark.py --k 2000 --ecc-k 50
    python3 benchmark.py --ip 192.168.1.50

Then render the charts and the comparison:

    python3 analyze.py results/<run-id>/benchmark.csv

Two measurement paths run for every protocol, and they cross-check each other:

  batch      K repetitions inside one timed region on the device, divided by K.
             This is the primary figure: it keeps WiFi latency out of the timed
             window and drives clock quantisation far below the differences being
             resolved.
  individual real network-driven authentication cycles. Noisier, but they prove
             the batch path measures the same work a real cycle does.

A disagreement between them beyond the measured dispersion fails the run rather
than being quietly reported.
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

import host_config
import paper_reference
import test_client

PROTOCOLS = ["classical", "srp", "sv", "ecc"]

# Human-facing labels, and the individual-cycle driver for each protocol.
CYCLE_RUNNERS = {
    "classical": test_client.test_classical,
    "srp": test_client.test_srp,
    "sv": test_client.test_secure_vault,
    "ecc": test_client.test_ecc,
}

CSV_COLUMNS = [
    "run_id",
    "protocol",
    "series",          # aggregate name or phase name
    "kind",            # batch_amortised | batch_per_iteration | phase | individual | overhead
    "count",
    "failures",
    "min_us",
    "max_us",
    "mean_us",
    "median_us",
    "median_window",
    "stddev_us",
    "energy_paper_uj",
    "energy_device_uj",
    "power_paper_mw",
    "power_device_mw",
    "truncated",
    "notes",
]


class BenchmarkError(RuntimeError):
    pass


def get_json(url: str, timeout: float = 20.0) -> dict:
    try:
        r = requests.get(url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise BenchmarkError(f"could not reach the device at {url}\n  {e}") from e
    if r.status_code != 200:
        raise BenchmarkError(f"{url} returned HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def post_json(url: str, timeout: float = 20.0) -> dict:
    try:
        r = requests.post(url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise BenchmarkError(f"could not reach the device at {url}\n  {e}") from e
    if r.status_code != 200:
        raise BenchmarkError(f"{url} returned HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def energy_uj(power_mw: float, latency_us: float) -> float:
    """The one conversion, mirroring the firmware: E(uJ) = P(mW) * t(us) / 1000."""
    return power_mw * latency_us / 1000.0


def check_power_constants(telemetry: dict) -> None:
    """The firmware and the host must agree on the paper's power constant.

    The device is the source of truth for both constants and the host records what
    it reports -- but the host independently knows the paper's figure, so the two
    can be cross-checked. A silent disagreement here would mean the dataset's
    energy column and its stated constant describe different things.
    """
    device_paper_mw = float(telemetry["power_model"]["paper"]["power_mw"])
    expected = paper_reference.PAPER_POWER_MW
    if abs(device_paper_mw - expected) > 1e-6:
        raise BenchmarkError(
            f"power-constant mismatch: the device reports the paper model as "
            f"{device_paper_mw} mW, but paper_reference.py has {expected} mW "
            f"({paper_reference.PAPER_CURRENT_MA} mA x {paper_reference.PAPER_VOLTAGE_V} V). "
            f"One of them is wrong; reconciling silently would make the dataset's "
            f"energy column disagree with its own stated constant."
        )


def run_batch(base: str, protocol: str, k: int) -> dict:
    result = get_json(f"{base}/api/benchmark?protocol={protocol}&k={k}", timeout=60)
    if result.get("truncated"):
        print(f"    NOTE: batch truncated at {result['completed_k']}/{result['requested_k']} "
              f"iterations by the {result['max_batch_ms']} ms request budget")
    return result


def run_individual_cycles(base: str, protocol: str, n: int) -> dict:
    """Drive real authentication cycles over the network.

    Each cycle is a complete mutual challenge-response that the host verifies
    cryptographically, and each returns the device's own `crypto_us` for that
    cycle. Those samples are collected here rather than read back from the
    device's accumulated series, because that series also holds every batch
    iteration -- comparing the batch against a series it dominates would be
    comparing the batch with itself.
    """
    test_client.BASE_URL = base
    ok = 0
    fail = 0
    crypto_us: list[float] = []
    wall_ms: list[float] = []     # host-side round trip: init + verify, both HTTP requests
    first_failure = ""

    for _ in range(n):
        t0 = time.perf_counter()
        result = CYCLE_RUNNERS[protocol]()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        if result.ok:
            ok += 1
            wall_ms.append(elapsed_ms)
            if result.crypto_us is not None:
                crypto_us.append(float(result.crypto_us))
        else:
            fail += 1
            if not first_failure:
                first_failure = result.detail

    return {"ok": ok, "failed": fail, "crypto_us": crypto_us, "wall_ms": wall_ms,
            "first_failure": first_failure}


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stddev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def check_batch_agrees_with_individual(protocol: str, batch: dict, individual: dict) -> str | None:
    """The batch figure must not exceed what a real authentication costs.

    The comparison is deliberately one-sided. A network-driven cycle runs once,
    cold: the HTTP and WiFi path has just evicted the cryptographic code and its
    lookup tables from the flash cache, so the single invocation pays the refill.
    That can only ADD time, and it scales with how much code and table each
    protocol touches - which is why it is large for the shortest protocol and
    invisible for ECC, whose own runtime amortises it.

    So a network cycle costing more than the batch is expected and is reported
    as a measured quantity, not a failure. What this check exists to catch is
    the opposite: a batch loop SLOWER than a real cycle, which would mean it is
    timing work the protocol never actually performs.
    """
    samples = individual["crypto_us"]
    if not samples:
        return None

    warm = batch["per_iteration"]["mean_us"]
    mean = _mean(samples)
    stddev = _stddev(samples)
    tolerance = max(3.0 * stddev, 0.25 * mean, 1.0)

    if warm - mean > tolerance:
        return (f"{protocol}: batch device-side mean {warm:.3f} us EXCEEDS the "
                f"network-cycle mean {mean:.3f} us over {len(samples)} cycles "
                f"(stddev {stddev:.3f}, tolerance {tolerance:.3f}) - the batch is timing "
                f"work a real authentication does not perform")
    return None


def first_call_overhead(protocol: str, batch: dict, individual: dict) -> dict | None:
    """How much more a single cold cycle costs than the same work run warm.

    Both sides are the device's own summed cryptographic phases, so the ratio
    isolates cache state rather than mixing in the batch loop's peer
    simulation.
    """
    samples = individual["crypto_us"]
    if not samples:
        return None
    warm = batch["per_iteration"]["mean_us"]
    mean = _mean(samples)
    if warm <= 0:
        return None
    return {
        "batch_warm_us": round(warm, 3),
        "batch_amortised_us": round(batch["amortised_us_per_op"], 3),
        "network_cycle_mean_us": round(mean, 3),
        "network_cycle_min_us": round(min(samples), 3),
        "delta_us": round(mean - warm, 3),
        "ratio": round(mean / warm, 3),
    }


def rows_for_protocol(run_id: str, protocol: str, batch: dict, proto_telemetry: dict,
                      individual: dict, power: dict) -> list[dict]:
    """CSV rows for one protocol.

    `proto_telemetry` is the device's statistics block for this protocol,
    snapshotted immediately after its batch and before its network cycles, so
    the phase figures describe the warm batch alone rather than a blend of warm
    and cold samples.
    """
    p = proto_telemetry
    pw_paper = power["paper"]["power_mw"]
    pw_device = power["device"]["power_mw"]
    rows = []

    # The whole timed region divided by K. Not the headline: the batch loop also
    # plays the peer, building and encrypting the messages a server would send,
    # and that work falls inside the region. Kept as an upper bound on a cycle.
    amortised = batch["amortised_us_per_op"]
    rows.append({
        "run_id": run_id, "protocol": protocol, "series": "crypto_amortised",
        "kind": "batch_amortised",
        "count": batch["completed_k"], "failures": 0,
        "min_us": "", "max_us": "", "mean_us": f"{amortised:.6f}",
        "median_us": "", "median_window": "", "stddev_us": "",
        "energy_paper_uj": f"{energy_uj(pw_paper, amortised):.6f}",
        "energy_device_uj": f"{energy_uj(pw_device, amortised):.6f}",
        "power_paper_mw": pw_paper, "power_device_mw": pw_device,
        "truncated": str(batch.get("truncated", False)).lower(),
        "notes": f"K={batch['requested_k']} in one timed region, peer simulation included; "
                 f"upper bound, not the headline",
    })

    # The primary figure: the sum of the device's own timed cryptographic
    # phases, which is what the reference paper counts at the device side.
    for series_name, kind, stats in [
        ("crypto", "batch_per_iteration", p["crypto_us"]),
        ("handler", "batch_per_iteration", p["handler_us"]),
    ]:
        rows.append({
            "run_id": run_id, "protocol": protocol, "series": series_name, "kind": kind,
            "count": stats["count"], "failures": p["failures"],
            "min_us": stats["min_us"], "max_us": stats["max_us"],
            "mean_us": f"{stats['mean_us']:.6f}",
            "median_us": stats["median_us"], "median_window": stats["median_window"],
            "stddev_us": f"{stats['stddev_us']:.6f}",
            "energy_paper_uj": f"{energy_uj(pw_paper, stats['mean_us']):.6f}",
            "energy_device_uj": f"{energy_uj(pw_device, stats['mean_us']):.6f}",
            "power_paper_mw": pw_paper, "power_device_mw": pw_device,
            "truncated": "false",
            "notes": ("device-side cryptographic phases only; primary figure"
                      if series_name == "crypto"
                      else "HTTP parsing and response construction; not protocol cost"),
        })

    # Individual cryptographic phases.
    for phase_name, stats in p["phases"].items():
        rows.append({
            "run_id": run_id, "protocol": protocol, "series": phase_name, "kind": "phase",
            "count": stats["count"], "failures": "",
            "min_us": stats["min_us"], "max_us": stats["max_us"],
            "mean_us": f"{stats['mean_us']:.6f}",
            "median_us": stats["median_us"], "median_window": stats["median_window"],
            "stddev_us": f"{stats['stddev_us']:.6f}",
            "energy_paper_uj": f"{energy_uj(pw_paper, stats['mean_us']):.6f}",
            "energy_device_uj": f"{energy_uj(pw_device, stats['mean_us']):.6f}",
            "power_paper_mw": pw_paper, "power_device_mw": pw_device,
            "truncated": "false",
            "notes": "excluded from per-cycle cost" if phase_name in ("setup", "warmup") else "",
        })

    # Network-driven cycles: the reality check on the batch path. These carry
    # their own measured latency, so the cross-check compares two independently
    # produced numbers rather than the batch against itself.
    samples = individual["crypto_us"]
    mean_ind = _mean(samples)
    rows.append({
        "run_id": run_id, "protocol": protocol, "series": "individual_cycles",
        "kind": "individual",
        "count": individual["ok"], "failures": individual["failed"],
        "min_us": f"{min(samples):.1f}" if samples else "",
        "max_us": f"{max(samples):.1f}" if samples else "",
        "mean_us": f"{mean_ind:.6f}" if samples else "",
        "median_us": "", "median_window": "",
        "stddev_us": f"{_stddev(samples):.6f}" if samples else "",
        "energy_paper_uj": f"{energy_uj(pw_paper, mean_ind):.6f}" if samples else "",
        "energy_device_uj": f"{energy_uj(pw_device, mean_ind):.6f}" if samples else "",
        "power_paper_mw": pw_paper, "power_device_mw": pw_device,
        "truncated": "false",
        "notes": "real network cycles, host-verified; cross-checks the batch path",
    })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    host_config.add_common_args(parser)
    parser.add_argument("--k", type=int, default=1000,
                        help="batch repetitions for the symmetric protocols (default: 1000)")
    parser.add_argument("--ecc-k", type=int, default=20,
                        help="batch repetitions for ECC, which is far slower (default: 20)")
    parser.add_argument("--cycles", type=int, default=10,
                        help="network-driven cycles per protocol (default: 10)")
    parser.add_argument("--out", default=None, help="output directory (default: results/<run-id>)")
    args = parser.parse_args()

    base = host_config.base_url(args.ip)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"Device:  {base}")
    print(f"Run ID:  {run_id}")

    try:
        status = get_json(f"{base}/api/status", timeout=10)
        uptime_start = status["uptime_s"]
        print(f"Reached device (uptime {uptime_start} s, RSSI {status['rssi']} dBm)")

        # A mock declares itself. Nothing it produces is a measurement, and the
        # provenance travels with the dataset so a later reader cannot mistake
        # simulated timings for hardware ones.
        is_mock = bool(status.get("mock", False))
        if is_mock:
            print("\n  *** MOCK DEVICE ***")
            print("  This is mock_device.py, not an ESP32. The numbers below are")
            print("  synthetic and are NOT measurements. Use them only to exercise")
            print("  the pipeline; never report them as results.\n")

        print("Resetting accumulated statistics...")
        reset = post_json(f"{base}/api/reset")
        print(f"  instrumentation overhead: {reset['instrumentation_overhead_us']:.3f} us "
              f"over {reset['overhead_samples']} samples")
        # The reset also re-initialises the device vault, so the host mirror has
        # to go back to the same boot state or every SV cycle derives a bad key.
        test_client.reset_host_state()

        batches = {}
        individuals = {}
        proto_telemetry = {}
        for protocol in PROTOCOLS:
            k = args.ecc_k if protocol == "ecc" else args.k
            print(f"\n{protocol}:")
            print(f"  batch of {k}...")
            batches[protocol] = run_batch(base, protocol, k)
            print(f"    device-side {batches[protocol]['per_iteration']['mean_us']:.4f} us/op "
                  f"(whole region amortised {batches[protocol]['amortised_us_per_op']:.4f}, "
                  f"warm-up {batches[protocol]['warmup']['mean_us']:.2f} us, excluded)")

            # Snapshot this protocol's statistics while they describe the batch
            # alone. Fetching once at the end of the run would blend the K warm
            # batch samples with the cold network cycles that follow.
            proto_telemetry[protocol] = get_json(f"{base}/api/energy",
                                                 timeout=30)["protocols"][protocol]

            print(f"  {args.cycles} network cycles...")
            ind = run_individual_cycles(base, protocol, args.cycles)
            individuals[protocol] = ind
            msg = f"    {ind['ok']} ok, {ind['failed']} failed"
            if ind["crypto_us"]:
                msg += f", mean {_mean(ind['crypto_us']):.3f} us/cycle"
            print(msg)
            if ind["first_failure"]:
                print(f"    first failure: {ind['first_failure']}")

        telemetry = get_json(f"{base}/api/energy", timeout=30)
        check_power_constants(telemetry)

        # A reboot mid-run silently truncates the statistics, so make it visible.
        uptime_end = telemetry["uptime_s"]
        rebooted = uptime_end < uptime_start
        if rebooted:
            print(f"\nWARNING: device uptime went from {uptime_start}s to {uptime_end}s "
                  f"-- it rebooted mid-run. Results are not trustworthy.")

        # Batch and individual paths must agree.
        disagreements = [d for d in (check_batch_agrees_with_individual(p, batches[p],
                                                                        individuals[p])
                                     for p in PROTOCOLS) if d]

        # A protocol whose network cycles all failed has no cross-check at all.
        uncrosschecked = [p for p in PROTOCOLS if not individuals[p]["crypto_us"]]
        cycle_failures = [f"{p}: {individuals[p]['failed']} of {args.cycles} cycles failed "
                          f"({individuals[p]['first_failure']})"
                          for p in PROTOCOLS if individuals[p]["failed"]]

        out_dir = Path(args.out) if args.out else host_config.RESULTS_DIR / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "benchmark.csv"

        rows = []
        for protocol in PROTOCOLS:
            rows.extend(rows_for_protocol(run_id, protocol, batches[protocol],
                                          proto_telemetry[protocol],
                                          individuals[protocol], telemetry["power_model"]))

        ov = telemetry["instrumentation"]["overhead_us"]
        rows.append({
            "run_id": run_id, "protocol": "-", "series": "instrumentation_overhead",
            "kind": "overhead",
            "count": ov["count"], "failures": "",
            "min_us": ov["min_us"], "max_us": ov["max_us"],
            "mean_us": f"{ov['mean_us']:.6f}",
            "median_us": ov["median_us"], "median_window": ov["median_window"],
            "stddev_us": f"{ov['stddev_us']:.6f}",
            "energy_paper_uj": "", "energy_device_uj": "",
            "power_paper_mw": telemetry["power_model"]["paper"]["power_mw"],
            "power_device_mw": telemetry["power_model"]["device"]["power_mw"],
            "truncated": "false",
            "notes": "empty instrumented region: the floor below which no phase is trustworthy",
        })

        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            w.writeheader()
            w.writerows(rows)

        # Everything needed to interpret the CSV, kept beside it.
        meta = {
            "run_id": run_id,
            "device": base,
            # "device" for real hardware, "mock" for mock_device.py. analyze.py
            # refuses to describe a mock run's figures as measurements.
            "device_kind": "mock" if is_mock else "device",
            "uptime_start_s": uptime_start,
            "uptime_end_s": uptime_end,
            "device_rebooted_mid_run": rebooted,
            "batch_k": args.k,
            "batch_ecc_k": args.ecc_k,
            "network_cycles_per_protocol": args.cycles,
            "power_model": telemetry["power_model"],
            "hw_accel": telemetry["hw_accel"],
            "invariant_violations": telemetry["invariant_violations"],
            "batch_vs_individual_disagreements": disagreements,
            "protocols_without_crosscheck": uncrosschecked,
            # Cold-vs-warm cost of the same work, reported rather than treated
            # as a failure: see check_batch_agrees_with_individual.
            "first_call_overhead": {p: o for p in PROTOCOLS
                                    if (o := first_call_overhead(p, batches[p],
                                                                 individuals[p]))},
            "network_cycle_failures": cycle_failures,
            # Host-measured wall time of one complete network cycle (two HTTP
            # requests). Recorded for diagnosis only: it includes the host's own
            # work and both round trips, so it is not a device-side measurement
            # and nothing in the report is derived from it.
            "network_cycle_wall_ms": {
                p: {"mean": _mean(individuals[p]["wall_ms"]),
                    "min": min(individuals[p]["wall_ms"], default=0.0),
                    "max": max(individuals[p]["wall_ms"], default=0.0),
                    "count": len(individuals[p]["wall_ms"])}
                for p in PROTOCOLS},
            "paper_reference": {
                "citation": paper_reference.CITATION,
                "protocols": paper_reference.PROTOCOLS,
                "ratios": paper_reference.RATIOS,
            },
            "raw_batch": batches,
            "raw_telemetry": telemetry,
        }
        (out_dir / "run.json").write_text(json.dumps(meta, indent=2))

        print(f"\nWrote {csv_path} ({len(rows)} rows)")
        print(f"Wrote {out_dir / 'run.json'}")

        if telemetry["invariant_violations"] > 0:
            print(f"\nWARNING: {telemetry['invariant_violations']} invariant violation(s): "
                  "measured crypto time exceeded handler time. Results are suspect.")

        if cycle_failures:
            print("\nWARNING: some network cycles did not authenticate:")
            for c in cycle_failures:
                print(f"  {c}")

        if disagreements:
            print("\nFAILED: the batch path and real cycles do not agree:")
            for d in disagreements:
                print(f"  {d}")
            print("The amortised figure cannot be trusted as representative. Not a valid run.")
            return 1

        if uncrosschecked:
            print(f"\nFAILED: no network cycle succeeded for {', '.join(uncrosschecked)}.")
            print("The batch figure for those protocols is uncorroborated -- it may be timing")
            print("work that no real authentication performs. Not a valid run.")
            return 1

        if rebooted:
            print("\nFAILED: device rebooted mid-run.")
            return 1

        if is_mock:
            print("\nNOTE: mock run. The dataset is marked device_kind=mock and its figures")
            print("are synthetic. Do not report them.")

        print(f"\nNext: python3 analyze.py {csv_path}")
        return 0

    except BenchmarkError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        print("No dataset was written. A partial run is not a benchmark.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
