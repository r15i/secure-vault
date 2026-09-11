#!/usr/bin/env python3
"""A functional stand-in for the ESP32, for exercising the harness without hardware.

    python3 mock_device.py        # serves on 127.0.0.1:5000

This implements the device side of all four authentication protocols for real:
it derives the same keys, performs the same AES / HMAC / ECDSA operations, and
rotates the vault exactly as the firmware does. A cycle driven against it either
authenticates or fails for the same reasons it would against the board, which is
the whole point -- a mock that always answered "success" would let a broken
client look correct.

WHAT IT IS NOT
--------------
The *timings* it reports are invented. They are plausible for an ESP32-C3 with
hardware AES/SHA and software P-256, but they are not measurements of anything.
Every response carries `"mock": true` on /api/status, benchmark.py stamps
`device_kind: "mock"` into run.json, and analyze.py refuses to describe such a
run's figures as measured. Nothing produced here may be reported as a result.

An earlier version of this file returned the reference paper's own published
numbers, which made the analysis print "+0.0% deviation" from the paper and read
as a perfect reproduction. The synthetic figures below are deliberately unlike
the paper's, so that a mock run can never be mistaken for a successful one.
"""

import re
import secrets
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256
from Crypto.PublicKey import ECC
from Crypto.Signature import DSS
from flask import Flask, jsonify, request

import ecc_keys

app = Flask(__name__)

NUM_KEYS = 16
KEY_SIZE = 16
CLASSICAL_KEY = bytes.fromhex("2B7E151628AED2A6ABF7158809CF4F3C")

# --- Synthetic timings -----------------------------------------------------
# Invented, not measured. Shapes chosen to reflect what this chip plausibly does:
# AES and SHA are hardware-accelerated, P-256 is not. Per-phase microseconds.
PHASES = {
    "classical": {"aes_dec": 21.0, "aes_enc": 19.0},
    "srp": {"aes_dec": 21.0, "aes_enc": 19.0, "rekey": 20.0},
    "sv": {"keyderiv": 3.0, "aes_dec": 31.0, "aes_enc": 24.0, "hmac": 46.0, "rotate": 8.0},
    "ecc": {"sign": 7100.0, "verify": 13400.0},
}
HANDLER_OVERHEAD_US = {"classical": 780.0, "srp": 810.0, "sv": 940.0, "ecc": 1150.0}
# Work the batch loop does on the peer's behalf, inside the timed region but
# outside the device's own phases: building challenges and encrypting the
# messages a server would have sent.
PEER_SIM_US = {"classical": 12.0, "srp": 24.0, "sv": 38.0, "ecc": 9.0}
OVERHEAD_US = 1.4          # cost of an empty instrumented region
JITTER = 0.03              # +/- 3%, so stddev is not identically zero


def crypto_us(protocol: str) -> float:
    return sum(PHASES[protocol].values())


def jitter(value: float) -> float:
    return value * (1.0 + (secrets.randbelow(2001) - 1000) / 1000.0 * JITTER)


def stats(mean: float, count: int = 10) -> dict:
    spread = mean * JITTER
    return {
        "count": count,
        "min_us": round(max(0.0, mean - spread), 3),
        "max_us": round(mean + spread, 3),
        "mean_us": round(mean, 3),
        "median_us": round(mean, 3),
        "median_window": 256,
        "stddev_us": round(spread / 2.0, 3),
    }


# --- Device ECC key, read from the firmware's own fixture ------------------
def _load_device_private() -> ECC.EccKey:
    """Parse ECC_DEVICE_PRIVATE out of src/ecc_keys.h.

    Read from the header rather than duplicated here, so the mock cannot drift
    away from the key the firmware actually holds.
    """
    header = (Path(__file__).resolve().parent / "src" / "ecc_keys.h").read_text()
    match = re.search(r"ECC_DEVICE_PRIVATE\[32\]\s*=\s*\{(.*?)\}", header, re.S)
    if not match:
        raise RuntimeError("could not find ECC_DEVICE_PRIVATE in src/ecc_keys.h")
    data = bytes(int(b, 16) for b in re.findall(r"0x([0-9A-Fa-f]{2})", match.group(1)))
    if len(data) != 32:
        raise RuntimeError(f"expected a 32-byte device scalar, got {len(data)}")
    return ECC.construct(curve="P-256", d=int.from_bytes(data, "big"))


DEVICE_KEY = _load_device_private()


def _host_public_key() -> ECC.EccKey:
    raw = bytes.fromhex(ecc_keys.HOST_PUBLIC_HEX)
    return ECC.construct(curve="P-256",
                         point_x=int.from_bytes(raw[1:33], "big"),
                         point_y=int.from_bytes(raw[33:65], "big"))


HOST_KEY = _host_public_key()


# --- Device state ----------------------------------------------------------
class State:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.vault = [bytearray((i + j) & 0xFF for j in range(KEY_SIZE))
                      for i in range(NUM_KEYS)]
        self.sessions = {}
        # Boot value matches initSRP() in src/auth_srp.cpp.
        self.srp_key = bytes(range(0xA0, 0xA0 + KEY_SIZE))
        self.counts = {p: {"count": 0, "failures": 0} for p in PHASES}

    def vault_bytes(self) -> bytes:
        return b"".join(bytes(k) for k in self.vault)

    def derive(self, indices) -> bytes:
        k = bytearray(self.vault[indices[0] % NUM_KEYS])
        for idx in indices[1:]:
            key = self.vault[idx % NUM_KEYS]
            for j in range(KEY_SIZE):
                k[j] ^= key[j]
        return bytes(k)

    def rotate(self, r1: bytes) -> None:
        digest = HMAC.new(r1, self.vault_bytes(), SHA256).digest()
        for i in range(NUM_KEYS):
            for j in range(KEY_SIZE):
                self.vault[i][j] ^= digest[j] ^ i


state = State()


def ecb(key: bytes):
    return AES.new(key, AES.MODE_ECB)


SESSION_SLOTS = 4          # mirrors SESSION_SLOTS in src/sessions.h


def open_session(protocol: str, payload):
    """Store a pending session under a random identifier and return it.

    Mirrors sessionOpen(): a bounded number of slots per protocol, oldest
    evicted, so an attacker calling /init cannot push out a legitimate peer
    beyond the slot count.
    """
    slots = state.sessions.setdefault(protocol, {})
    if len(slots) >= SESSION_SLOTS:
        slots.pop(next(iter(slots)))
    sid = secrets.randbits(32) or 1
    slots[sid] = payload
    return sid


def take_session(protocol: str):
    """Consume the session whose identifier this request carries, or None.

    A request without the right identifier removes nothing, which is the whole
    point: it cannot cancel a peer that holds one.
    """
    try:
        sid = int(request.args.get("sid", "0"))
    except ValueError:
        return None
    return state.sessions.get(protocol, {}).pop(sid, None)


def body_hex() -> str:
    return request.get_data(as_text=True).strip()


def auth_reply(protocol: str, extra: dict) -> dict:
    """The success envelope every auth handler returns, matching the firmware."""
    state.counts[protocol]["count"] += 1
    c = jitter(crypto_us(protocol))
    h = c + HANDLER_OVERHEAD_US[protocol]
    return {
        "status": "success",
        "crypto_us": round(c, 3),
        "handler_us": round(h, 3),
        "energy_uj": {"paper": round(99.5 * c / 1000, 4), "device": round(82.5 * c / 1000, 4)},
        **extra,
    }


def fail(protocol: str, code: int, error: str, cause: str):
    state.counts[protocol]["failures"] += 1
    return jsonify({"status": "failed", "error": error, "cause": cause}), code


# --- Monitoring ------------------------------------------------------------
@app.route("/")
def dashboard():
    """Serve the firmware's own dashboard, parsed out of src/dashboard.h.

    Read from the header rather than duplicated, so what the mock serves is
    byte-identical to what the device serves. Useful for working on the page,
    and for capturing a screenshot of it, without flashing a board.
    """
    header = (Path(__file__).resolve().parent / "src" / "dashboard.h").read_text()
    start = header.index('R"HTML(') + len('R"HTML(')
    return header[start:header.rindex(')HTML"')]


@app.route("/api/status")
def status():
    # `mock: true` is what tells benchmark.py this is not hardware.
    return jsonify({"rssi": -50, "uptime_s": 100, "ip": "127.0.0.1", "mock": True})


@app.route("/api/reset", methods=["POST"])
def reset():
    state.reset()
    return jsonify({"status": "reset", "vault_reinitialised": True,
                    "instrumentation_overhead_us": OVERHEAD_US, "overhead_samples": 200})


@app.route("/api/benchmark")
def benchmark():
    protocol = request.args.get("protocol")
    if protocol not in PHASES:
        return jsonify({"error": "Unknown protocol", "cause": "malformed_request",
                        "valid": list(PHASES)}), 400
    k = int(request.args.get("k", "10"))
    device_side = jitter(crypto_us(protocol))
    # The firmware's timed region also simulates the peer, so the amortised
    # whole-region figure sits above the device-side sum. Mirrored here so the
    # harness sees the same shape it sees against the board.
    amortised = device_side + jitter(PEER_SIM_US[protocol])
    return jsonify({
        "protocol": protocol,
        "requested_k": k, "completed_k": k, "truncated": False,
        "max_batch_ms": 2000,
        "total_us": round(amortised * k, 3),
        "amortised_us_per_op": round(amortised, 4),
        "warmup": {"iterations": 8, "mean_us": round(amortised * 1.4, 3), "excluded": True},
        "per_iteration": stats(device_side, count=k),
        "instrumentation_overhead_us": OVERHEAD_US,
        "opt_level": "-Os (mock)",
    })


@app.route("/api/energy")
def energy():
    def protocol_block(name: str) -> dict:
        c = crypto_us(name)
        n_ok = state.counts[name]["count"]
        return {
            "count": n_ok,
            "failures": state.counts[name]["failures"],
            "crypto_us": stats(c),
            "handler_us": stats(c + HANDLER_OVERHEAD_US[name]),
            # Phase names must match telemetry.cpp exactly; analyze.py keys its
            # per-phase chart off them and silently renders an empty panel if
            # they drift.
            "phases": {n: stats(v) for n, v in PHASES[name].items()},
            # The firmware's telemetry carries a per-protocol energy block and
            # the on-device dashboard reads per_cycle_uj from it. analyze.py
            # derives energy host-side, so omitting this went unnoticed until
            # the dashboard was rendered against the mock and came up empty.
            "energy": {
                "paper": {"power_mw": 99.5,
                          "per_cycle_uj": round(99.5 * c / 1000, 4),
                          "total_uj": round(99.5 * c / 1000 * n_ok, 4),
                          "total_wh": 99.5 * c / 1000 * n_ok / 3.6e9},
                "device": {"power_mw": 82.5,
                           "per_cycle_uj": round(82.5 * c / 1000, 4),
                           "total_uj": round(82.5 * c / 1000 * n_ok, 4),
                           "total_wh": 82.5 * c / 1000 * n_ok / 3.6e9},
            },
        }

    return jsonify({
        "uptime_s": 200,
        "rssi": -50,
        "mock": True,
        "power_model": {
            "paper": {"power_mw": 99.5, "current_ma": 19.9, "voltage_v": 5.0,
                      "source": "Gupta & Kumaraguru, TrustCom 2018, section VI-A"},
            "device": {"power_mw": 82.5, "current_ma": 25.0, "voltage_v": 3.3,
                       "source": "ESP32-C3 datasheet, CPU active @160 MHz"},
            "formula": "energy_uJ = power_mW * latency_us / 1000",
            # The dashboard prints this verbatim; without it the page showed a
            # literal "undefined". Matches telemetry.cpp.
            "note": "Ratios between protocols are invariant to both constants.",
        },
        "hw_accel": {"aes": True, "sha": True, "ecc_p256": False, "opt_level": "-Os (mock)"},
        "invariant_violations": 0,
        "instrumentation": {"overhead_us": stats(OVERHEAD_US, count=200)},
        "protocols": {name: protocol_block(name) for name in PHASES},
    })


# --- Classical -------------------------------------------------------------
@app.route("/api/auth/classical/init", methods=["GET"])
def cl_init():
    challenge = secrets.token_bytes(16)
    sid = open_session("classical", challenge)
    return jsonify({"sid": sid, "challenge": challenge.hex().upper()})


@app.route("/api/auth/classical/verify", methods=["POST"])
def cl_verify():
    """Two AES operations, as the firmware does: decrypt to verify, encrypt to answer."""
    challenge = take_session("classical")
    if challenge is None:
        return fail("classical", 400, "Session not initialized", "no_session")
    raw = body_hex()
    if len(raw) < 64:
        return fail("classical", 400, "Invalid response length", "malformed_request")

    decrypted = ecb(CLASSICAL_KEY).decrypt(bytes.fromhex(raw[:32]))
    if decrypted != challenge:
        return fail("classical", 401, "Authentication Failed", "verification_failed")

    peer_challenge = bytes.fromhex(raw[32:64])
    reply = ecb(CLASSICAL_KEY).encrypt(peer_challenge)
    return jsonify(auth_reply("classical", {"message": "Authentication Success",
                                            "response": reply.hex().upper()}))


# --- Single rotating password (the reference paper's own Figure 3 baseline) --
@app.route("/api/auth/srp/init", methods=["GET"])
def srp_init():
    challenge = secrets.token_bytes(16)
    sid = open_session("srp", challenge)
    return jsonify({"sid": sid, "challenge": challenge.hex().upper()})


@app.route("/api/auth/srp/verify", methods=["POST"])
def srp_verify():
    """Three AES operations: verify the peer, answer it, recover the next password."""
    challenge = take_session("srp")
    if challenge is None:
        return fail("srp", 400, "Session not initialized", "no_session")
    raw = body_hex()
    if len(raw) < 96:
        return fail("srp", 400, "Invalid response length", "malformed_request")

    if ecb(state.srp_key).decrypt(bytes.fromhex(raw[:32])) != challenge:
        return fail("srp", 401, "Authentication Failed", "verification_failed")

    peer_challenge = bytes.fromhex(raw[32:64])
    reply = ecb(state.srp_key).encrypt(peer_challenge)
    next_key = ecb(state.srp_key).decrypt(bytes.fromhex(raw[64:96]))

    # Rotate only after the reply was produced under the old password.
    state.srp_key = next_key
    return jsonify(auth_reply("srp", {"response": reply.hex().upper()}))


# --- Secure Vault ----------------------------------------------------------
@app.route("/api/auth/sv/init", methods=["GET"])
def sv_init():
    c1 = secrets.SystemRandom().sample(range(NUM_KEYS), 4)
    r1 = secrets.token_bytes(16)
    sid = open_session("sv", (c1, r1))
    return jsonify({"sid": sid, "C1": c1, "r1": r1.hex().upper()})


@app.route("/api/auth/sv/verify", methods=["POST"])
def sv_verify():
    session = take_session("sv")
    if session is None:
        return fail("sv", 400, "Session not initialized", "no_session")
    c1, r1 = session

    raw = body_hex()
    if len(raw) < 128:
        return fail("sv", 400, "Invalid M3 length", "malformed_request")

    k1 = state.derive(c1)
    plain = ecb(k1).decrypt(bytes.fromhex(raw[:128]))
    if plain[:16] != r1:
        return fail("sv", 401, "Authentication Failed: r1 mismatch", "verification_failed")

    # Offsets fixed by auth_sv.cpp: t1 at 16, C2 at 32 (4 bytes), r2 at 48.
    t1, c2, r2 = plain[16:32], plain[32:36], plain[48:64]

    # Mirrors auth_sv.cpp: C2 must be four distinct in-range indices and a
    # different set from C1.
    if len(set(c2)) != 4 or any(i >= NUM_KEYS for i in c2) or set(c2) == set(c1):
        return fail("sv", 401, "Authentication Failed: C2 invalid or equal to C1",
                    "bad_challenge")

    k2 = state.derive(list(c2))
    enc_key = bytes(a ^ b for a, b in zip(k2, t1))
    t2 = secrets.token_bytes(16)
    m4 = ecb(enc_key).encrypt(r2 + t2)

    # HMAC is taken over the vault BEFORE rotation, keyed with r1.
    state.rotate(r1)

    return jsonify(auth_reply("sv", {"M4": m4.hex().upper()}))


# --- ECC -------------------------------------------------------------------
@app.route("/api/auth/ecc/init", methods=["GET"])
def ecc_init():
    challenge = secrets.token_bytes(32)
    sid = open_session("ecc", challenge)
    return jsonify({"sid": sid, "challenge": challenge.hex().upper()})


@app.route("/api/auth/ecc/verify", methods=["POST"])
def ecc_verify():
    our_challenge = take_session("ecc")
    if our_challenge is None:
        return fail("ecc", 400, "Session not initialized", "no_session")

    raw = body_hex()
    if len(raw) < 192:
        return fail("ecc", 400, "Expected 96 bytes: challenge(32) || signature(64)",
                    "malformed_request")

    buf = bytes.fromhex(raw[:192])
    peer_challenge, peer_sig = buf[:32], buf[32:96]

    # Verify the host's signature over the challenge WE issued.
    try:
        DSS.new(HOST_KEY, "fips-186-3").verify(SHA256.new(our_challenge), peer_sig)
    except ValueError:
        return fail("ecc", 401, "Signature verification failed", "verification_failed")

    # Sign the challenge the host issued.
    signature = DSS.new(DEVICE_KEY, "fips-186-3").sign(SHA256.new(peer_challenge))

    return jsonify(auth_reply("ecc", {
        "signature": signature.hex().upper(),
        "sign_us": round(jitter(PHASES["ecc"]["sign"]), 3),
        "verify_us": round(jitter(PHASES["ecc"]["verify"]), 3),
    }))


if __name__ == "__main__":
    print("MOCK DEVICE -- synthetic timings, not measurements.")
    app.run(host="127.0.0.1", port=5000)
