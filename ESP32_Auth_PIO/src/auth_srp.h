// Single rotating password authentication -- the reference paper's own
// baseline, and the one its Figure 3 plots Secure Vault against.
//
// Gupta & Kumaraguru, section VI-A: "Single rotating password-based scheme
// requires 3 AES operations, first two AES operation for authentication and the
// last one for the exchanging new password using previous password as
// encryption key." The paper costs it at 746.25 uJ (3 x 248.75).
//
// This exists so the comparison Secure Vault is actually meant to win can be
// measured rather than inherited from the paper. Unlike the Classical baseline
// it rotates key material after every session, so it offers a comparable
// security guarantee: the fair question is what Secure Vault costs against
// THIS, not against a scheme that never changes its key.
#pragma once

#include <WebServer.h>
#include <stdint.h>

constexpr int SRP_KEY_SIZE = 16;

// Sets the password to its documented boot value. Called at boot and on reset.
void initSRP();

// Registers GET /api/auth/srp/init and POST /api/auth/srp/verify.
// Drops every pending session. Called by POST /api/reset.
void srpResetSessions();

void registerSRPRoutes(WebServer& server);

// One full cycle of the protocol's cryptographic work, for the batch benchmark.
// Same primitives, key material and phase boundaries as the live handler.
uint8_t srpBenchmarkOnce(uint8_t seed);
