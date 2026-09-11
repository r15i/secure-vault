#include "auth_ecc.h"

#include <esp_random.h>
#include <stdio.h>
#include <string.h>

#include <mbedtls/bignum.h>
#include <mbedtls/ecdsa.h>
#include <mbedtls/ecp.h>
#include <mbedtls/md.h>

#include "crypto_util.h"
#include "ecc_keys.h"
#include "metrics.h"
#include "sessions.h"

// Wire sizes: challenge 32 B, signature r||s 64 B.
static constexpr size_t CHALLENGE_LEN = 32;
static constexpr size_t SIG_LEN = 64;
// POST body: peer_challenge(32) || peer_sig(64) = 96 bytes = 192 hex chars.
static constexpr size_t VERIFY_BODY_LEN = CHALLENGE_LEN + SIG_LEN;

struct ECCSession {
    bool active = false;
    uint8_t challenge[CHALLENGE_LEN];
};

static ECCSession ecc_session;
static SessionTable ecc_sessions;
static WebServer* srv = nullptr;

static mbedtls_ecp_group grp;
static mbedtls_mpi device_d;         // device private scalar
static mbedtls_ecp_point host_Q;     // peer public point
static mbedtls_ecp_point device_Q;   // device public point (batch verification)
static bool ecc_ready = false;

// RNG for ECDSA signing: the hardware RNG directly, avoiding a CTR-DRBG
// instance in the timed path (design.md Decision 7).
static int hwRng(void* ctx, unsigned char* out, size_t len) {
    (void) ctx;
    esp_fill_random(out, len);
    return 0;
}

// SHA-256 via the generic message-digest interface, which is stable across
// mbedTLS versions.
static void sha256(const uint8_t* in, size_t len, uint8_t out[32]) {
    mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), in, len, out);
}

bool initECC() {
    PhaseTimer t_setup(S_ECC_SETUP);

    mbedtls_ecp_group_init(&grp);
    mbedtls_mpi_init(&device_d);
    mbedtls_ecp_point_init(&host_Q);
    mbedtls_ecp_point_init(&device_Q);

    bool ok = mbedtls_ecp_group_load(&grp, MBEDTLS_ECP_DP_SECP256R1) == 0;
    ok = ok && mbedtls_mpi_read_binary(&device_d, ECC_DEVICE_PRIVATE,
                                       sizeof(ECC_DEVICE_PRIVATE)) == 0;
    ok = ok && mbedtls_ecp_point_read_binary(&grp, &host_Q, ECC_HOST_PUBLIC,
                                             sizeof(ECC_HOST_PUBLIC)) == 0;
    ok = ok && mbedtls_ecp_check_pubkey(&grp, &host_Q) == 0;
    ok = ok && mbedtls_ecp_point_read_binary(&grp, &device_Q, ECC_DEVICE_PUBLIC,
                                             sizeof(ECC_DEVICE_PUBLIC)) == 0;
    ok = ok && mbedtls_ecp_check_pubkey(&grp, &device_Q) == 0;

    t_setup.stop();
    ecc_ready = ok;
    return ok;
}

uint32_t eccRunCryptoOnce(const uint8_t* peer_challenge,
                          const uint8_t* peer_sig,
                          const uint8_t* our_challenge,
                          uint8_t* our_sig_out,
                          bool* verify_ok,
                          uint32_t* sign_us,
                          uint32_t* verify_us) {
    uint32_t crypto_us = 0;
    if (verify_ok) *verify_ok = false;

    uint8_t hash[32];
    mbedtls_mpi r, s;
    mbedtls_mpi_init(&r);
    mbedtls_mpi_init(&s);

    // Phase: sign the peer's challenge with the device private key.
    PhaseTimer t_sign(S_ECC_SIGN);
    sha256(peer_challenge, CHALLENGE_LEN, hash);
    const int sign_rc =
        mbedtls_ecdsa_sign(&grp, &r, &s, &device_d, hash, sizeof(hash), hwRng, nullptr);
    if (sign_rc == 0) {
        mbedtls_mpi_write_binary(&r, our_sig_out, 32);
        mbedtls_mpi_write_binary(&s, our_sig_out + 32, 32);
    }
    const uint32_t d_sign = t_sign.stop();
    if (sign_us) *sign_us = d_sign;
    crypto_us += d_sign;

    // Phase: verify the peer's signature over the challenge we issued.
    PhaseTimer t_verify(S_ECC_VERIFY);
    sha256(our_challenge, CHALLENGE_LEN, hash);
    mbedtls_mpi vr, vs;
    mbedtls_mpi_init(&vr);
    mbedtls_mpi_init(&vs);
    mbedtls_mpi_read_binary(&vr, peer_sig, 32);
    mbedtls_mpi_read_binary(&vs, peer_sig + 32, 32);
    const int verify_rc = mbedtls_ecdsa_verify(&grp, hash, sizeof(hash), &host_Q, &vr, &vs);
    const uint32_t d_verify = t_verify.stop();
    if (verify_us) *verify_us = d_verify;
    crypto_us += d_verify;

    if (verify_ok) *verify_ok = (sign_rc == 0 && verify_rc == 0);

    mbedtls_mpi_free(&r);
    mbedtls_mpi_free(&s);
    mbedtls_mpi_free(&vr);
    mbedtls_mpi_free(&vs);
    return crypto_us;
}

uint8_t eccBenchmarkOnce(uint8_t seed) {
    // Carried between iterations: the signature produced last time, and the
    // challenge it was made over. Verifying THAT is verifying a genuinely valid
    // signature, and it makes the iterations a dependency chain the optimiser
    // cannot collapse. The host's private key is not on the device, so batch
    // verification necessarily uses the device's own public key -- the same
    // primitive at the same cost.
    static bool primed = false;
    static uint8_t prev_chal[CHALLENGE_LEN];
    static uint8_t prev_sig[SIG_LEN];

    uint8_t hash[32];
    mbedtls_mpi r, s;
    mbedtls_mpi_init(&r);
    mbedtls_mpi_init(&s);

    if (!primed) {
        // One untimed priming signature so the first verification has valid input.
        getRandomBytes(prev_chal, CHALLENGE_LEN);
        sha256(prev_chal, CHALLENGE_LEN, hash);
        if (mbedtls_ecdsa_sign(&grp, &r, &s, &device_d, hash, sizeof(hash), hwRng, nullptr) == 0) {
            mbedtls_mpi_write_binary(&r, prev_sig, 32);
            mbedtls_mpi_write_binary(&s, prev_sig + 32, 32);
            primed = true;
        }
    }

    uint8_t chal[CHALLENGE_LEN];
    getRandomBytes(chal, CHALLENGE_LEN);
    chal[0] ^= seed;
    uint8_t sig[SIG_LEN] = {0};

    // Phase: sign.
    PhaseTimer t_sign(S_ECC_SIGN);
    sha256(chal, CHALLENGE_LEN, hash);
    const int sign_rc =
        mbedtls_ecdsa_sign(&grp, &r, &s, &device_d, hash, sizeof(hash), hwRng, nullptr);
    if (sign_rc == 0) {
        mbedtls_mpi_write_binary(&r, sig, 32);
        mbedtls_mpi_write_binary(&s, sig + 32, 32);
    }
    uint32_t crypto_us = t_sign.stop();

    // Phase: verify the previous iteration's signature.
    PhaseTimer t_verify(S_ECC_VERIFY);
    sha256(prev_chal, CHALLENGE_LEN, hash);
    mbedtls_mpi vr, vs;
    mbedtls_mpi_init(&vr);
    mbedtls_mpi_init(&vs);
    mbedtls_mpi_read_binary(&vr, prev_sig, 32);
    mbedtls_mpi_read_binary(&vs, prev_sig + 32, 32);
    const int verify_rc = mbedtls_ecdsa_verify(&grp, hash, sizeof(hash), &device_Q, &vr, &vs);
    crypto_us += t_verify.stop();

    record(S_ECC_CRYPTO, crypto_us);

    if (sign_rc == 0) {
        memcpy(prev_chal, chal, CHALLENGE_LEN);
        memcpy(prev_sig, sig, SIG_LEN);
    }

    mbedtls_mpi_free(&r);
    mbedtls_mpi_free(&s);
    mbedtls_mpi_free(&vr);
    mbedtls_mpi_free(&vs);

    return (uint8_t) (sig[0] ^ sig[63] ^ (verify_rc == 0 ? 0xA5 : 0));
}

static void handleECCInit() {
    if (!ecc_ready) {
        srv->send(503, "application/json",
                  "{\"error\":\"ECC key material unavailable\", \"cause\":\"no_key_material\"}");
        return;
    }
    uint8_t challenge[CHALLENGE_LEN];
    getRandomBytes(challenge, CHALLENGE_LEN);
    const uint32_t sid = sessionOpen(ecc_sessions, challenge, CHALLENGE_LEN);

    char chalHex[CHALLENGE_LEN * 2 + 1];
    bytesToHexString(challenge, CHALLENGE_LEN, chalHex);
    char response[160];
    sprintf(response, "{\"sid\":%u, \"challenge\":\"%s\"}", sid, chalHex);
    srv->send(200, "application/json", response);
}

static void handleECCVerify() {
    ScopedTimer handlerTimer(S_ECC_HANDLER);

    if (!ecc_ready) {
        recordFailure(P_ECC);
        srv->send(503, "application/json",
                  "{\"error\":\"ECC key material unavailable\", \"cause\":\"no_key_material\"}");
        return;
    }
    // Only the request holding this session's identifier may consume it, so a
    // peer with a pending session cannot be cancelled by anyone else.
    const uint32_t sid = (uint32_t) strtoul(srv->arg("sid").c_str(), nullptr, 10);
    if (!sessionTake(ecc_sessions, sid, ecc_session.challenge, CHALLENGE_LEN)) {
        recordFailure(P_ECC);
        srv->send(400, "application/json",
                  "{\"error\":\"No such session\", \"cause\":\"no_session\"}");
        return;
    }
    ecc_session.active = true;

    String body = srv->arg("plain");
    if (body.length() < VERIFY_BODY_LEN * 2) {
        recordFailure(P_ECC);
        srv->send(400, "application/json",
                  "{\"error\":\"Expected 96 bytes: challenge(32) || signature(64)\", "
                  "\"cause\":\"malformed_request\"}");
        return;
    }

    uint8_t buf[VERIFY_BODY_LEN];
    hexStringToBytes(body.c_str(), buf, VERIFY_BODY_LEN);
    const uint8_t* peer_challenge = buf;
    const uint8_t* peer_sig = buf + CHALLENGE_LEN;

    uint8_t device_sig[SIG_LEN] = {0};
    bool verify_ok = false;
    uint32_t sign_us = 0, verify_us = 0;
    const uint32_t crypto_us =
        eccRunCryptoOnce(peer_challenge, peer_sig, ecc_session.challenge, device_sig,
                         &verify_ok, &sign_us, &verify_us);

    // Single-use session: a signature replayed from an earlier cycle cannot
    // satisfy the next one, because the challenge it was made over is gone.
    ecc_session.active = false;

    if (!verify_ok) {
        recordFailure(P_ECC);
        srv->send(401, "application/json",
                  "{\"status\":\"failed\", \"error\":\"Signature verification failed\", "
                  "\"cause\":\"verification_failed\"}");
        return;
    }

    record(S_ECC_CRYPTO, crypto_us);
    if ((int64_t) crypto_us > handlerTimer.elapsed()) invariant_violations++;
    recordSuccess(P_ECC, crypto_us);

    const ProtocolMetrics& m = protocols[P_ECC];
    char sigHex[SIG_LEN * 2 + 1];
    bytesToHexString(device_sig, SIG_LEN, sigHex);
    char response[512];
    sprintf(response,
            "{\"status\":\"success\", \"signature\":\"%s\", "
            "\"crypto_us\":%u, \"handler_us\":%lld, "
            "\"sign_us\":%u, \"verify_us\":%u, "
            "\"energy_uj\":{\"paper\":%.4f, \"device\":%.4f}, "
            "\"total_energy_uj\":{\"paper\":%.4f, \"device\":%.4f}}",
            sigHex, crypto_us, (long long) handlerTimer.elapsed(), sign_us, verify_us,
            energyUj(PAPER_POWER_MW, crypto_us), energyUj(DEVICE_POWER_MW, crypto_us),
            m.energy_paper_uj, m.energy_device_uj);
    srv->send(200, "application/json", response);
}

void eccResetSessions() {
    sessionReset(ecc_sessions);
}

void registerECCRoutes(WebServer& server) {
    srv = &server;
    server.on("/api/auth/ecc/init", HTTP_GET, handleECCInit);
    server.on("/api/auth/ecc/verify", HTTP_POST, handleECCVerify);
}
