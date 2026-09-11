#include "benchmark.h"

#include <Arduino.h>
#include <stdio.h>

#include "auth_classical.h"
#include "auth_ecc.h"
#include "auth_srp.h"
#include "auth_sv.h"
#include "metrics.h"

// The sink every iteration writes through. `volatile` plus the seed dependency
// chain (each iteration consumes the previous iteration's output) is what stops
// the compiler deleting or hoisting the loop. A benchmark that measures a loop
// the optimiser removed reports a beautiful, entirely fictional number --
// design.md Decision 3.
static volatile uint8_t g_sink = 0;

// Wall-clock ceiling for one batch request. ECDSA is tens of milliseconds per
// operation, so the same K that costs milliseconds for AES would block the
// WebServer loop for a minute and trip the task watchdog.
static constexpr uint32_t MAX_BATCH_MS = 2000;
static constexpr uint16_t CHUNK = 16;   // iterations between watchdog yields

struct ProtocolSpec {
    const char* name;
    uint8_t (*runOnce)(uint8_t);
    SeriesId crypto;
    SeriesId warmup;
    uint16_t warmup_iters;
    uint32_t max_k;
};

static const ProtocolSpec kProtocols[] = {
    {"sv",        svBenchmarkOnce,  S_SV_CRYPTO,  S_SV_WARMUP,  8, 100000},
    {"classical", clBenchmarkOnce,  S_CL_CRYPTO,  S_CL_WARMUP,  8, 200000},
    {"srp",       srpBenchmarkOnce, S_SRP_CRYPTO, S_SRP_WARMUP, 8, 200000},
    {"ecc",       eccBenchmarkOnce, S_ECC_CRYPTO, S_ECC_WARMUP, 2,    500},
};
static constexpr uint8_t kProtocolCount = 4;

static WebServer* srv = nullptr;

static const ProtocolSpec* findProtocol(const String& name) {
    for (uint8_t i = 0; i < kProtocolCount; i++) {
        if (name == kProtocols[i].name) return &kProtocols[i];
    }
    return nullptr;
}

static void handleBenchmark() {
    const String proto = srv->hasArg("protocol") ? srv->arg("protocol") : String("");
    const ProtocolSpec* spec = findProtocol(proto);
    if (spec == nullptr) {
        srv->send(400, "application/json",
                  "{\"error\":\"Unknown protocol\",\"cause\":\"malformed_request\","
                  "\"valid\":[\"sv\",\"classical\",\"srp\",\"ecc\"]}");
        return;
    }

    const uint32_t k = srv->hasArg("k") ? (uint32_t) srv->arg("k").toInt() : 1000;
    if (k == 0) {
        srv->send(400, "application/json",
                  "{\"error\":\"k must be >= 1\",\"cause\":\"malformed_request\"}");
        return;
    }
    if (k > spec->max_k) {
        char err[192];
        snprintf(err, sizeof(err),
                 "{\"error\":\"k exceeds the maximum for this protocol\","
                 "\"cause\":\"malformed_request\",\"requested\":%u,\"max_k\":%u}",
                 k, spec->max_k);
        srv->send(400, "application/json", err);
        return;
    }

    uint8_t seed = g_sink;

    // --- Warm-up: excluded from the measured series, reported on its own ------
    // The first repetitions pay flash-cache misses and mbedTLS context setup.
    metrics_recording_enabled = false;
    const int64_t warm_t0 = nowUs();
    for (uint16_t i = 0; i < spec->warmup_iters; i++) {
        seed = spec->runOnce(seed);
    }
    const int64_t warm_total = nowUs() - warm_t0;
    metrics_recording_enabled = true;
    if (spec->warmup_iters > 0) {
        record(spec->warmup, (uint32_t) (warm_total / spec->warmup_iters));
    }

    // --- Measured loop -------------------------------------------------------
    // The amortised figure (total / k) is the primary result: dividing one
    // timed region by K drives clock quantisation three orders of magnitude
    // below the differences being resolved (design.md Decision 2).
    const int64_t t0 = nowUs();
    uint32_t done = 0;
    bool truncated = false;

    while (done < k) {
        const uint32_t chunk = (k - done < CHUNK) ? (uint32_t) (k - done) : CHUNK;
        for (uint32_t i = 0; i < chunk; i++) {
            seed = spec->runOnce(seed);
        }
        done += chunk;

        // Keep the watchdog fed and the WiFi stack serviced, and stop before
        // the time budget rather than blocking the server.
        yield();
        if ((uint32_t) ((nowUs() - t0) / 1000) >= MAX_BATCH_MS && done < k) {
            truncated = true;
            break;
        }
    }

    const int64_t total_us = nowUs() - t0;
    g_sink = seed;

    const double amortised_us = (done > 0) ? (double) total_us / (double) done : 0.0;
    const Series& cs = series[spec->crypto];

    // Truncation is reported, never silent: a shortened run must not read as a
    // completed one.
    char json[1024];
    snprintf(json, sizeof(json),
             "{\"protocol\":\"%s\","
             "\"requested_k\":%u,\"completed_k\":%u,\"truncated\":%s,"
             "\"max_batch_ms\":%u,\"total_us\":%lld,"
             "\"amortised_us_per_op\":%.4f,"
             "\"warmup\":{\"iterations\":%u,\"mean_us\":%.3f,\"excluded\":true},"
             "\"per_iteration\":{\"count\":%u,\"min_us\":%u,\"max_us\":%u,"
             "\"mean_us\":%.3f,\"median_us\":%u,\"median_window\":%u,\"stddev_us\":%.3f},"
             "\"energy_per_op_uj\":{\"paper\":%.6f,\"device\":%.6f},"
             "\"power_mw\":{\"paper\":%.2f,\"device\":%.2f},"
             "\"instrumentation_overhead_us\":%.3f,"
             "\"opt_level\":\"%s\"}",
             spec->name, k, done, truncated ? "true" : "false",
             (unsigned) MAX_BATCH_MS, (long long) total_us,
             amortised_us,
             spec->warmup_iters,
             (spec->warmup_iters > 0) ? (double) warm_total / spec->warmup_iters : 0.0,
             cs.count, cs.min_us, cs.max_us, cs.mean, cs.median(),
             (unsigned) MEDIAN_WINDOW, cs.stddev(),
             energyUj(PAPER_POWER_MW, amortised_us), energyUj(DEVICE_POWER_MW, amortised_us),
             (double) PAPER_POWER_MW, (double) DEVICE_POWER_MW,
             series[S_OVERHEAD].mean,
#ifdef BUILD_OPT_LEVEL
             BUILD_OPT_LEVEL
#else
             "unknown"
#endif
    );
    srv->send(200, "application/json", json);
}

static void handleReset() {
    resetAllMetrics();
    // Return the Secure Vault to its documented boot state. A reset is the point
    // at which the host re-syncs its mirror (test_client.reset_host_state), and
    // without this the two would disagree about the key material from the first
    // cycle onwards -- the statistics would be clean and every SV cycle would fail.
    initSecureVault();
    initSRP();
    // Drop any pending authentication sessions too: a reset means both sides
    // start from a known state, and a stale session identifier must not survive.
    clResetSessions();
    srpResetSessions();
    svResetSessions();
    eccResetSessions();
    // Re-characterise the instrumentation overhead: the reset cleared it, and
    // every later figure is interpreted against it.
    measureInstrumentationOverhead();
    char json[192];
    snprintf(json, sizeof(json),
             "{\"status\":\"reset\",\"vault_reinitialised\":true,"
             "\"instrumentation_overhead_us\":%.3f,"
             "\"overhead_samples\":%u}",
             series[S_OVERHEAD].mean, series[S_OVERHEAD].count);
    srv->send(200, "application/json", json);
}

void registerBenchmarkRoutes(WebServer& server) {
    srv = &server;
    server.on("/api/benchmark", HTTP_GET, handleBenchmark);
    server.on("/api/reset", HTTP_POST, handleReset);
}
