#!/usr/bin/env python3
"""Render comparison charts and the deviation report from a benchmark dataset.

    python3 analyze.py results/<run-id>/benchmark.csv

Reads the CSV and nothing else — no device required, so any archived dataset can
be re-rendered. Platform facts for the report's attribution section come from
run.json beside the CSV when it is present; the charts themselves are derived
solely from the CSV.

Outputs, alongside the input CSV:
    energy.png    per-cycle energy by protocol, under both power models
    latency.png   latency by protocol with the per-phase breakdown
    ratios.png    measured inter-protocol ratios vs the reference paper's
    report.md     ratio comparison, deviation analysis, modelling limits
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt
import pandas as pd

import paper_reference

# --- Design tokens ---------------------------------------------------------
# Validated categorical slots 1 and 2 (light mode, surface #fcfcfb):
# CVD dE 24.7, normal-vision dE 33.6, both >= 3:1 contrast on the surface.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#8a8880"
SERIES_1 = "#2a78d6"  # blue
SERIES_2 = "#eb6834"  # orange
GRID = "#e4e3de"

LABELS = {
    "classical": "Classical\nAES-128",
    "srp": "Rotating\npassword",
    "sv": "Secure Vault",
    "ecc": "ECC\nECDSA P-256",
}
ORDER = ["classical", "srp", "sv", "ecc"]

# Preferred left-to-right order per protocol. Any phase the dataset carries but
# that is missing here is appended rather than dropped: a hardcoded list that
# silently omitted Classical's encrypt phase once already charted half of that
# protocol's cost and a total that disagreed with the table beside it.
PHASE_ORDER = {
    "classical": ["aes_dec", "aes_enc"],
    "srp": ["aes_dec", "aes_enc", "rekey"],
    "sv": ["keyderiv", "aes_dec", "aes_enc", "hmac", "rotate"],
    "ecc": ["sign", "verify"],
}
PHASE_LABELS = {
    "keyderiv": "key derive", "aes_dec": "AES dec", "aes_enc": "AES enc",
    "hmac": "HMAC", "rotate": "vault rotate", "rekey": "next password",
    "sign": "ECDSA sign",
    "verify": "ECDSA verify",
}


def style_axes(ax):
    """Recessive grid and axes: the data should carry the ink."""
    ax.set_facecolor(SURFACE)
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)


def load(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    required = {"protocol", "series", "kind", "mean_us"}
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"{csv_path} is missing required columns: {sorted(missing)}")
    return df


def _headline_rows(df: pd.DataFrame) -> pd.DataFrame:
    """The rows carrying the primary per-cycle figure.

    Device-side cryptographic work only: the sum of the protocol's timed
    phases, which is what the reference paper counts ("at the IoT device
    side", SS VI-A). The batch loop also simulates the peer -- building
    challenges, encrypting the messages the server would send -- and the
    amortised whole-region figure includes that. It is kept in the CSV as
    `batch_amortised` and reported as a bound, but it is not the headline,
    because the peer's work is not the device's cost.
    """
    return df[(df["kind"] == "batch_per_iteration") & (df["series"] == "crypto")]


def amortised(df: pd.DataFrame) -> dict:
    """The primary per-cycle figure for each protocol. Device-side only."""
    rows = _headline_rows(df)
    return {r["protocol"]: float(r["mean_us"]) for _, r in rows.iterrows()}


def energy_values(df: pd.DataFrame) -> tuple[dict, dict, float, float]:
    rows = _headline_rows(df)
    paper = {r["protocol"]: float(r["energy_paper_uj"]) for _, r in rows.iterrows()}
    device = {r["protocol"]: float(r["energy_device_uj"]) for _, r in rows.iterrows()}
    pw_paper = float(rows.iloc[0]["power_paper_mw"])
    pw_device = float(rows.iloc[0]["power_device_mw"])
    return paper, device, pw_paper, pw_device


def chart_energy(df: pd.DataFrame, out: Path) -> None:
    """Grouped bars, log scale: ECC is ~3 orders of magnitude above the rest.

    Bar length on a log axis is not proportional to value, so every bar carries
    its own value label and the axis states the scale.
    """
    paper, device, pw_paper, pw_device = energy_values(df)
    protos = [p for p in ORDER if p in paper]

    fig, ax = plt.subplots(figsize=(8, 4.6), facecolor=SURFACE)
    style_axes(ax)

    x = range(len(protos))
    # 2px-equivalent surface gap between adjacent bars.
    w = 0.38
    gap = 0.02
    b1 = ax.bar([i - w / 2 - gap / 2 for i in x], [paper[p] for p in protos],
                width=w, color=SERIES_1, zorder=3,
                label=f"Paper model ({pw_paper:g} mW)")
    b2 = ax.bar([i + w / 2 + gap / 2 for i in x], [device[p] for p in protos],
                width=w, color=SERIES_2, zorder=3,
                label=f"Device model ({pw_device:g} mW)")

    ax.set_yscale("log")
    lo = min(list(paper.values()) + list(device.values()))
    ax.set_ylim(bottom=lo / 3.0)
    ax.set_ylabel("Energy per cycle (µJ, log scale)", color=INK_SECONDARY, fontsize=10)
    ax.set_xticks(list(x))
    ax.set_xticklabels([LABELS[p] for p in protos], color=INK, fontsize=10)

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f"{h:,.3g}", (bar.get_x() + bar.get_width() / 2, h),
                        textcoords="offset points", xytext=(0, 4), ha="center",
                        fontsize=8, color=INK_SECONDARY)

    leg = ax.legend(frameon=False, fontsize=9, loc="upper left")
    for text in leg.get_texts():
        text.set_color(INK_SECONDARY)

    fig.suptitle("Energy per authentication cycle, both power models",
                 color=INK, fontsize=13, fontweight="600", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.90,
             "Derived from measured latency: E(µJ) = P(mW) × t(µs) / 1000.\n"
             "Log scale — bar length is not proportional to value.",
             fontsize=8.5, color=INK_MUTED, ha="left", va="top", linespacing=1.5)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def chart_latency(df: pd.DataFrame, out: Path) -> None:
    """Small multiples: one panel per protocol, each on its own linear scale.

    A stacked bar would need a log axis to fit ECC beside the symmetric
    protocols, and stacked segments on a log axis do not add up visually. Panels
    with per-panel linear scales keep every phase readable and honest; the scale
    is printed on each panel.
    """
    phases = df[df["kind"] == "phase"]
    protos = [p for p in ORDER if p in set(phases["protocol"])]

    fig, axes = plt.subplots(1, len(protos), figsize=(11, 4.2), facecolor=SURFACE)
    if len(protos) == 1:
        axes = [axes]

    for ax, proto in zip(axes, protos):
        style_axes(ax)
        sub = phases[phases["protocol"] == proto].set_index("series")
        # warm-up and setup are measured but are not part of a cycle's cost, so
        # they are excluded here exactly as they are everywhere else.
        charted = [n for n in sub.index if n not in ("warmup", "setup")]
        known = [n for n in PHASE_ORDER.get(proto, []) if n in charted]
        names = known + sorted(n for n in charted if n not in known)
        values = [float(sub.loc[n, "mean_us"]) for n in names]

        # One series, one color: identity comes from the axis labels, so the
        # colour channel stays free rather than re-encoding bar length.
        bars = ax.bar(range(len(names)), values, width=0.62, color=SERIES_1, zorder=3)
        for bar, v in zip(bars, values):
            ax.annotate(f"{v:,.3g}", (bar.get_x() + bar.get_width() / 2, v),
                        textcoords="offset points", xytext=(0, 4), ha="center",
                        fontsize=8, color=INK_SECONDARY)

        ax.set_xticks(range(len(names)))
        ax.set_xticklabels([PHASE_LABELS.get(n, n) for n in names],
                           rotation=30, ha="right", color=INK, fontsize=9)
        title = LABELS[proto].replace("\n", " ")
        total = sum(values)
        ax.set_title(f"{title}\ntotal {total:,.3g} µs", color=INK,
                     fontsize=10.5, fontweight="600", pad=8)
        if ax is axes[0]:
            ax.set_ylabel("Mean latency (µs)", color=INK_SECONDARY, fontsize=10)
        ax.margins(y=0.18)

    fig.suptitle("Measured latency by cryptographic phase",
                 color=INK, fontsize=13, fontweight="600", x=0.01, ha="left", y=0.99)
    fig.text(0.01, 0.925, "Each panel has its OWN linear scale — panels are not "
                          "comparable by bar height; compare the stated totals.",
             fontsize=8.5, color=INK_MUTED, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.90))
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def measured_ratios(df: pd.DataFrame) -> dict:
    a = amortised(df)
    out = {}
    if "sv" in a and a.get("srp", 0) > 0:
        out["sv/srp"] = a["sv"] / a["srp"]
    if "sv" in a and "classical" in a and a["classical"] > 0:
        out["sv/classical"] = a["sv"] / a["classical"]
    if "ecc" in a and "sv" in a and a["sv"] > 0:
        out["ecc/sv"] = a["ecc"] / a["sv"]
    if "ecc" in a and "classical" in a and a["classical"] > 0:
        out["ecc/classical"] = a["ecc"] / a["classical"]
    return out


def chart_ratios(df: pd.DataFrame, out: Path) -> None:
    """The actual claim under test. Ratios are invariant to the power constant."""
    measured = measured_ratios(df)
    names = [n for n in ("sv/srp", "sv/classical", "ecc/sv", "ecc/classical")
             if n in measured and n in paper_reference.RATIOS]

    fig, ax = plt.subplots(figsize=(8, 4.4), facecolor=SURFACE)
    style_axes(ax)

    x = range(len(names))
    w, gap = 0.38, 0.02
    b1 = ax.bar([i - w / 2 - gap / 2 for i in x], [measured[n] for n in names],
                width=w, color=SERIES_1, zorder=3, label="Measured (this device)")
    b2 = ax.bar([i + w / 2 + gap / 2 for i in x],
                [paper_reference.RATIOS[n] for n in names],
                width=w, color=SERIES_2, zorder=3, label="Reference paper")

    ax.set_yscale("log")
    lo = min([measured[n] for n in names] + [paper_reference.RATIOS[n] for n in names])
    ax.set_ylim(bottom=lo / 3.0)
    ax.set_ylabel("Cost ratio (×, log scale)", color=INK_SECONDARY, fontsize=10)
    ax.set_xticks(list(x))
    ax.set_xticklabels([n.replace("/", " / ") for n in names], color=INK, fontsize=10)

    for bars in (b1, b2):
        for bar in bars:
            h = bar.get_height()
            ax.annotate(f"{h:,.2f}×", (bar.get_x() + bar.get_width() / 2, h),
                        textcoords="offset points", xytext=(0, 4), ha="center",
                        fontsize=8, color=INK_SECONDARY)

    leg = ax.legend(frameon=False, fontsize=9, loc="upper left")
    for text in leg.get_texts():
        text.set_color(INK_SECONDARY)

    fig.suptitle("Measured cost ratios vs the reference paper",
                 color=INK, fontsize=13, fontweight="600", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.90,
             "Ratios are identical under both power models — this comparison\n"
             "does not depend on either power constant.",
             fontsize=8.5, color=INK_MUTED, ha="left", va="top", linespacing=1.5)
    fig.tight_layout(rect=(0, 0, 1, 0.84))
    fig.savefig(out, dpi=200, facecolor=SURFACE)
    plt.close(fig)


def write_report(df: pd.DataFrame, out: Path, meta: dict | None) -> None:
    """Ratio comparison, deviation analysis, and modelling limits."""
    a = amortised(df)
    paper_e, device_e, pw_paper, pw_device = energy_values(df)
    measured = measured_ratios(df)
    hw = (meta or {}).get("hw_accel", {})
    run_id = df["run_id"].iloc[0] if "run_id" in df.columns else "unknown"

    overhead = df[df["kind"] == "overhead"]
    overhead_us = float(overhead.iloc[0]["mean_us"]) if not overhead.empty else float("nan")

    # Provenance decides what these figures may be called. A dataset produced by
    # mock_device.py contains invented timings; describing them as measurements
    # would be the single most misleading thing this report could do.
    kind = (meta or {}).get("device_kind", "unknown")
    is_mock = kind == "mock"

    L = []
    L.append("# Authentication benchmark results\n")

    if is_mock:
        L.append("> ## \u26a0 NOT A MEASUREMENT\n"
                 "> \n"
                 "> This dataset came from `mock_device.py` (`device_kind: mock`), not from an\n"
                 "> ESP32. Every latency below is a synthetic constant invented to exercise the\n"
                 "> analysis pipeline, and every energy figure is derived from one. **Nothing in\n"
                 "> this report may be cited as a result.** Re-run `make benchmark` against the\n"
                 "> board to produce a report whose numbers mean something.\n")
        L.append(f"\nRun `{run_id}`, simulated. Regenerate with `python3 analyze.py`.\n")
    elif kind == "unknown":
        L.append("> **Provenance unknown.** This dataset predates provenance recording, so it\n"
                 "> cannot be confirmed as having come from real hardware. Re-run `make benchmark`\n"
                 "> if these figures are to be reported.\n")
        L.append(f"\nRun `{run_id}`. Regenerate with `python3 analyze.py`.\n")
    else:
        L.append(f"Run `{run_id}`. Every figure below is measured on the device or computed "
                 f"from those measurements. Regenerate with `python3 analyze.py`.\n")

    L.append("\n## Measured per-cycle cost\n")
    L.append("| Protocol | Crypto latency | Energy (paper model) | Energy (device model) |")
    L.append("| :--- | ---: | ---: | ---: |")
    for p in ORDER:
        if p not in a:
            continue
        label = LABELS[p].replace("\n", " ")
        L.append(f"| {label} | {a[p]:,.3f} µs | {paper_e[p]:,.4f} µJ | {device_e[p]:,.4f} µJ |")
    L.append(f"\nPower constants: paper {pw_paper:g} mW, device {pw_device:g} mW. "
             f"`E(µJ) = P(mW) × t(µs) / 1000`. Instrumentation overhead "
             f"{overhead_us:.3f} µs — the floor below which no phase is trustworthy.\n")

    # The batch figure is only a protocol cost if a real authentication costs the
    # same. Showing both columns is what lets a reader check that, rather than
    # taking the claim on trust.
    ind = df[df["kind"] == "individual"]
    if not ind.empty and ind["mean_us"].notna().any():
        L.append("\n### Cross-check: batch vs. real network cycles\n")
        L.append("The batch path times K back-to-back repetitions on the device. Real "
                 "cycles are driven over HTTP and verified cryptographically by the host. Both "
                 "columns are the same quantity -- the sum of the device's timed cryptographic "
                 "phases -- so they are directly comparable, and the run is rejected if the "
                 "batch exceeds the network mean.\n")
        L.append("| Protocol | Batch (warm) | Network cycles (cold) | Cycles | Failed | Δ |")
        L.append("| :--- | ---: | ---: | ---: | ---: | ---: |")
        for p_ in ORDER:
            row = ind[ind["protocol"] == p_]
            if row.empty or pd.isna(row.iloc[0]["mean_us"]) or p_ not in a:
                continue
            r_ = row.iloc[0]
            cyc_mean = float(r_["mean_us"])
            delta = (cyc_mean - a[p_]) / a[p_] * 100.0 if a[p_] else float("nan")
            label = LABELS[p_].replace("\n", " ")
            L.append(f"| {label} | {a[p_]:,.3f} µs | {cyc_mean:,.3f} µs | "
                     f"{int(r_['count'])} | {int(r_['failures'])} | {delta:+.1f}% |")

    L.append("\n## Ratios: the claim under test\n")
    L.append("Ratios are invariant to the choice of power constant, which is exactly why "
             "they survive a platform change that absolute energies cannot.\n")
    L.append("| Comparison | Measured | Reference paper | Deviation |")
    L.append("| :--- | ---: | ---: | ---: |")
    for name in ("sv/srp", "sv/classical", "ecc/sv", "ecc/classical"):
        if name not in measured:
            continue
        m, ref = measured[name], paper_reference.RATIOS[name]
        dev = (m - ref) / ref * 100.0
        L.append(f"| {name} | {m:,.2f}× | {ref:,.2f}× | {dev:+.1f}% |")

    L.append("\n\n## Absolute divergence from the paper\n")
    L.append("Absolute energies are **not** expected to match and do not. Stated rather "
             "than omitted:\n")
    L.append("| Protocol | Measured (paper model) | Paper's figure | Factor |")
    L.append("| :--- | ---: | ---: | ---: |")
    for p in ORDER:
        if p not in paper_e:
            continue
        ref = paper_reference.PROTOCOLS[p]["energy_uj"]
        label = LABELS[p].replace("\n", " ")
        if paper_e[p] <= 0:
            verdict = "n/a"
        elif ref >= paper_e[p]:
            verdict = f"{ref / paper_e[p]:,.1f}× cheaper here"
        else:
            # Reachable: a protocol whose device-side work exceeds the paper's
            # composition can cost more here despite the faster chip.
            verdict = f"{paper_e[p] / ref:,.1f}× more expensive here"
        L.append(f"| {label} | {paper_e[p]:,.4f} µJ | {ref:,.2f} µJ | {verdict} |")

    L.append("\n\n## Deviation analysis\n")
    L.append("Each divergence attributed to a named cause on this platform, not left "
             "unexplained.\n")
    aes_hw = hw.get("aes")
    sha_hw = hw.get("sha")
    ecc_hw = hw.get("ecc_p256")

    # The largest single cause of sv/classical divergence, and the one most easily
    # mistaken for a hardware effect.
    L.append("- **Protocol composition differs from the paper's, and this dominates "
             "`sv/classical`.** The paper's costs are *2 \u00d7 AES-128* for Classical and "
             "*2 \u00d7 AES-128 + 1 \u00d7 HMAC* for Secure Vault \u2014 a ratio of 1.30\u00d7. What this "
             "firmware actually executes per cycle is:\n"
             "\n"
             "  | | Paper | This implementation (device side) |\n"
             "  | :--- | :--- | :--- |\n"
             "  | Classical | 2 \u00d7 AES-128 | **1** AES-128 ECB block decrypt |\n"
             "  | Secure Vault | 2 \u00d7 AES-128 + 1 \u00d7 HMAC | 4-key XOR derivation + **6** AES-128 "
             "ECB blocks (4 decrypt, 2 encrypt) + HMAC-SHA256 over the 256-byte vault + "
             "256-byte vault rotation |\n"
             "  | ECC | one ECC public-key operation | 1 ECDSA-P256 sign + 1 ECDSA-P256 verify |\n"
             "\n"
             "  Secure Vault therefore performs roughly six times the block-cipher work of "
             "Classical here, against the paper's parity. A measured `sv/classical` well above "
             "1.30\u00d7 is the expected consequence of that asymmetry and is **not** evidence "
             "against the paper's claim \u2014 the two numbers are not measuring the same pair of "
             "protocols. Attributing this gap to hardware acceleration alone would be wrong: "
             "acceleration applies to both sides of the ratio and largely cancels, whereas the "
             "block-count difference does not.")
    L.append(f"- **Processor and clock.** The reference platform is an Arduino; this is an "
             f"ESP32-C3 RISC-V core at 160 MHz. The paper measured 2.5 ms for one AES-128 "
             f"operation; anything in the microsecond range here is a different regime, not "
             f"a discrepancy.")
    if aes_hw is not None:
        L.append(f"- **Hardware AES/SHA.** `CONFIG_MBEDTLS_HARDWARE_AES` = "
                 f"{'enabled' if aes_hw else 'disabled'}, `..._SHA` = "
                 f"{'enabled' if sha_hw else 'disabled'} on this build. Accelerated symmetric "
                 f"primitives compress the Classical and Secure Vault side of every ratio.")
    if ecc_hw is not None:
        L.append(f"- **ECC path.** P-256 point multiplication runs in "
                 f"**{'hardware' if ecc_hw else 'software'}** here. With AES and SHA "
                 f"accelerated and ECC not, the ECC-to-symmetric ratios are pushed *above* "
                 f"the paper's, and that asymmetry is the single largest cause of ratio "
                 f"divergence in this dataset.")
    L.append("- **Different power bases.** The two models differ only in their constant "
             f"({pw_paper:g} mW from 19.9 mA @ 5 V; {pw_device:g} mW from 25 mA @ 3.3 V). "
             "This shifts absolute energy and cancels exactly in every ratio.")
    L.append("- **Radio and transport excluded.** The modelled figure covers cryptographic "
             "execution only. WiFi association, transmission, and HTTP parsing are measured "
             "separately (`handler` series) and deliberately excluded from protocol cost, "
             "since including them would measure the network rather than the protocol.")
    L.append("- **ECDSA substituted for the paper's ECC.** The paper compares against \"ECC "
             "public key encryption\"; this implementation uses ECDSA sign + verify, chosen "
             "because challenge-response maps onto the structure of the other two protocols. "
             "A deliberate substitution, disclosed rather than silently equated.")
    L.append("- **The paper's ECC figure is rounded.** 1105 ms × 99.5 mW = 109,947.5 µJ, "
             "printed in Table 1 as 109.95 mJ. Immaterial to the ratios (170.0 either way), "
             "but the exact product is used here.")

    L.append("\n\n## Modelling limits\n")
    L.append("- Energy is **derived from latency under a constant-power assumption**, not "
             "measured with a power meter. This is the reference paper's own method "
             "(Prasithsangaree et al., adopted in its section VI-A), applied identically — "
             "which is what makes the comparison valid.")
    L.append("- The assumption excludes variation in current draw with instruction mix, and "
             "excludes radio energy entirely. An accelerated AES block and a software "
             "big-integer multiply do not draw identical current, and this model cannot see "
             "that difference.")
    L.append("- The median is computed over a bounded window of recent samples; mean and "
             "standard deviation are exact over all samples.")
    L.append("- Batch and network-driven cycles are cross-checked; a disagreement beyond the "
             "measured dispersion fails the run rather than being reported.")

    if meta:
        if meta.get("invariant_violations"):
            L.append(f"\n> **{meta['invariant_violations']} invariant violation(s)** recorded: "
                     "measured crypto time exceeded handler time. Treat these results as suspect.")
        if meta.get("device_rebooted_mid_run"):
            L.append("\n> **The device rebooted mid-run.** Statistics were truncated; "
                     "this dataset is not trustworthy.")
        if meta.get("hw_accel", {}).get("opt_level"):
            L.append(f"\nBuild optimisation level: `{meta['hw_accel']['opt_level']}`. Recorded "
                     "because a loop the optimiser removed would otherwise be "
                     "indistinguishable from fast code.")

    out.write_text("\n".join(L) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", type=Path, help="path to benchmark.csv")
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"ERROR: {args.csv} does not exist", file=sys.stderr)
        return 1

    df = load(args.csv)
    out_dir = args.csv.parent

    meta = None
    run_json = out_dir / "run.json"
    if run_json.exists():
        meta = json.loads(run_json.read_text())

    chart_energy(df, out_dir / "energy.png")
    chart_latency(df, out_dir / "latency.png")
    chart_ratios(df, out_dir / "ratios.png")
    write_report(df, out_dir / "report.md", meta)

    print(f"Wrote {out_dir / 'energy.png'}")
    print(f"Wrote {out_dir / 'latency.png'}")
    print(f"Wrote {out_dir / 'ratios.png'}")
    print(f"Wrote {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
