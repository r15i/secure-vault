// Classical authentication: a single shared AES-128 key, mutual
// challenge-response. The cheapest of the four protocols and the comparison
// baseline, matching the two AES operations the reference paper's Table 1
// charges to its simplest scheme.
#pragma once

#include <WebServer.h>

// Registers GET /api/auth/classical/init and POST /api/auth/classical/verify.
// Drops every pending session. Called by POST /api/reset.
void clResetSessions();

void registerClassicalRoutes(WebServer& server);

// Two AES-128 block operations under the shared key, for the batch benchmark:
// one decryption to verify the peer, one encryption to answer it. Same
// primitives and key material as the live handler. Takes and returns a byte so
// iterations chain into a dependency the optimiser cannot collapse.
uint8_t clBenchmarkOnce(uint8_t seed);
