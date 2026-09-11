"""Host side of the ECC authentication exchange: ECDSA over P-256.

The device signs a challenge we issue and verifies a signature we produce, so the
host must do real asymmetric crypto too. Without this the ECC path could not be
mutually authenticated and its cost could not be attributed.

Signature wire format is the raw concatenation r || s, 32 bytes each -- what
mbedTLS's mbedtls_mpi_write_binary pair produces on the device, and what
pycryptodome's 'fips-186-3' DSS mode produces here.
"""

import os

from Crypto.Hash import SHA256
from Crypto.PublicKey import ECC
from Crypto.Signature import DSS

import ecc_keys

CHALLENGE_LEN = 32
SIG_LEN = 64


def _load_private(hex_scalar: str) -> ECC.EccKey:
    return ECC.construct(curve="P-256", d=int(hex_scalar, 16))


def _load_public(hex_point: str) -> ECC.EccKey:
    raw = bytes.fromhex(hex_point)
    if len(raw) != 65 or raw[0] != 0x04:
        raise ValueError("expected a 65-byte uncompressed point (0x04 || X || Y)")
    return ECC.construct(
        curve="P-256",
        point_x=int.from_bytes(raw[1:33], "big"),
        point_y=int.from_bytes(raw[33:65], "big"),
    )


HOST_KEY = _load_private(ecc_keys.HOST_PRIVATE_HEX)
DEVICE_PUBLIC = _load_public(ecc_keys.DEVICE_PUBLIC_HEX)


def new_challenge() -> bytes:
    """A fresh random challenge. Freshness is what makes replay detectable."""
    return os.urandom(CHALLENGE_LEN)


def sign(message: bytes) -> bytes:
    """ECDSA-sign with the host key. Returns r || s, 64 bytes."""
    signer = DSS.new(HOST_KEY, "fips-186-3")
    sig = signer.sign(SHA256.new(message))
    if len(sig) != SIG_LEN:
        raise ValueError(f"expected a {SIG_LEN}-byte signature, got {len(sig)}")
    return sig


def verify_device(message: bytes, signature: bytes) -> bool:
    """Verify a device signature over `message` against the device public key."""
    if len(signature) != SIG_LEN:
        return False
    verifier = DSS.new(DEVICE_PUBLIC, "fips-186-3")
    try:
        verifier.verify(SHA256.new(message), signature)
        return True
    except ValueError:
        return False


def build_verify_body(device_challenge: bytes) -> tuple[str, bytes]:
    """Body for POST /api/auth/ecc/verify.

    Returns (hex body, our challenge). The body is
    host_challenge(32) || host_signature_over_device_challenge(64), hex-encoded.
    Keep the returned challenge: the device's reply signs it, and verifying that
    signature is what authenticates the device to us.
    """
    host_challenge = new_challenge()
    host_sig = sign(device_challenge)
    return (host_challenge + host_sig).hex(), host_challenge
