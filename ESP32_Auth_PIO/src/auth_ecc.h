// ECC authentication — the asymmetric baseline the symmetric protocols are
// compared against.
//
// ECDSA over NIST P-256 (secp256r1) with SHA-256. Each cycle performs one
// signature generation AND one verification on the device, mirroring the
// two-primitive structure of the symmetric protocols (Classical: 2 AES;
// Secure Vault: 2 AES + HMAC) so the ratio comparison is like-for-like.
//
// Exchange, per cycle:
//   1. GET  /api/auth/ecc/init    device issues a fresh 32-byte challenge
//   2. host signs the device challenge, sends its own challenge + signature
//   3. POST /api/auth/ecc/verify  device verifies the host signature and signs
//      the host challenge; the host then verifies the device's signature
//
// On this build P-256 point multiplication runs in SOFTWARE: the ESP32-C3
// framework config enables CONFIG_MBEDTLS_HARDWARE_AES and _SHA but no
// hardware ECC. See telemetry's hw_accel block and design.md Decision 8.
#pragma once

#include <WebServer.h>
#include <stdint.h>

// Loads the P-256 group and key material. Call once at boot, before serving.
// Timed as S_ECC_SETUP, which is NOT part of per-cycle cost.
bool initECC();

// Registers GET /api/auth/ecc/init and POST /api/auth/ecc/verify.
// Drops every pending session. Called by POST /api/reset.
void eccResetSessions();

void registerECCRoutes(WebServer& server);

// One ECDSA sign + one ECDSA verify, for the batch benchmark. The verification
// checks a genuinely valid signature -- the one the previous iteration produced,
// against the device's own public key -- because the host's private key is not
// on the device. Same primitives and curve as the live handler.
uint8_t eccBenchmarkOnce(uint8_t seed);

// Runs one cycle's cryptographic work: sign the peer challenge, verify the
// peer's signature over ours. Returns summed measured crypto time and sets
// *verify_ok. sign_us / verify_us receive the individual phase durations and
// may be null. Shared with the batch benchmark path.
uint32_t eccRunCryptoOnce(const uint8_t* peer_challenge,
                          const uint8_t* peer_sig,
                          const uint8_t* our_challenge,
                          uint8_t* our_sig_out,
                          bool* verify_ok,
                          uint32_t* sign_us = nullptr,
                          uint32_t* verify_us = nullptr);
