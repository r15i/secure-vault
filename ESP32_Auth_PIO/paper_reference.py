"""Reference figures from the paper this project implements.

  Gupta, M. and Kumaraguru, P., "Authentication of IoT Device and IoT Server
  Using Secure Vaults", IEEE TrustCom/BigDataSE 2018, pp. 819-824.
  DOI 10.1109/TrustCom/BigDataSE.2018.00117

Section VI-A states the method (Prasithsangaree et al.): total energy = average
current x supply voltage x execution time. Their platform is an Arduino drawing
19.9 mA at 5 V = 99.5 mW. Table 1 lists the per-operation times and energies.

Everything here is a LITERATURE VALUE, never a measurement. It exists to be
compared against, not to be reported as a result.
"""

CITATION = (
    "Gupta & Kumaraguru, Authentication of IoT Device and IoT Server Using "
    "Secure Vaults, IEEE TrustCom/BigDataSE 2018, Table 1 and section VI-A"
)

# The paper's platform.
PAPER_CURRENT_MA = 19.9
PAPER_VOLTAGE_V = 5.0
PAPER_POWER_MW = PAPER_CURRENT_MA * PAPER_VOLTAGE_V  # 99.5 mW

# Per-operation figures from Table 1: latency in ms, energy in uJ.
OPERATIONS = {
    "aes128": {"latency_ms": 2.5, "energy_uj": 248.75},
    "hmac": {"latency_ms": 1.5, "energy_uj": 149.25},
    "aes256": {"latency_ms": 4.0, "energy_uj": 398.0},
    "ecc": {"latency_ms": 1105.0, "energy_uj": 109947.5},
}

# Composite protocol costs, as the paper describes them in section VI-A:
#   Classical    = 2 AES-128 operations                  -> 497.50 uJ
#   Secure Vault = 2 AES-128 operations + 1 HMAC         -> 646.75 uJ
#   ECC          = the asymmetric baseline               -> 109947.50 uJ
#
# NOTE on the ECC figure: 1105 ms x 99.5 mW = 109,947.5 uJ. Table 1 prints this
# rounded to 109.95 mJ. The firmware previously hardcoded 109950.0 uJ -- the
# rounded value read back as though it were exact. The 2.5 uJ difference is
# immaterial to the ratios (170.0 either way) but the exact product is used here
# so that "reproduce the paper's arithmetic" has one unambiguous answer.
# The paper's own headline comparison, in its Figure 3, is NOT against the plain
# two-AES scheme: it is against a single rotating password, which also changes
# key material after each session and therefore offers a comparable security
# guarantee. Section VI-A: "Single rotating password-based scheme requires 3 AES
# operations, first two AES operation for authentication and the last one for the
# exchanging new password using previous password as encryption key."
#   3 x 248.75 = 746.25 uJ, which is the value Figure 3 plots.
# Against that baseline Secure Vault is CHEAPER (646.75 / 746.25 = 0.87x), because
# it replaces the third AES with one HMAC. Comparing only against the two-AES
# scheme measures the cost of rotation against no rotation at all.
SINGLE_ROTATING_PASSWORD = {
    "energy_uj": 746.25,
    "composition": "3 x AES-128",
    "note": "the paper's Figure 3 baseline; rotates key material, unlike 'classical'",
}

PROTOCOLS = {
    "classical": {
        "energy_uj": 497.5,
        "latency_ms": 5.0,
        "composition": "2 x AES-128",
    },
    "sv": {
        "energy_uj": 646.75,
        "latency_ms": 6.5,
        "composition": "2 x AES-128 + 1 x HMAC-SHA256",
    },
    "srp": {
        "energy_uj": SINGLE_ROTATING_PASSWORD["energy_uj"],
        "latency_ms": 3 * OPERATIONS["aes128"]["latency_ms"],
        "composition": SINGLE_ROTATING_PASSWORD["composition"],
        "note": SINGLE_ROTATING_PASSWORD["note"],
    },
    "ecc": {
        "energy_uj": 109947.5,
        "latency_ms": 1105.0,
        "composition": "ECC public-key authentication",
    },
}

# The claim under test. Ratios are invariant to the power constant, which is what
# makes them comparable across platforms with different absolute performance.
RATIOS = {
    # The paper's own Figure 3 comparison: Secure Vault against the scheme that
    # also rotates key material. Below 1.0 means Secure Vault is the cheaper.
    "sv/srp": PROTOCOLS["sv"]["energy_uj"] / SINGLE_ROTATING_PASSWORD["energy_uj"],
    "sv/classical": PROTOCOLS["sv"]["energy_uj"] / PROTOCOLS["classical"]["energy_uj"],
    "ecc/sv": PROTOCOLS["ecc"]["energy_uj"] / PROTOCOLS["sv"]["energy_uj"],
    "ecc/classical": PROTOCOLS["ecc"]["energy_uj"] / PROTOCOLS["classical"]["energy_uj"],
}


def ratio_table() -> str:
    lines = [f"Reference ratios ({CITATION}):"]
    for name, value in RATIOS.items():
        lines.append(f"  {name:16s} {value:10.2f}x")
    return "\n".join(lines)


if __name__ == "__main__":
    print(f"Paper platform: {PAPER_CURRENT_MA} mA @ {PAPER_VOLTAGE_V} V = {PAPER_POWER_MW} mW")
    for name, p in PROTOCOLS.items():
        print(f"  {name:10s} {p['energy_uj']:12.2f} uJ  {p['latency_ms']:8.1f} ms  ({p['composition']})")
    print()
    print(ratio_table())
