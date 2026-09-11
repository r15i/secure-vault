#include "auth_classical.h"

#include <stdio.h>
#include <string.h>
#include <mbedtls/aes.h>

#include "crypto_util.h"
#include "metrics.h"
#include "sessions.h"

// Fixed shared key. A benchmark fixture, not a deployment pattern.
static const uint8_t classical_key[16] = {
    0x2B, 0x7E, 0x15, 0x16, 0x28, 0xAE, 0xD2, 0xA6,
    0xAB, 0xF7, 0x15, 0x88, 0x09, 0xCF, 0x4F, 0x3C};

struct ClassicalSession {
    bool active = false;
    uint8_t challenge[16];
};

static ClassicalSession cl_session;
static SessionTable cl_sessions;
static WebServer* srv = nullptr;

// The protocol's entire cryptographic cost: two AES-128 ECB block operations,
// matching the two the reference paper's Table 1 charges to the classical
// scheme. One decryption verifies that the peer holds the shared key; one
// encryption proves to the peer that this device holds it too. Context setup
// and key scheduling are inside the timed region, as they are for every other
// protocol here. Shared with the batch benchmark path so both measure
// identical work.
//
//   body = E_k(device_challenge) || peer_challenge
//
// Returns the summed measured crypto time and writes the reply block out. The
// second operation is skipped when the first fails, so a rejected cycle is
// never billed for work it did not do.
uint32_t clRunCryptoOnce(const uint8_t* enc_response,
                         const uint8_t* peer_challenge,
                         const uint8_t* expected_challenge,
                         uint8_t* reply_out,
                         bool* ok_out) {
    uint32_t crypto_us = 0;
    mbedtls_aes_context aes;

    // Phase 1 of 2: verify the peer holds the shared key.
    PhaseTimer t_dec(S_CL_AES_DEC);
    uint8_t decrypted[16];
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_dec(&aes, classical_key, 128);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_DECRYPT, enc_response, decrypted);
    mbedtls_aes_free(&aes);
    crypto_us += t_dec.stop();

    const bool ok = (memcmp(decrypted, expected_challenge, 16) == 0);
    if (ok_out) *ok_out = ok;
    if (!ok) {
        // The phase that did execute is already recorded.
        return crypto_us;
    }

    // Phase 2 of 2: prove to the peer that this device holds it too.
    PhaseTimer t_enc(S_CL_AES_ENC);
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_enc(&aes, classical_key, 128);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_ENCRYPT, peer_challenge, reply_out);
    mbedtls_aes_free(&aes);
    crypto_us += t_enc.stop();

    return crypto_us;
}

static void handleCLInit() {
    uint8_t challenge[16];
    getRandomBytes(challenge, 16);
    const uint32_t sid = sessionOpen(cl_sessions, challenge, 16);

    char chalHex[33];
    bytesToHexString(challenge, 16, chalHex);
    char response[128];
    sprintf(response, "{\"sid\":%u, \"challenge\":\"%s\"}", sid, chalHex);
    srv->send(200, "application/json", response);
}

static void handleCLVerify() {
    ScopedTimer handlerTimer(S_CL_HANDLER);

    // Only the request holding this session's identifier may consume it, so a
    // peer with a pending session cannot be cancelled by anyone else.
    const uint32_t sid = (uint32_t) strtoul(srv->arg("sid").c_str(), nullptr, 10);
    if (!sessionTake(cl_sessions, sid, cl_session.challenge, 16)) {
        recordFailure(P_CLASSICAL);
        srv->send(400, "application/json",
                  "{\"error\":\"No such session\", \"cause\":\"no_session\"}");
        return;
    }
    cl_session.active = true;

    // 32 bytes: E_k(device_challenge) || peer_challenge.
    String body = srv->arg("plain");
    if (body.length() < 64) {
        recordFailure(P_CLASSICAL);
        srv->send(400, "application/json",
                  "{\"error\":\"Expected 32 bytes: response(16) || challenge(16)\", "
                  "\"cause\":\"malformed_request\"}");
        return;
    }

    uint8_t buf[32], reply[16];
    hexStringToBytes(body.c_str(), buf, 32);

    bool ok = false;
    const uint32_t crypto_us = clRunCryptoOnce(buf, buf + 16, cl_session.challenge,
                                               reply, &ok);
    cl_session.active = false;

    if (!ok) {
        recordFailure(P_CLASSICAL);
        srv->send(401, "application/json",
                  "{\"status\":\"failed\", \"message\":\"Authentication Failed\", "
                  "\"cause\":\"verification_failed\"}");
        return;
    }

    record(S_CL_CRYPTO, crypto_us);
    if ((int64_t) crypto_us > handlerTimer.elapsed()) invariant_violations++;
    recordSuccess(P_CLASSICAL, crypto_us);

    const ProtocolMetrics& m = protocols[P_CLASSICAL];
    char replyHex[33];
    bytesToHexString(reply, 16, replyHex);
    char response[384];
    sprintf(response,
            "{\"status\":\"success\", \"message\":\"Authentication Success\", "
            "\"response\":\"%s\", \"crypto_us\":%u, \"handler_us\":%lld, "
            "\"energy_uj\":{\"paper\":%.4f, \"device\":%.4f}, "
            "\"total_energy_uj\":{\"paper\":%.4f, \"device\":%.4f}}",
            replyHex, crypto_us, (long long) handlerTimer.elapsed(),
            energyUj(PAPER_POWER_MW, crypto_us), energyUj(DEVICE_POWER_MW, crypto_us),
            m.energy_paper_uj, m.energy_device_uj);
    srv->send(200, "application/json", response);
}

uint8_t clBenchmarkOnce(uint8_t seed) {
    // AES-ECB cost is independent of block content, so a seed-derived block is
    // representative of a real challenge response. Building the peer's message
    // is the peer's work in a real cycle, so it happens outside the timed
    // phases.
    uint8_t challenge[16], peer_challenge[16];
    for (int i = 0; i < 16; i++) challenge[i] = (uint8_t) (seed + i * 7);
    getRandomBytes(peer_challenge, 16);

    uint8_t enc_response[16];
    mbedtls_aes_context aes;
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_enc(&aes, classical_key, 128);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_ENCRYPT, challenge, enc_response);
    mbedtls_aes_free(&aes);

    uint8_t reply[16];
    bool ok = false;
    const uint32_t crypto_us = clRunCryptoOnce(enc_response, peer_challenge, challenge,
                                               reply, &ok);
    record(S_CL_CRYPTO, crypto_us);

    // Feed the result forward so the iterations form a dependency chain.
    return (uint8_t) (reply[0] ^ reply[15] ^ (ok ? 0x3C : 0));
}

void clResetSessions() {
    sessionReset(cl_sessions);
}

void registerClassicalRoutes(WebServer& server) {
    srv = &server;
    server.on("/api/auth/classical/init", HTTP_GET, handleCLInit);
    server.on("/api/auth/classical/verify", HTTP_POST, handleCLVerify);
}
