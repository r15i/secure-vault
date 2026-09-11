#include "metrics.h"

#include <esp_timer.h>
#include <math.h>
#include <string.h>

int64_t nowUs() {
    return esp_timer_get_time();
}

Series series[SERIES_COUNT];
ProtocolMetrics protocols[PROTOCOL_COUNT];
uint32_t invariant_violations = 0;
bool metrics_recording_enabled = true;

static const char* const kSeriesNames[SERIES_COUNT] = {
    "sv_crypto", "sv_handler", "sv_keyderiv", "sv_aes_dec", "sv_aes_enc",
    "sv_hmac", "sv_rotate", "sv_warmup",
    "cl_crypto", "cl_handler", "cl_aes_dec", "cl_aes_enc", "cl_warmup",
    "srp_crypto", "srp_handler", "srp_aes_dec", "srp_aes_enc", "srp_rekey",
    "srp_warmup",
    "ecc_crypto", "ecc_handler", "ecc_sign", "ecc_verify", "ecc_setup",
    "ecc_warmup",
    "instrumentation_overhead",
};

const char* seriesName(SeriesId id) {
    return (id < SERIES_COUNT) ? kSeriesNames[id] : "unknown";
}

// --- Series ---------------------------------------------------------------

void Series::add(uint32_t us) {
    if (count == 0) {
        min_us = us;
        max_us = us;
    } else {
        if (us < min_us) min_us = us;
        if (us > max_us) max_us = us;
    }

    // Welford: exact mean and variance over all samples, O(1) memory.
    count++;
    const double delta = (double) us - mean;
    mean += delta / (double) count;
    m2 += delta * ((double) us - mean);

    ring[ring_pos] = us;
    ring_pos = (uint16_t) ((ring_pos + 1) % MEDIAN_WINDOW);
    if (ring_len < MEDIAN_WINDOW) ring_len++;
}

double Series::stddev() const {
    if (count < 2) return 0.0;
    return sqrt(m2 / (double) (count - 1));
}

uint32_t Series::median() const {
    if (ring_len == 0) return 0;

    uint32_t tmp[MEDIAN_WINDOW];
    memcpy(tmp, ring, sizeof(uint32_t) * ring_len);

    // Insertion sort: ring_len <= 256 and this runs only when telemetry is
    // requested, never inside a timed region.
    for (uint16_t i = 1; i < ring_len; i++) {
        const uint32_t v = tmp[i];
        int16_t j = (int16_t) (i - 1);
        while (j >= 0 && tmp[j] > v) {
            tmp[j + 1] = tmp[j];
            j--;
        }
        tmp[j + 1] = v;
    }

    const uint16_t mid = ring_len / 2;
    if (ring_len % 2 == 1) return tmp[mid];
    return (uint32_t) (((uint64_t) tmp[mid - 1] + tmp[mid]) / 2);
}

void Series::reset() {
    count = 0;
    min_us = 0;
    max_us = 0;
    mean = 0.0;
    m2 = 0.0;
    ring_len = 0;
    ring_pos = 0;
}

// --- Protocol accounting --------------------------------------------------

void recordSuccess(ProtocolId p, uint32_t crypto_us) {
    ProtocolMetrics& m = protocols[p];
    m.count++;
    m.crypto_us_total += (double) crypto_us;
    m.energy_paper_uj += energyUj(PAPER_POWER_MW, (double) crypto_us);
    m.energy_device_uj += energyUj(DEVICE_POWER_MW, (double) crypto_us);
}

void recordFailure(ProtocolId p) {
    protocols[p].failures++;
}

// --- Instrumentation overhead --------------------------------------------

void measureInstrumentationOverhead(uint16_t samples) {
    // An instrumented region containing no work. What remains is the cost of
    // reading the clock twice plus the record() call -- the floor below which
    // no measured phase can be trusted (spec: instrumentation overhead is
    // bounded and disclosed).
    for (uint16_t i = 0; i < samples; i++) {
        ScopedTimer t(S_OVERHEAD);
        (void) t;
    }
}

void resetAllMetrics() {
    for (uint8_t i = 0; i < SERIES_COUNT; i++) series[i].reset();
    for (uint8_t i = 0; i < PROTOCOL_COUNT; i++) protocols[i] = ProtocolMetrics();
    invariant_violations = 0;
}
