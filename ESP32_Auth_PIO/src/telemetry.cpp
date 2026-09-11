#include "telemetry.h"

#include <WiFi.h>
#include <stdio.h>

#include "dashboard.h"
#include "metrics.h"

#ifndef BUILD_OPT_LEVEL
  #define BUILD_OPT_LEVEL "unknown"
#endif

// Hardware acceleration on this build. Determined by the framework's sdkconfig,
// not assumed: it is the primary explanation for divergence from the reference
// paper's ratios (design.md Decision 8).
#if defined(CONFIG_MBEDTLS_HARDWARE_AES)
  #define HW_AES "true"
#else
  #define HW_AES "false"
#endif
#if defined(CONFIG_MBEDTLS_HARDWARE_SHA)
  #define HW_SHA "true"
#else
  #define HW_SHA "false"
#endif
#if defined(CONFIG_MBEDTLS_HARDWARE_ECC)
  #define HW_ECC "true"
#else
  #define HW_ECC "false"
#endif

static WebServer* srv = nullptr;

static void handleRoot() {
    // charset must be declared: the page contains UTF-8 (µ), and without it a
    // browser falls back to Latin-1 and renders "Âµs". Belt and braces - the
    // page also carries <meta charset>. Not reproducible against the mock,
    // because Flask sets the charset on the Content-Type itself.
    srv->send(200, "text/html; charset=utf-8", DASHBOARD_HTML);
}

static void handleStatus() {
    char json[192];
    snprintf(json, sizeof(json),
             "{\"rssi\":%d,\"uptime_s\":%lu,\"ip\":\"%s\"}",
             WiFi.RSSI(), (unsigned long) (millis() / 1000),
             WiFi.localIP().toString().c_str());
    srv->send(200, "application/json", json);
}

// One measured series. The median is labelled with its window so it is never
// mistaken for a whole-run median; mean and stddev are exact over all samples.
static String statsJson(const Series& s) {
    char buf[256];
    snprintf(buf, sizeof(buf),
             "{\"count\":%u,\"min_us\":%u,\"max_us\":%u,\"mean_us\":%.3f,"
             "\"median_us\":%u,\"median_window\":%u,\"stddev_us\":%.3f}",
             s.count, s.min_us, s.max_us, s.mean, s.median(),
             (unsigned) MEDIAN_WINDOW, s.stddev());
    return String(buf);
}

// Energy under both models. Per-cycle is derived from the measured mean crypto
// latency; the total is the accumulated sum of per-cycle measurements, so
// total == count x per-cycle by construction.
static String energyJson(const ProtocolMetrics& m, const Series& crypto) {
    char buf[384];
    snprintf(buf, sizeof(buf),
             "{\"paper\":{\"power_mw\":%.2f,\"per_cycle_uj\":%.4f,\"total_uj\":%.4f,"
             "\"total_wh\":%.12f},"
             "\"device\":{\"power_mw\":%.2f,\"per_cycle_uj\":%.4f,\"total_uj\":%.4f,"
             "\"total_wh\":%.12f}}",
             (double) PAPER_POWER_MW, energyUj(PAPER_POWER_MW, crypto.mean),
             m.energy_paper_uj, m.energy_paper_uj * UJ_TO_WH,
             (double) DEVICE_POWER_MW, energyUj(DEVICE_POWER_MW, crypto.mean),
             m.energy_device_uj, m.energy_device_uj * UJ_TO_WH);
    return String(buf);
}

static String protocolJson(ProtocolId p, SeriesId crypto, SeriesId handler,
                           const SeriesId* phases, const char* const* phase_names,
                           uint8_t phase_count) {
    const ProtocolMetrics& m = protocols[p];
    String out = "{";
    out += "\"count\":" + String(m.count);
    out += ",\"failures\":" + String(m.failures);
    out += ",\"crypto_us\":" + statsJson(series[crypto]);
    out += ",\"handler_us\":" + statsJson(series[handler]);
    out += ",\"phases\":{";
    for (uint8_t i = 0; i < phase_count; i++) {
        if (i) out += ",";
        out += "\"";
        out += phase_names[i];
        out += "\":" + statsJson(series[phases[i]]);
    }
    out += "}";
    out += ",\"energy\":" + energyJson(m, series[crypto]);
    out += "}";
    return out;
}

static void handleEnergy() {
    String out = "{";

    out += "\"uptime_s\":" + String((unsigned long) (millis() / 1000));
    out += ",\"rssi\":" + String(WiFi.RSSI());

    // Power constants travel with the figures they produced: no reported
    // energy is ever separated from the assumption behind it.
    char pm[512];
    snprintf(pm, sizeof(pm),
             ",\"power_model\":{"
             "\"paper\":{\"power_mw\":%.2f,\"current_ma\":%.2f,\"voltage_v\":%.2f,"
             "\"source\":\"%s\"},"
             "\"device\":{\"power_mw\":%.2f,\"current_ma\":%.2f,\"voltage_v\":%.2f,"
             "\"source\":\"%s\"},"
             "\"formula\":\"energy_uJ = power_mW * latency_us / 1000\","
             "\"note\":\"Ratios between protocols are invariant to both constants.\"}",
             (double) PAPER_POWER_MW, (double) PAPER_CURRENT_MA, (double) PAPER_VOLTAGE_V,
             PAPER_POWER_SOURCE,
             (double) DEVICE_POWER_MW, (double) DEVICE_CURRENT_MA, (double) DEVICE_VOLTAGE_V,
             DEVICE_POWER_SOURCE);
    out += pm;

    out += ",\"hw_accel\":{\"aes\":" HW_AES ",\"sha\":" HW_SHA ",\"ecc_p256\":" HW_ECC
           ",\"opt_level\":\"" BUILD_OPT_LEVEL "\"}";

    out += ",\"instrumentation\":{\"overhead_us\":" + statsJson(series[S_OVERHEAD]) + "}";
    out += ",\"invariant_violations\":" + String(invariant_violations);

    static const SeriesId sv_phases[] = {S_SV_KEYDERIV, S_SV_AES_DEC, S_SV_AES_ENC,
                                         S_SV_HMAC, S_SV_ROTATE, S_SV_WARMUP};
    static const char* const sv_names[] = {"keyderiv", "aes_dec", "aes_enc",
                                           "hmac", "rotate", "warmup"};
    static const SeriesId cl_phases[] = {S_CL_AES_DEC, S_CL_AES_ENC, S_CL_WARMUP};
    static const char* const cl_names[] = {"aes_dec", "aes_enc", "warmup"};
    static const SeriesId srp_phases[] = {S_SRP_AES_DEC, S_SRP_AES_ENC, S_SRP_REKEY,
                                          S_SRP_WARMUP};
    static const char* const srp_names[] = {"aes_dec", "aes_enc", "rekey", "warmup"};
    static const SeriesId ecc_phases[] = {S_ECC_SIGN, S_ECC_VERIFY, S_ECC_SETUP, S_ECC_WARMUP};
    static const char* const ecc_names[] = {"sign", "verify", "setup", "warmup"};

    out += ",\"protocols\":{";
    out += "\"sv\":" + protocolJson(P_SV, S_SV_CRYPTO, S_SV_HANDLER, sv_phases, sv_names, 6);
    out += ",\"classical\":" +
           protocolJson(P_CLASSICAL, S_CL_CRYPTO, S_CL_HANDLER, cl_phases, cl_names, 3);
    out += ",\"srp\":" +
           protocolJson(P_SRP, S_SRP_CRYPTO, S_SRP_HANDLER, srp_phases, srp_names, 4);
    out += ",\"ecc\":" +
           protocolJson(P_ECC, S_ECC_CRYPTO, S_ECC_HANDLER, ecc_phases, ecc_names, 4);
    out += "}}";

    srv->send(200, "application/json", out);
}

void registerTelemetryRoutes(WebServer& server) {
    srv = &server;
    server.on("/", HTTP_GET, handleRoot);
    server.on("/api/status", HTTP_GET, handleStatus);
    server.on("/api/energy", HTTP_GET, handleEnergy);
}
