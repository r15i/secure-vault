"""P-256 test key material for the ECC authentication benchmark (host side).

GENERATED FIXTURE. The device holds the matching keys in src/ecc_keys.h.
A committed private key is acceptable only because this is a benchmark: it
authenticates nothing of value and makes runs reproducible.

Regenerate with: python3 tools/gen_ecc_keys.py
"""

# Host private scalar, 32-byte big-endian hex.
HOST_PRIVATE_HEX = "8E6C1858549CB5020F68D97FA23F1902FED562DBCDBBF5914B9A4F464571F14C"

# Host public point, uncompressed (04 || X || Y).
HOST_PUBLIC_HEX = "04ABA91262CD5853A9A62DF0BFA0A5AA083CD42625E17B72DE7F066FE6686FE0117C337204934D848BBFA3DA9D1DFB463623B81FB1FDCF7D07C434EE6E78B50E8F"

# Device public point, uncompressed. Used to verify the device's signature.
DEVICE_PUBLIC_HEX = "04F30ADEA15A693A655D0F8C29B91D9A9C1B7D79E7E136945A1F694685A55DCBE8A3AA00DBE87DA8B1265726DA05C58E10328C4878AE2623D7EAC5795ECFAD33C8"
