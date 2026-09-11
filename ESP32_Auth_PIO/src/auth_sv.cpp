#include "auth_sv.h"

#include <mbedtls/aes.h>
#include <mbedtls/md.h>
#include <stdio.h>
#include <string.h>

#include "crypto_util.h"
#include "metrics.h"
#include "sessions.h"

static uint8_t secure_vault[NUM_KEYS][KEY_SIZE];

struct SecureVaultSession {
    bool active = false;
    uint8_t C1[4];
    uint8_t r1[16];
};

static SecureVaultSession sv_session;
static SessionTable sv_sessions;
static WebServer* srv = nullptr;

void initSecureVault() {
    for (int i = 0; i < NUM_KEYS; i++) {
        for (int j = 0; j < KEY_SIZE; j++) {
            secure_vault[i][j] = i + j;
        }
    }
}

// Runs the protocol's cryptographic work once against a caller-supplied M3,
// returning the summed measured crypto time. Shared by the request handler and
// the batch benchmark path so the two measure identical work (spec
// benchmark-harness: "Batch is equivalent to individual cycles").
//
// Phase boundaries include mbedTLS context setup and key scheduling, because
// that is the real cost of performing the operation -- the same accounting the
// reference paper used when it counted "one AES encryption and one AES
// decryption".
bool svChallengeValid(const uint8_t* c) {
    for (int i = 0; i < 4; i++) {
        if (c[i] >= NUM_KEYS) return false;
        for (int j = 0; j < i; j++) {
            if (c[i] == c[j]) return false;
        }
    }
    return true;
}

// True if the two challenges select the same set of vault keys.
static bool svSameSet(const uint8_t* a, const uint8_t* b) {
    for (int i = 0; i < 4; i++) {
        bool found = false;
        for (int j = 0; j < 4; j++) found |= (a[i] == b[j]);
        if (!found) return false;
    }
    return true;
}

// Four distinct indices below NUM_KEYS, from the hardware RNG.
static void svRandomChallenge(uint8_t* c) {
    for (int i = 0; i < 4; i++) {
        uint8_t v;
        bool dup;
        do {
            v = esp_random() % NUM_KEYS;
            dup = false;
            for (int j = 0; j < i; j++) dup |= (c[j] == v);
        } while (dup);
        c[i] = v;
    }
}

uint32_t svRunCryptoOnce(const uint8_t* m3, const uint8_t* expected_r1,
                         uint8_t* m4_out, bool* r1_ok_out, bool* c2_ok_out) {
    uint32_t crypto_us = 0;
    mbedtls_aes_context aes;

    // Phase: derive k1 by XOR-ing the four vault keys the challenge selected.
    PhaseTimer t_keyderiv(S_SV_KEYDERIV);
    uint8_t k1[16];
    memcpy(k1, secure_vault[sv_session.C1[0]], 16);
    for (int i = 1; i < 4; i++) {
        for (int j = 0; j < 16; j++) k1[j] ^= secure_vault[sv_session.C1[i]][j];
    }
    crypto_us += t_keyderiv.stop();

    // Phase: AES-128 ECB decrypt of M3 (4 blocks).
    PhaseTimer t_dec(S_SV_AES_DEC);
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_dec(&aes, k1, 128);
    uint8_t decryptedM3[64];
    for (int i = 0; i < 4; i++) {
        mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_DECRYPT, m3 + (i * 16), decryptedM3 + (i * 16));
    }
    mbedtls_aes_free(&aes);
    crypto_us += t_dec.stop();

    const bool r1_ok = (memcmp(decryptedM3, expected_r1, 16) == 0);
    if (r1_ok_out) *r1_ok_out = r1_ok;
    if (c2_ok_out) *c2_ok_out = false;
    if (!r1_ok) {
        // The phases that did execute are already recorded (spec
        // protocol-instrumentation: "Timing survives a failed authentication").
        return crypto_us;
    }

    uint8_t t1[16], C2[4], r2[16];
    memcpy(t1, decryptedM3 + 16, 16);
    memcpy(C2, decryptedM3 + 32, 4);
    memcpy(r2, decryptedM3 + 48, 16);

    // The paper requires C2 to be a set of distinct indices different from C1,
    // so a key recovered for one challenge cannot be reused for the other. A
    // handful of byte comparisons, outside the timed phases.
    const bool c2_ok = svChallengeValid(C2) && !svSameSet(C2, sv_session.C1);
    if (c2_ok_out) *c2_ok_out = c2_ok;
    if (!c2_ok) return crypto_us;

    // Phase: AES-128 ECB encrypt of M4 (2 blocks), under k2 masked with t1.
    PhaseTimer t_enc(S_SV_AES_ENC);
    uint8_t t2[16], k2[16], encKey[16];
    getRandomBytes(t2, 16);
    memcpy(k2, secure_vault[C2[0]], 16);
    for (int i = 1; i < 4; i++) {
        for (int j = 0; j < 16; j++) k2[j] ^= secure_vault[C2[i]][j];
    }
    for (int j = 0; j < 16; j++) encKey[j] = k2[j] ^ t1[j];

    uint8_t m4_plain[32];
    memcpy(m4_plain, r2, 16);
    memcpy(m4_plain + 16, t2, 16);
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_enc(&aes, encKey, 128);
    for (int i = 0; i < 2; i++) {
        mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_ENCRYPT, m4_plain + (i * 16), m4_out + (i * 16));
    }
    mbedtls_aes_free(&aes);
    crypto_us += t_enc.stop();

    // Phase: HMAC-SHA256 over the whole vault, keyed with r1.
    PhaseTimer t_hmac(S_SV_HMAC);
    mbedtls_md_context_t ctx;
    mbedtls_md_init(&ctx);
    mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
    mbedtls_md_hmac_starts(&ctx, sv_session.r1, 16);
    mbedtls_md_hmac_update(&ctx, (const unsigned char*) secure_vault, NUM_KEYS * KEY_SIZE);
    uint8_t hmac_result[32];
    mbedtls_md_hmac_finish(&ctx, hmac_result);
    mbedtls_md_free(&ctx);
    crypto_us += t_hmac.stop();

    // Phase: rotate the vault so the next session uses different key material.
    // Only the first KEY_SIZE bytes of the 32-byte digest are consumed; the host
    // mirror in test_client.py Vault.rotate() reproduces this exactly, and the
    // two must change together or every subsequent cycle fails to authenticate.
    PhaseTimer t_rotate(S_SV_ROTATE);
    for (int i = 0; i < NUM_KEYS; i++) {
        for (int j = 0; j < KEY_SIZE; j++) {
            secure_vault[i][j] ^= (hmac_result[j] ^ i);
        }
    }
    crypto_us += t_rotate.stop();

    return crypto_us;
}

static void handleSVInit() {
    // Payload layout, mirrored by the take below: C1[4] then r1[16].
    uint8_t state[20];
    svRandomChallenge(state);
    getRandomBytes(state + 4, 16);
    const uint32_t sid = sessionOpen(sv_sessions, state, sizeof(state));

    char r1Hex[33];
    bytesToHexString(state + 4, 16, r1Hex);
    char response[160];
    sprintf(response, "{\"sid\":%u, \"C1\":[%d,%d,%d,%d], \"r1\":\"%s\"}",
            sid, state[0], state[1], state[2], state[3], r1Hex);
    srv->send(200, "application/json", response);
}

static void handleSVVerify() {
    ScopedTimer handlerTimer(S_SV_HANDLER);

    // Only the request holding this session's identifier may consume it, so a
    // peer with a pending session cannot be cancelled by anyone else.
    const uint32_t sid = (uint32_t) strtoul(srv->arg("sid").c_str(), nullptr, 10);
    uint8_t state[20];
    if (!sessionTake(sv_sessions, sid, state, sizeof(state))) {
        recordFailure(P_SV);
        srv->send(400, "application/json",
                  "{\"error\":\"No such session\", \"cause\":\"no_session\"}");
        return;
    }
    memcpy(sv_session.C1, state, 4);
    memcpy(sv_session.r1, state + 4, 16);
    sv_session.active = true;
    String m3Hex = srv->arg("plain");
    if (m3Hex.length() < 128) {
        recordFailure(P_SV);
        srv->send(400, "application/json",
                  "{\"error\":\"Invalid M3 length\", \"cause\":\"malformed_request\"}");
        return;
    }

    uint8_t m3[64];
    hexStringToBytes(m3Hex.c_str(), m3, 64);

    uint8_t m4[32];
    bool r1_ok = false, c2_ok = false;
    const uint32_t crypto_us = svRunCryptoOnce(m3, sv_session.r1, m4, &r1_ok, &c2_ok);

    sv_session.active = false;

    if (!r1_ok) {
        recordFailure(P_SV);
        srv->send(401, "application/json",
                  "{\"error\":\"Authentication Failed: r1 mismatch\", "
                  "\"cause\":\"verification_failed\"}");
        return;
    }
    if (!c2_ok) {
        recordFailure(P_SV);
        srv->send(401, "application/json",
                  "{\"error\":\"Authentication Failed: C2 invalid or equal to C1\", "
                  "\"cause\":\"bad_challenge\"}");
        return;
    }

    record(S_SV_CRYPTO, crypto_us);
    if ((int64_t) crypto_us > handlerTimer.elapsed()) invariant_violations++;
    recordSuccess(P_SV, crypto_us);

    const ProtocolMetrics& m = protocols[P_SV];
    char m4Hex[65];
    bytesToHexString(m4, 32, m4Hex);
    char response[384];
    sprintf(response,
            "{\"M4\":\"%s\", \"status\":\"success\", \"crypto_us\":%u, \"handler_us\":%lld, "
            "\"energy_uj\":{\"paper\":%.4f, \"device\":%.4f}, "
            "\"total_energy_uj\":{\"paper\":%.4f, \"device\":%.4f}}",
            m4Hex, crypto_us, (long long) handlerTimer.elapsed(),
            energyUj(PAPER_POWER_MW, crypto_us), energyUj(DEVICE_POWER_MW, crypto_us),
            m.energy_paper_uj, m.energy_device_uj);
    srv->send(200, "application/json", response);
}

uint8_t svBenchmarkOnce(uint8_t seed) {
    // Synthetic session, seeded so successive iterations select different vault
    // keys. Setting up the session and building a valid M3 happens OUTSIDE the
    // timed phases -- it is the peer's work in a real cycle, not the device's.
    //
    // The vault is snapshotted and restored around the iteration. A batch of K
    // rotates it K times, which would leave the host mirror in test_client.py
    // unable to derive a single correct key afterwards -- so the network cycles
    // that cross-check this path would all fail. Both the copy and the restore
    // sit outside every PhaseTimer, so the measured work is unchanged: the
    // rotation still executes and is still timed.
    uint8_t vault_snapshot[NUM_KEYS][KEY_SIZE];
    memcpy(vault_snapshot, secure_vault, sizeof(secure_vault));

    sv_session.active = true;
    for (int i = 0; i < 4; i++) sv_session.C1[i] = (uint8_t) ((seed + i) % NUM_KEYS);
    getRandomBytes(sv_session.r1, 16);

    uint8_t k1[16];
    memcpy(k1, secure_vault[sv_session.C1[0]], 16);
    for (int i = 1; i < 4; i++) {
        for (int j = 0; j < 16; j++) k1[j] ^= secure_vault[sv_session.C1[i]][j];
    }

    // C2 must be four distinct valid indices and a different set from C1:
    // C1 = {s..s+3}, C2 = {s+8..s+11} mod 16 never overlap.
    uint8_t plain[64], m3[64];
    memcpy(plain, sv_session.r1, 16);
    getRandomBytes(plain + 16, 48);          // t1 || C2 || pad || r2
    for (int i = 0; i < 4; i++) plain[32 + i] = (uint8_t) ((seed + 8 + i) % NUM_KEYS);
    mbedtls_aes_context aes;
    mbedtls_aes_init(&aes);
    mbedtls_aes_setkey_enc(&aes, k1, 128);
    for (int i = 0; i < 4; i++) {
        mbedtls_aes_crypt_ecb(&aes, MBEDTLS_AES_ENCRYPT, plain + (i * 16), m3 + (i * 16));
    }
    mbedtls_aes_free(&aes);

    uint8_t m4[32];
    bool r1_ok = false, c2_ok = false;
    const uint32_t crypto_us = svRunCryptoOnce(m3, sv_session.r1, m4, &r1_ok, &c2_ok);
    record(S_SV_CRYPTO, crypto_us);
    sv_session.active = false;

    memcpy(secure_vault, vault_snapshot, sizeof(secure_vault));

    // Feed the result forward so the iterations form a dependency chain.
    return (uint8_t) (m4[0] ^ m4[31] ^ ((r1_ok && c2_ok) ? 0x5A : 0));
}

void svResetSessions() {
    sessionReset(sv_sessions);
}

void registerSVRoutes(WebServer& server) {
    srv = &server;
    server.on("/api/auth/sv/init", HTTP_GET, handleSVInit);
    server.on("/api/auth/sv/verify", HTTP_POST, handleSVVerify);
}
