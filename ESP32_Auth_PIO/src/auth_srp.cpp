#include "auth_srp.h"

#include <mbedtls/aes.h>
#include <stdio.h>
#include <string.h>

#include "crypto_util.h"
#include "metrics.h"
#include "sessions.h"

// The shared password. A benchmark fixture, not a deployment pattern; it is
// rotated after every successful session, which is the whole point of the
// scheme. Boot value is fixed so the host mirror can start from a known state.
static uint8_t srp_key[SRP_KEY_SIZE];

struct SRPSession {
    bool active = false;
    uint8_t challenge[16];
};

static SRPSession srp_session;
static SessionTable srp_sessions;
static WebServer* srv = nullptr;

void initSRP() {
    for (int i = 0; i < SRP_KEY_SIZE; i++) srp_key[i] = (uint8_t) (0xA0 + i);
}

// The protocol's whole cryptographic cost: exactly three AES-128 block
// operations, matching the paper's accounting. Two authenticate (verify the
// peer's response, answer the peer's challenge) and one carries the next
// password. Shared by the handler and the batch path so both measure the same
// work.
//
//   body = E_k(device_challenge) || peer_challenge || E_k(next_password)
//
// Returns the summed measured crypto time; writes the reply block and the new
// password out. The caller rotates only after a cycle that fully succeeded.
uint32_t srpRunCryptoOnce(const uint8_t* enc_response,
                          const uint8_t* peer_challenge,
                          const uint8_t* enc_next_key,
                          const uint8_t* expected_challenge,
                          uint8_t* reply_out,
                          uint8_t* next_key_out,
                          bool* ok_out) {
    uint32_t crypto_us = 0;
    mbedtls_aes_context aes;

    // Phase 1 of 3: verify the peer holds the current password.
    PhaseTimer t_dec(S_SRP_AES_DEC);
    uint8_t decrypted[16];
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_dec(&aes, srp_key, 128);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_DECRYPT, enc_response, decrypted);
    mbedtls_aes_free(&aes);
    crypto_us += t_dec.stop();

    const bool ok = (memcmp(decrypted, expected_challenge, 16) == 0);
    if (ok_out) *ok_out = ok;
    if (!ok) {
        // The phase that did execute is already recorded.
        return crypto_us;
    }

    // Phase 2 of 3: prove to the peer that we hold it too.
    PhaseTimer t_enc(S_SRP_AES_ENC);
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_enc(&aes, srp_key, 128);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_ENCRYPT, peer_challenge, reply_out);
    mbedtls_aes_free(&aes);
    crypto_us += t_enc.stop();

    // Phase 3 of 3: recover the next password, sent under the current one.
    PhaseTimer t_rekey(S_SRP_REKEY);
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_dec(&aes, srp_key, 128);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_DECRYPT, enc_next_key, next_key_out);
    mbedtls_aes_free(&aes);
    crypto_us += t_rekey.stop();

    return crypto_us;
}

static void handleSRPInit() {
    uint8_t challenge[16];
    getRandomBytes(challenge, 16);
    const uint32_t sid = sessionOpen(srp_sessions, challenge, 16);

    char chalHex[33];
    bytesToHexString(challenge, 16, chalHex);
    char response[128];
    sprintf(response, "{\"sid\":%u, \"challenge\":\"%s\"}", sid, chalHex);
    srv->send(200, "application/json", response);
}

static void handleSRPVerify() {
    ScopedTimer handlerTimer(S_SRP_HANDLER);

    // Only the request holding this session's identifier may consume it, so a
    // peer with a pending session cannot be cancelled by anyone else.
    const uint32_t sid = (uint32_t) strtoul(srv->arg("sid").c_str(), nullptr, 10);
    if (!sessionTake(srp_sessions, sid, srp_session.challenge, 16)) {
        recordFailure(P_SRP);
        srv->send(400, "application/json",
                  "{\"error\":\"No such session\", \"cause\":\"no_session\"}");
        return;
    }
    srp_session.active = true;

    // 48 bytes: E_k(challenge) || peer_challenge || E_k(next_password).
    String body = srv->arg("plain");
    if (body.length() < 96) {
        recordFailure(P_SRP);
        srv->send(400, "application/json",
                  "{\"error\":\"Expected 48 bytes: response(16) || challenge(16) || "
                  "next_key(16)\", \"cause\":\"malformed_request\"}");
        return;
    }

    uint8_t buf[48];
    hexStringToBytes(body.c_str(), buf, 48);

    uint8_t reply[16], next_key[16];
    bool ok = false;
    const uint32_t crypto_us = srpRunCryptoOnce(buf, buf + 16, buf + 32,
                                                srp_session.challenge,
                                                reply, next_key, &ok);
    srp_session.active = false;

    if (!ok) {
        recordFailure(P_SRP);
        srv->send(401, "application/json",
                  "{\"status\":\"failed\", \"error\":\"Authentication Failed\", "
                  "\"cause\":\"verification_failed\"}");
        return;
    }

    // Rotate only after success, and only after the reply has been produced
    // under the old password -- the peer decrypts it with that one.
    memcpy(srp_key, next_key, SRP_KEY_SIZE);

    record(S_SRP_CRYPTO, crypto_us);
    if ((int64_t) crypto_us > handlerTimer.elapsed()) invariant_violations++;
    recordSuccess(P_SRP, crypto_us);

    const ProtocolMetrics& m = protocols[P_SRP];
    char replyHex[33];
    bytesToHexString(reply, 16, replyHex);
    char response[384];
    sprintf(response,
            "{\"status\":\"success\", \"response\":\"%s\", "
            "\"crypto_us\":%u, \"handler_us\":%lld, "
            "\"energy_uj\":{\"paper\":%.4f, \"device\":%.4f}, "
            "\"total_energy_uj\":{\"paper\":%.4f, \"device\":%.4f}}",
            replyHex, crypto_us, (long long) handlerTimer.elapsed(),
            energyUj(PAPER_POWER_MW, crypto_us), energyUj(DEVICE_POWER_MW, crypto_us),
            m.energy_paper_uj, m.energy_device_uj);
    srv->send(200, "application/json", response);
}

uint8_t srpBenchmarkOnce(uint8_t seed) {
    // The password is snapshotted and restored around the iteration, for the
    // same reason the Secure Vault batch snapshots its vault: a batch of K
    // would otherwise rotate the key K times and leave the host mirror unable
    // to authenticate afterwards. Both sit outside every PhaseTimer, so the
    // measured work is unchanged.
    uint8_t key_snapshot[SRP_KEY_SIZE];
    memcpy(key_snapshot, srp_key, SRP_KEY_SIZE);

    // Building the peer's message is the peer's work in a real cycle, so it
    // happens outside the timed phases.
    uint8_t challenge[16], peer_challenge[16], next_key[16];
    for (int i = 0; i < 16; i++) challenge[i] = (uint8_t) (seed + i * 7);
    getRandomBytes(peer_challenge, 16);
    getRandomBytes(next_key, 16);

    uint8_t enc_response[16], enc_next[16];
    mbedtls_aes_context aes;
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_enc(&aes, srp_key, 128);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_ENCRYPT, challenge, enc_response);
    mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_ENCRYPT, next_key, enc_next);
    mbedtls_aes_free(&aes);

    uint8_t reply[16], recovered[16];
    bool ok = false;
    const uint32_t crypto_us = srpRunCryptoOnce(enc_response, peer_challenge, enc_next,
                                                challenge, reply, recovered, &ok);
    record(S_SRP_CRYPTO, crypto_us);

    memcpy(srp_key, key_snapshot, SRP_KEY_SIZE);

    // Feed the result forward so the iterations form a dependency chain.
    return (uint8_t) (reply[0] ^ reply[15] ^ (ok ? 0x3C : 0));
}

void srpResetSessions() {
    sessionReset(srp_sessions);
}

void registerSRPRoutes(WebServer& server) {
    srv = &server;
    server.on("/api/auth/srp/init", HTTP_GET, handleSRPInit);
    server.on("/api/auth/srp/verify", HTTP_POST, handleSRPVerify);
}
