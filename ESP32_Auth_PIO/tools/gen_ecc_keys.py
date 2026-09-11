#!/usr/bin/env python3
"""Regenerate the P-256 benchmark key fixtures.

Writes src/ecc_keys.h (device private + public, host public) and ecc_keys.py
(host private + public, device public).

These are BENCHMARK FIXTURES. A committed private key is acceptable only because
it authenticates nothing of value and keeps runs reproducible; per-cycle key
generation would dominate the measurement it exists to take.

    python3 tools/gen_ecc_keys.py
"""

from pathlib import Path

from Crypto.PublicKey import ECC

PROJECT_DIR = Path(__file__).resolve().parent.parent


def fmt_c(name: str, data: bytes, per_line: int = 12) -> str:
    lines = []
    for i in range(0, len(data), per_line):
        chunk = data[i:i + per_line]
        lines.append("    " + " ".join(f"0x{b:02X}," for b in chunk))
    body = "\n".join(lines).rstrip(",")
    return f"static const uint8_t {name}[{len(data)}] = {{\n{body}\n}};"


def pub_uncompressed(key) -> bytes:
    """Public point as 0x04 || X || Y, the form mbedtls_ecp_point_read_binary wants."""
    p = key.pointQ
    return b"\x04" + p.x.to_bytes(32) + p.y.to_bytes(32)


def main() -> None:
    dev = ECC.generate(curve="P-256")
    host = ECC.generate(curve="P-256")

    dev_priv = int(dev.d).to_bytes(32, "big")
    dev_pub = pub_uncompressed(dev)
    host_priv = int(host.d).to_bytes(32, "big")
    host_pub = pub_uncompressed(host)

    header = f'''// P-256 test key material for the ECC authentication benchmark.
//
// GENERATED FIXTURE -- do not treat this as a deployment pattern. A compiled-in
// private key is acceptable here and only here: this is a benchmark, per-cycle
// key generation would dominate the measurement, and runs must be deterministic
// (design.md Decision 7). The matching host-side keys live in ecc_keys.py.
//
// Regenerate with: python3 tools/gen_ecc_keys.py
#pragma once

#include <stdint.h>

// Device private scalar d, 32-byte big-endian.
{fmt_c("ECC_DEVICE_PRIVATE", dev_priv)}

// Device public point Q, uncompressed (0x04 || X || Y).
{fmt_c("ECC_DEVICE_PUBLIC", dev_pub)}

// Host (peer) public point, uncompressed. Used to verify the host's signature.
{fmt_c("ECC_HOST_PUBLIC", host_pub)}
'''
    (PROJECT_DIR / "src" / "ecc_keys.h").write_text(header)

    pymod = f'''"""P-256 test key material for the ECC authentication benchmark (host side).

GENERATED FIXTURE. The device holds the matching keys in src/ecc_keys.h.
A committed private key is acceptable only because this is a benchmark: it
authenticates nothing of value and makes runs reproducible.

Regenerate with: python3 tools/gen_ecc_keys.py
"""

# Host private scalar, 32-byte big-endian hex.
HOST_PRIVATE_HEX = "{host_priv.hex().upper()}"

# Host public point, uncompressed (04 || X || Y).
HOST_PUBLIC_HEX = "{host_pub.hex().upper()}"

# Device public point, uncompressed. Used to verify the device's signature.
DEVICE_PUBLIC_HEX = "{dev_pub.hex().upper()}"
'''
    (PROJECT_DIR / "ecc_keys.py").write_text(pymod)

    print("Wrote src/ecc_keys.h and ecc_keys.py")
    print("Reflash the device after regenerating, or the host and device keys will disagree.")


if __name__ == "__main__":
    main()
