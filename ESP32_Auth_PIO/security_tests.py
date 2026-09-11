#!/usr/bin/env python3
"""Rejection tests: requests the device must refuse, for every protocol.

The benchmark proves the success path: a peer holding the right key material
authenticates. This proves the failure path: a replayed message, a forged
response under the wrong key, a tampered message, a request out of session
order, and a malformed body are each refused, and a genuine cycle still
succeeds afterwards. The device's own failure counters are read before and
after, so the rejections are corroborated on the device side too.

    python3 security_tests.py                # against $ESP32_IP / host_config default
    python3 security_tests.py --ip 192.168.1.62 --out ../results/<run-id>

Writes security.json into the newest dataset directory (or --out) so the report
can cite it beside the measurements. Exits non-zero if any case fails.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from Crypto.Hash import SHA256
from Crypto.PublicKey import ECC
from Crypto.Signature import DSS

import ecc_host
import host_config
import test_client
from test_client import CLASSICAL_KEY, _aes_ecb, new_challenge, srp, vault

TIMEOUT_S = 20.0
PROTOCOLS = ["classical", "srp", "sv", "ecc"]
LABELS = {"classical": "Classical AES-128", "srp": "Rotating password",
          "sv": "Secure Vault", "ecc": "ECC (ECDSA P-256)"}


class Device:
    def __init__(self, base: str) -> None:
        self.base = base

    def get(self, path: str):
        r = requests.get(self.base + path, timeout=TIMEOUT_S)
        return r.status_code, _json(r)

    def post(self, path: str, body_hex: str, sid=None):
        url = self.base + path + (f"?sid={sid}" if sid is not None else "")
        r = requests.post(url, data=body_hex,
                          headers={"Content-Type": "text/plain"}, timeout=TIMEOUT_S)
        return r.status_code, _json(r)

    def failures(self) -> dict:
        _, t = self.get("/api/energy")
        return {p: t["protocols"][p]["failures"] for p in PROTOCOLS}

    def kind(self) -> str:
        _, st = self.get("/api/status")
        return "mock" if st.get("mock") else "device"


def _json(r):
    try:
        return r.json()
    except ValueError:
        return {"raw": r.text[:200]}


# ---------------------------------------------------------------------------
# Genuine cycles, mirroring test_client.py but returning the body sent, so a
# later case can replay it. Each keeps the host mirrors in sync on success.
# ---------------------------------------------------------------------------
def genuine_classical(dev, init=None):
    if init is None:
        _, init = dev.get("/api/auth/classical/init")
    body = _aes_ecb(CLASSICAL_KEY).encrypt(bytes.fromhex(init["challenge"])) + os.urandom(16)
    code, reply = dev.post("/api/auth/classical/verify", body.hex(), init["sid"])
    return code, reply, body.hex()


def genuine_srp(dev, init=None):
    if init is None:
        _, init = dev.get("/api/auth/srp/init")
    next_key = os.urandom(16)
    c = _aes_ecb(srp.key)
    body = c.encrypt(bytes.fromhex(init["challenge"])) + os.urandom(16) + c.encrypt(next_key)
    code, reply = dev.post("/api/auth/srp/verify", body.hex(), init["sid"])
    if code == 200:
        srp.key = next_key
    return code, reply, body.hex()


def build_m3(init, key_vault, c2=None, flip_bit=False):
    c1 = list(init["C1"])
    r1 = bytes.fromhex(init["r1"])
    k1 = key_vault.derive(c1)
    c2 = bytes(c2 if c2 is not None else new_challenge(exclude=c1))
    plain = r1 + os.urandom(16) + c2 + os.urandom(12) + os.urandom(16)
    m3 = bytearray(_aes_ecb(k1).encrypt(plain))
    if flip_bit:
        m3[0] ^= 0x01
    return bytes(m3), r1


def genuine_sv(dev, init=None):
    if init is None:
        _, init = dev.get("/api/auth/sv/init")
    m3, r1 = build_m3(init, vault)
    code, reply = dev.post("/api/auth/sv/verify", m3.hex(), init["sid"])
    if code == 200:
        vault.rotate(r1)
    return code, reply, m3.hex()


def genuine_ecc(dev, init=None):
    if init is None:
        _, init = dev.get("/api/auth/ecc/init")
    body_hex, _ = ecc_host.build_verify_body(bytes.fromhex(init["challenge"]))
    code, reply = dev.post("/api/auth/ecc/verify", body_hex, init["sid"])
    return code, reply, body_hex


GENUINE = {"classical": genuine_classical, "srp": genuine_srp,
           "sv": genuine_sv, "ecc": genuine_ecc}


# ---------------------------------------------------------------------------
# Rejection cases. Each returns (http_status, cause).
# ---------------------------------------------------------------------------
def case_replay(dev, p):
    """A body that authenticated once is sent again against a fresh challenge."""
    code, _, body = GENUINE[p](dev)
    assert code == 200, f"{p}: genuine cycle failed before the replay could be tried"
    _, init = dev.get(f"/api/auth/{p}/init")
    return dev.post(f"/api/auth/{p}/verify", body, init["sid"])


def case_wrong_key(dev, p):
    """A response computed under key material the device does not hold."""
    if p == "classical":
        _, init = dev.get("/api/auth/classical/init")
        body = _aes_ecb(os.urandom(16)).encrypt(bytes.fromhex(init["challenge"])) + os.urandom(16)
        return dev.post("/api/auth/classical/verify", body.hex(), init["sid"])
    if p == "srp":
        _, init = dev.get("/api/auth/srp/init")
        c = _aes_ecb(os.urandom(16))
        body = c.encrypt(bytes.fromhex(init["challenge"])) + os.urandom(16) + c.encrypt(os.urandom(16))
        return dev.post("/api/auth/srp/verify", body.hex(), init["sid"])
    if p == "sv":
        # A vault that never rotated: valid key material once, stale now.
        _, init = dev.get("/api/auth/sv/init")
        m3, _ = build_m3(init, test_client.Vault())
        return dev.post("/api/auth/sv/verify", m3.hex(), init["sid"])
    if p == "ecc":
        _, init = dev.get("/api/auth/ecc/init")
        rogue = ECC.generate(curve="P-256")
        sig = DSS.new(rogue, "fips-186-3").sign(SHA256.new(bytes.fromhex(init["challenge"])))
        return dev.post("/api/auth/ecc/verify", (os.urandom(32) + sig).hex(), init["sid"])
    raise ValueError(p)


def case_tampered(dev, p):
    """A genuine body with one bit flipped in the authenticating field."""
    if p == "sv":
        _, init = dev.get("/api/auth/sv/init")
        m3, _ = build_m3(init, vault, flip_bit=True)
        return dev.post("/api/auth/sv/verify", m3.hex(), init["sid"])
    if p == "ecc":
        _, init = dev.get("/api/auth/ecc/init")
        body_hex, _ = ecc_host.build_verify_body(bytes.fromhex(init["challenge"]))
        body = bytearray(bytes.fromhex(body_hex))
        body[40] ^= 0x01                       # inside the signature
        return dev.post("/api/auth/ecc/verify", body.hex(), init["sid"])
    _, init = dev.get(f"/api/auth/{p}/init")
    key = CLASSICAL_KEY if p == "classical" else srp.key
    resp = bytearray(_aes_ecb(key).encrypt(bytes.fromhex(init["challenge"])))
    resp[0] ^= 0x01
    tail = os.urandom(16) if p == "classical" else os.urandom(16) + _aes_ecb(key).encrypt(os.urandom(16))
    return dev.post(f"/api/auth/{p}/verify", (bytes(resp) + tail).hex(), init["sid"])


def case_c2_equals_c1(dev, p):
    """Secure Vault only: C2 selecting the same keys as C1, which the paper forbids."""
    _, init = dev.get("/api/auth/sv/init")
    m3, _ = build_m3(init, vault, c2=list(init["C1"]))
    return dev.post("/api/auth/sv/verify", m3.hex(), init["sid"])


def case_c2_repeated_index(dev, p):
    """Secure Vault only: C2 with a repeated index."""
    _, init = dev.get("/api/auth/sv/init")
    c2 = new_challenge(exclude=list(init["C1"]))
    c2[1] = c2[0]
    m3, _ = build_m3(init, vault, c2=c2)
    return dev.post("/api/auth/sv/verify", m3.hex(), init["sid"])


def case_no_session(dev, p):
    """A verify carrying a session identifier the device never issued."""
    lengths = {"classical": 32, "srp": 48, "sv": 64, "ecc": 96}
    return dev.post(f"/api/auth/{p}/verify", os.urandom(lengths[p]).hex(), 0xDEADBEEF)


def case_malformed(dev, p):
    """A body too short to be the protocol's message, under a valid session."""
    _, init = dev.get(f"/api/auth/{p}/init")
    return dev.post(f"/api/auth/{p}/verify", "00" * 8, init["sid"])


def case_cannot_cancel_peer(dev, p):
    """An attacker must not be able to cancel someone else's pending session.

    A legitimate peer opens a session; an attacker posts garbage under an
    identifier it does not hold; the peer then completes. The attacker's request
    is what this case reports, and the peer's success is asserted, because a
    refusal that also destroyed the peer's session would be no better than the
    single-session design this replaced.
    """
    _, victim = dev.get(f"/api/auth/{p}/init")
    lengths = {"classical": 32, "srp": 48, "sv": 64, "ecc": 96}
    code, reply = dev.post(f"/api/auth/{p}/verify",
                           os.urandom(lengths[p]).hex(), 0x5EC0FFEE)
    # The victim finishes with its OWN identifier: that is what proves the
    # attacker's request left the pending session untouched.
    done, dreply, _ = GENUINE[p](dev, victim)
    assert done == 200, (f"{p}: the attacker's request cancelled a pending "
                         f"session -- the peer then got {done} {dreply}")
    return code, reply


# (name, function, expected HTTP status, expected cause, protocols, rejected
#  requests the case issues -- the malformed case also closes the session it
#  opened with a second request the device refuses)
CASES = [
    ("replay",        case_replay,            401, "verification_failed", PROTOCOLS, 1),
    ("wrong key",     case_wrong_key,         401, "verification_failed", PROTOCOLS, 1),
    ("tampered",      case_tampered,          401, "verification_failed", PROTOCOLS, 1),
    ("C2 = C1",       case_c2_equals_c1,      401, "bad_challenge",       ["sv"], 1),
    ("C2 repeats",    case_c2_repeated_index, 401, "bad_challenge",       ["sv"], 1),
    ("no session",    case_no_session,        400, "no_session",          PROTOCOLS, 1),
    ("malformed",     case_malformed,         400, "malformed_request",   PROTOCOLS, 1),
    ("peer safe",     case_cannot_cancel_peer, 400, "no_session",          PROTOCOLS, 1),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    host_config.add_common_args(parser)
    parser.add_argument("--out", default=None,
                        help="directory to write security.json into (default: newest dataset)")
    args = parser.parse_args()

    base = host_config.base_url(args.ip)
    test_client.BASE_URL = base
    dev = Device(base)
    print(f"Device: {base}")

    requests.post(f"{base}/api/reset", timeout=TIMEOUT_S).raise_for_status()
    test_client.reset_host_state()
    kind = dev.kind()
    before = dev.failures()

    results = []
    expected_failures = {p: 0 for p in PROTOCOLS}
    for name, fn, exp_code, exp_cause, protocols, rejected in CASES:
        for p in protocols:
            code, reply = fn(dev, p)
            cause = (reply or {}).get("cause", "")
            ok = (code == exp_code and cause == exp_cause)
            expected_failures[p] += rejected
            results.append({"protocol": p, "case": name, "expected_http": exp_code,
                            "expected_cause": exp_cause, "http": code, "cause": cause,
                            "pass": ok})
            print(f"  {'PASS' if ok else 'FAIL'}  {LABELS[p]:20s} {name:12s} -> {code} {cause}")

    # After every rejection a genuine cycle must still succeed, host-verified.
    recovery = {}
    for p in PROTOCOLS:
        r = test_client.RUNNERS[p]()
        recovery[p] = bool(r.ok)
        print(f"  {'PASS' if r.ok else 'FAIL'}  {LABELS[p]:20s} genuine after rejections "
              f"-> {'authenticated' if r.ok else r.detail}")

    after = dev.failures()
    counters = {p: {"before": before[p], "after": after[p],
                    "expected_delta": expected_failures[p],
                    "agrees": after[p] - before[p] == expected_failures[p]}
                for p in PROTOCOLS}
    for p in PROTOCOLS:
        c = counters[p]
        print(f"  {'PASS' if c['agrees'] else 'FAIL'}  {LABELS[p]:20s} device failure counter "
              f"{c['before']} -> {c['after']} (expected +{c['expected_delta']})")

    all_ok = all(r["pass"] for r in results) and all(recovery.values()) \
        and all(c["agrees"] for c in counters.values())

    out_dir = Path(args.out) if args.out else _newest_dataset_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "device": base, "device_kind": kind,
        "cases": results, "recovery": recovery, "device_failure_counters": counters,
        "all_passed": all_ok,
    }
    (out_dir / "security.json").write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {out_dir / 'security.json'}  ({'all passed' if all_ok else 'FAILURES'})")
    return 0 if all_ok else 1


def _newest_dataset_dir() -> Path:
    dirs = sorted(d for d in host_config.RESULTS_DIR.glob("*/") if (d / "benchmark.csv").exists())
    if dirs:
        return dirs[-1]
    return host_config.RESULTS_DIR / ("security-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))


if __name__ == "__main__":
    sys.exit(main())
