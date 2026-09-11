// Secure Vault authentication (reference paper: Gupta & Kumaraguru,
// TrustCom 2018). Multi-key XOR key derivation, AES-128 challenge-response,
// and an HMAC-SHA256-driven vault update after each successful session.
#pragma once

#include <WebServer.h>
#include <stdint.h>

constexpr int NUM_KEYS = 16;
constexpr int KEY_SIZE = 16;

// Populates the initial vault. Must be called once at boot.
void initSecureVault();

// True if `c` is a valid challenge: four distinct indices, each below NUM_KEYS.
bool svChallengeValid(const uint8_t* c);

// Registers GET /api/auth/sv/init and POST /api/auth/sv/verify.
// Drops every pending session. Called by POST /api/reset.
void svResetSessions();

void registerSVRoutes(WebServer& server);

// Runs one full cycle of the protocol's cryptographic work against a synthetic
// session, for the batch benchmark. Uses the same primitives, key material, and
// phase boundaries as the live handler. Takes and returns a byte so callers can
// chain iterations into a dependency the optimiser cannot collapse.
uint8_t svBenchmarkOnce(uint8_t seed);
