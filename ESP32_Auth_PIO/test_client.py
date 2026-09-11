#!/usr/bin/env python3
"""Host side of the three authentication protocols: real cycles against the device.

Every function here completes an actual challenge-response exchange over HTTP and
verifies the device's reply cryptographically. A cycle counts as successful only
if the device authenticated to us AND we authenticated to it -- returning True
without checking would make the whole "individual cycles cross-check the batch
path" argument vacuous.

    python3 test_client.py                       # one cycle per protocol
    python3 test_client.py --method sv --mode long --iterations 500
    python3 test_client.py --ip 192.168.1.50

Each cycle's device-reported `crypto_us` is returned to the caller and appended to
test_log.csv, so the network path produces a measurement rather than just a
verdict. benchmark.py compares those samples against the batch figure.

Wire formats are fixed by the firmware (src/auth_*.cpp); see
docs/Architecture and Endpoints.md.
"""

import argparse
import csv
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256

import ecc_host
import host_config

# Set by benchmark.py before driving cycles; also resolved from host_config below.
BASE_URL = host_config.base_url()

LOG_FILE = "test_log.csv"
TIMEOUT_S = 20.0

# --- Protocol constants, mirroring the firmware ----------------------------
NUM_KEYS = 16          # auth_sv.h NUM_KEYS
KEY_SIZE = 16          # auth_sv.h KEY_SIZE

# auth_classical.cpp classical_key. A benchmark fixture, not a deployment secret.
CLASSICAL_KEY = bytes.fromhex("2B7E151628AED2A6ABF7158809CF4F3C")

# auth_srp.cpp initSRP(): the boot value of the single rotating password.
SRP_BOOT_KEY = bytes(0xA0 + i for i in range(16))


class ProtocolError(RuntimeError):
    """The device replied, but not in a way the protocol allows."""


@dataclass
class CycleResult:
    """One completed authentication cycle."""
    ok: bool
    crypto_us: float | None = None
    handler_us: float | None = None
    detail: str = ""


# ---------------------------------------------------------------------------
# The vault, mirrored host-side
# ---------------------------------------------------------------------------
# The device rotates its vault after every successful Secure Vault cycle, so the
# host must apply the identical rotation or the next cycle derives the wrong key
# and fails. This mirror is the reason SV is stateful where the other two are not.
class Vault:
    """Host mirror of the device's Secure Vault key material."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """The device's boot state: initSecureVault() sets vault[i][j] = i + j."""
        self.keys = [bytearray((i + j) & 0xFF for j in range(KEY_SIZE))
                     for i in range(NUM_KEYS)]

    def as_bytes(self) -> bytes:
        """Flat layout, matching the device's `secure_vault[NUM_KEYS][KEY_SIZE]`."""
        return b"".join(bytes(k) for k in self.keys)

    def derive(self, indices) -> bytes:
        """XOR the selected vault keys together -- the paper's multi-key derivation."""
        k = bytearray(self.keys[indices[0] % NUM_KEYS])
        for idx in indices[1:]:
            key = self.keys[idx % NUM_KEYS]
            for j in range(KEY_SIZE):
                k[j] ^= key[j]
        return bytes(k)

    def rotate(self, r1: bytes) -> None:
        """Mirror auth_sv.cpp's post-session rotation, exactly.

        HMAC-SHA256 keyed with r1 over the whole vault *before* rotation, then
        vault[i][j] ^= hmac[j] ^ i. Only the first KEY_SIZE bytes of the digest
        are consumed, which is what the firmware does.
        """
        digest = HMAC.new(r1, self.as_bytes(), SHA256).digest()
        for i in range(NUM_KEYS):
            for j in range(KEY_SIZE):
                self.keys[i][j] ^= digest[j] ^ i


vault = Vault()


def new_challenge(exclude=None) -> list[int]:
    """Four distinct vault indices, as the paper requires; never the same set as
    `exclude` (the device's C1), which the device rejects."""
    while True:
        c = random.sample(range(NUM_KEYS), 4)
        if exclude is None or set(c) != set(exclude):
            return c


class RotatingPassword:
    """Host mirror of the single rotating password (auth_srp.cpp).

    Like the vault it is stateful: both sides replace the password after every
    successful session, so a client that starts mid-stream cannot authenticate.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.key = SRP_BOOT_KEY


srp = RotatingPassword()


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _get(path: str) -> dict:
    r = requests.get(f"{BASE_URL}{path}", timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise ProtocolError(f"GET {path} -> HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _post_hex(path: str, body_hex: str, sid: int | None = None) -> dict:
    # text/plain, not form-encoded: the firmware reads the raw body via
    # server.arg("plain"), which WebServer only populates for non-form bodies.
    # The session identifier travels as a query parameter so the body stays the
    # protocol's own bytes; only the request holding it consumes the session.
    url = f"{BASE_URL}{path}" + (f"?sid={sid}" if sid is not None else "")
    r = requests.post(url, data=body_hex,
                      headers={"Content-Type": "text/plain"}, timeout=TIMEOUT_S)
    if r.status_code != 200:
        raise ProtocolError(f"POST {path} -> HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _aes_ecb(key: bytes):
    return AES.new(key, AES.MODE_ECB)


def _timings(resp: dict) -> tuple[float | None, float | None]:
    return resp.get("crypto_us"), resp.get("handler_us")


# ---------------------------------------------------------------------------
# Classical AES-128 challenge-response
# ---------------------------------------------------------------------------
def test_classical() -> CycleResult:
    """Mutual challenge-response under one shared AES-128 key.

    The device issues a challenge; we answer with AES-128-ECB(challenge) and
    append a challenge of our own. The device decrypts to verify us, then
    encrypts our challenge to prove it holds the key -- the two AES operations
    the reference paper's Table 1 charges to its classical scheme. We verify
    the device's reply, so a device that skipped the second operation would
    fail the cycle rather than silently under-report its cost.
    """
    try:
        init = _get("/api/auth/classical/init")
        challenge = bytes.fromhex(init["challenge"])
        if len(challenge) != 16:
            raise ProtocolError(f"expected a 16-byte challenge, got {len(challenge)}")

        our_challenge = os.urandom(16)
        response = _aes_ecb(CLASSICAL_KEY).encrypt(challenge)
        reply = _post_hex("/api/auth/classical/verify",
                          (response + our_challenge).hex().upper(), init["sid"])

        if reply.get("status") != "success":
            return CycleResult(False, detail=f"device rejected: {reply}")

        expected = _aes_ecb(CLASSICAL_KEY).encrypt(our_challenge)
        if bytes.fromhex(reply["response"]) != expected:
            return CycleResult(False, detail="device reply did not authenticate")

        crypto_us, handler_us = _timings(reply)
        return CycleResult(True, crypto_us, handler_us)
    except (ProtocolError, requests.RequestException, ValueError, KeyError) as e:
        return CycleResult(False, detail=str(e))


# ---------------------------------------------------------------------------
# Secure Vault
# ---------------------------------------------------------------------------
def test_secure_vault() -> CycleResult:
    """The paper's mutual challenge-response over a rotating multi-key vault.

    init  -> C1 (four vault indices) and r1
    M3     = AES-ECB_k1( r1 || t1 || C2 || pad || r2 ),  k1 = XOR of vault[C1]
    M4     = AES-ECB_{k2 ^ t1}( r2 || t2 ),              k2 = XOR of vault[C2]

    Recovering r2 from M4 is what authenticates the device: only a peer holding
    the same vault could have produced it. Both sides then rotate the vault.
    """
    try:
        init = _get("/api/auth/sv/init")
        c1 = list(init["C1"])
        r1 = bytes.fromhex(init["r1"])
        if len(c1) != 4 or len(r1) != 16:
            raise ProtocolError(f"malformed init: C1={c1}, len(r1)={len(r1)}")

        k1 = vault.derive(c1)

        # M3 layout is fixed by auth_sv.cpp's offsets: r1 at 0, t1 at 16,
        # C2 at 32 (4 bytes), r2 at 48. Bytes 36..48 are unused padding.
        t1 = os.urandom(16)
        c2 = bytes(new_challenge(exclude=c1))
        r2 = os.urandom(16)
        plaintext = r1 + t1 + c2 + os.urandom(12) + r2
        m3 = _aes_ecb(k1).encrypt(plaintext)

        reply = _post_hex("/api/auth/sv/verify", m3.hex().upper(), init["sid"])
        if reply.get("status") != "success":
            return CycleResult(False, detail=f"device rejected: {reply}")

        # Verify the device's half: decrypt M4 and check it returned our r2.
        k2 = vault.derive(list(c2))
        enc_key = bytes(a ^ b for a, b in zip(k2, t1))
        m4 = bytes.fromhex(reply["M4"])
        if len(m4) != 32:
            raise ProtocolError(f"expected a 32-byte M4, got {len(m4)}")
        recovered = _aes_ecb(enc_key).decrypt(m4)
        if recovered[:16] != r2:
            return CycleResult(False, detail="M4 did not carry back r2: device not authenticated")

        # Both sides rotate only after a cycle that fully succeeded.
        vault.rotate(r1)

        crypto_us, handler_us = _timings(reply)
        return CycleResult(True, crypto_us, handler_us)
    except (ProtocolError, requests.RequestException, ValueError, KeyError) as e:
        return CycleResult(False, detail=str(e))


# ---------------------------------------------------------------------------
# ECC (ECDSA P-256)
# ---------------------------------------------------------------------------
def test_ecc() -> CycleResult:
    """Mutual ECDSA: the device signs our challenge and verifies our signature.

    The device's per-cycle cost is one sign plus one verify, which is what makes
    it comparable in structure to the two symmetric protocols.
    """
    try:
        init = _get("/api/auth/ecc/init")
        device_challenge = bytes.fromhex(init["challenge"])
        if len(device_challenge) != ecc_host.CHALLENGE_LEN:
            raise ProtocolError(f"expected a 32-byte challenge, got {len(device_challenge)}")

        body_hex, host_challenge = ecc_host.build_verify_body(device_challenge)
        reply = _post_hex("/api/auth/ecc/verify", body_hex.upper(), init["sid"])

        if reply.get("status") != "success":
            return CycleResult(False, detail=f"device rejected: {reply}")

        signature = bytes.fromhex(reply["signature"])
        if not ecc_host.verify_device(host_challenge, signature):
            return CycleResult(False, detail="device signature invalid: device not authenticated")

        crypto_us, handler_us = _timings(reply)
        return CycleResult(True, crypto_us, handler_us)
    except (ProtocolError, requests.RequestException, ValueError, KeyError) as e:
        return CycleResult(False, detail=str(e))


def test_srp() -> CycleResult:
    """The paper's own baseline: one password, rotated after every session.

    Three AES-128 operations on the device, which is what the paper costs it at:
    it verifies our response to its challenge, answers ours, and recovers the
    next password we sent encrypted under the current one.
    """
    try:
        init = _get("/api/auth/srp/init")
        device_challenge = bytes.fromhex(init["challenge"])
        if len(device_challenge) != 16:
            raise ProtocolError(f"expected a 16-byte challenge, got {len(device_challenge)}")

        host_challenge = os.urandom(16)
        next_key = os.urandom(16)
        cipher = _aes_ecb(srp.key)
        body = cipher.encrypt(device_challenge) + host_challenge + cipher.encrypt(next_key)

        reply = _post_hex("/api/auth/srp/verify", body.hex().upper(), init["sid"])
        if reply.get("status") != "success":
            return CycleResult(False, detail=f"device rejected: {reply}")

        # The device answered under the OLD password, before rotating.
        answer = bytes.fromhex(reply["response"])
        if _aes_ecb(srp.key).decrypt(answer) != host_challenge:
            return CycleResult(False, detail="reply did not carry back our challenge")

        srp.key = next_key          # rotate only after a fully successful cycle

        crypto_us, handler_us = _timings(reply)
        return CycleResult(True, crypto_us, handler_us)
    except (ProtocolError, requests.RequestException, ValueError, KeyError) as e:
        return CycleResult(False, detail=str(e))


RUNNERS = {
    "classical": test_classical,
    "srp": test_srp,
    "sv": test_secure_vault,
    "ecc": test_ecc,
}


def reset_host_state() -> None:
    """Re-sync the host mirror with a device that has just been reset or rebooted.

    POST /api/reset re-initialises the device vault, so the host copy must go back
    to the same boot state or every subsequent SV cycle derives the wrong key.
    """
    vault.reset()
    srp.reset()


# ---------------------------------------------------------------------------
# Logging and CLI
# ---------------------------------------------------------------------------
def log_event(method: str, result: CycleResult) -> None:
    new_file = not os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["timestamp", "method", "status", "crypto_us", "handler_us", "detail"])
        w.writerow([
            datetime.now().strftime("%H:%M:%S.%f")[:-3],
            method,
            "Success" if result.ok else "Fail",
            f"{result.crypto_us:.0f}" if result.crypto_us is not None else "",
            f"{result.handler_us:.0f}" if result.handler_us is not None else "",
            result.detail,
        ])


def run_cycle(method: str) -> CycleResult:
    result = RUNNERS[method]()
    log_event(method, result)
    return result


def long_run(method: str, iterations: int | None, delay: float) -> int:
    methods = list(RUNNERS) if method == "both" else [method]
    print(f"Long run: {', '.join(methods)} -> {LOG_FILE}")

    completed = 0
    failed = 0
    try:
        while iterations is None or completed < iterations:
            for m in methods:
                result = run_cycle(m)
                if not result.ok:
                    failed += 1
                    print(f"  FAIL [{m}] {result.detail}")
                    # A desynced vault or a dead device fails every subsequent
                    # cycle; stop rather than filling the log with noise.
                    if failed >= 5:
                        print("  5 consecutive-ish failures, aborting.")
                        return completed
            completed += 1
            if completed % 10 == 0:
                print(f"[{datetime.now():%H:%M:%S}] {completed} iterations")
            if delay > 0:
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    print(f"Completed {completed} iterations ({failed} failed cycles)")
    return completed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    host_config.add_common_args(parser)
    parser.add_argument("--mode", choices=["single", "long"], default="single")
    parser.add_argument("--method", choices=["sv", "classical", "srp", "ecc", "both"], default="both")
    parser.add_argument("--iterations", type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.05)
    parser.add_argument("--no-reset", action="store_true",
                        help="do not reset the device first (keeps its accumulated statistics, "
                             "but Secure Vault cycles will fail unless the vault happens to be "
                             "in its boot state)")
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = host_config.base_url(args.ip)
    print(f"Device: {BASE_URL}")

    # The device rotates its vault on every successful SV cycle, so a client that
    # starts mid-stream cannot derive the right key. Resetting puts both sides
    # back at the documented boot state.
    if not args.no_reset:
        try:
            requests.post(f"{BASE_URL}/api/reset", timeout=TIMEOUT_S).raise_for_status()
            reset_host_state()
        except requests.RequestException as e:
            print(f"Could not reset the device: {e}")
            return 1

    if args.mode == "long":
        return 0 if long_run(args.method, args.iterations, args.delay) else 1

    methods = list(RUNNERS) if args.method == "both" else [args.method]
    failures = 0
    for m in methods:
        result = run_cycle(m)
        if result.ok:
            print(f"{m:10s} OK    crypto {result.crypto_us} us, handler {result.handler_us} us")
        else:
            failures += 1
            print(f"{m:10s} FAIL  {result.detail}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
