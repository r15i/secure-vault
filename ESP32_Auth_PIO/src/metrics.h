// Measurement machinery: microsecond timing, streaming statistics, and energy
// derivation. Kept separate from the protocols that generate the cost so it can
// be reasoned about without WiFi or HTTP in the picture.
#pragma once

#include <stdint.h>

#include "power_model.h"

// ---------------------------------------------------------------------------
// Timing
// ---------------------------------------------------------------------------
// esp_timer_get_time() is the same clock Arduino's micros() reads -- micros()
// is this value truncated to uint32_t, which wraps every ~71.6 minutes. Using
// the 64-bit value directly keeps microsecond resolution and makes wraparound
// unreachable, which matters because long unattended runs are a stated use
// case (make test-*-long). See design.md Decision 1.
int64_t nowUs();

// ---------------------------------------------------------------------------
// Series identifiers
// ---------------------------------------------------------------------------
// One accumulated series per measured quantity.
//   *_CRYPTO   sum of the protocol's instrumented cryptographic phases
//   *_HANDLER  total time inside the request handler (parsing, hex, response)
//   others     individual cryptographic phases
enum SeriesId : uint8_t {
    S_SV_CRYPTO = 0,
    S_SV_HANDLER,
    S_SV_KEYDERIV,   // multi-key XOR vault key derivation
    S_SV_AES_DEC,    // AES-128 ECB decrypt of M3 (4 blocks)
    S_SV_AES_ENC,    // AES-128 ECB encrypt of M4 (2 blocks)
    S_SV_HMAC,       // HMAC-SHA256 over the vault
    S_SV_ROTATE,     // vault rotation
    S_SV_WARMUP,

    S_CL_CRYPTO,
    S_CL_HANDLER,
    S_CL_AES_DEC,    // AES-128 ECB decrypt of the challenge response
    S_CL_AES_ENC,    // AES-128 ECB encrypt of the reply to the peer's challenge
    S_CL_WARMUP,

    S_SRP_CRYPTO,
    S_SRP_HANDLER,
    S_SRP_AES_DEC,   // AES-128 ECB decrypt of the challenge response
    S_SRP_AES_ENC,   // AES-128 ECB encrypt of the reply to the peer's challenge
    S_SRP_REKEY,     // AES-128 ECB decrypt of the next password
    S_SRP_WARMUP,

    S_ECC_CRYPTO,
    S_ECC_HANDLER,
    S_ECC_SIGN,      // ECDSA P-256 signature generation
    S_ECC_VERIFY,    // ECDSA P-256 signature verification
    S_ECC_SETUP,     // one-time key load at boot, NOT per-cycle cost
    S_ECC_WARMUP,

    S_OVERHEAD,      // empty instrumented region: the cost of measuring
    SERIES_COUNT
};

const char* seriesName(SeriesId id);

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------
// count/min/max/mean/stddev are exact over ALL samples via Welford's online
// algorithm -- O(1) memory, no sample storage. The median is inherently an
// order statistic, so it is computed over a bounded window of the most recent
// samples; the window size is reported alongside it so it is never mistaken for
// a whole-run median. See design.md Decision 5.
constexpr uint16_t MEDIAN_WINDOW = 256;

struct Series {
    uint32_t count = 0;
    uint32_t min_us = 0;
    uint32_t max_us = 0;
    double mean = 0.0;   // Welford running mean
    double m2 = 0.0;     // Welford sum of squared deviations

    uint32_t ring[MEDIAN_WINDOW] = {0};
    uint16_t ring_len = 0;   // samples held, saturates at MEDIAN_WINDOW
    uint16_t ring_pos = 0;   // next write index

    void add(uint32_t us);
    double stddev() const;      // 0 when count < 2
    uint32_t median() const;    // over the most recent ring_len samples
    void reset();
};

extern Series series[SERIES_COUNT];

// When false, record() drops samples. Used to run warm-up iterations without
// polluting the measured series: the first repetitions of any primitive pay
// flash-cache misses and context setup, and folding that into the mean inflates
// it unequally across protocols (design.md Decision 4).
extern bool metrics_recording_enabled;

inline void record(SeriesId id, uint32_t us) {
    if (metrics_recording_enabled) series[id].add(us);
}

// Times a region and records it on scope exit.
//
//   {
//       ScopedTimer t(S_SV_HMAC);
//       ... work ...
//   }   // recorded here
//
// Also exposes elapsed() so a caller can accumulate a crypto total without
// timing the same work twice.
class ScopedTimer {
  public:
    explicit ScopedTimer(SeriesId id) : id_(id), t0_(nowUs()) {}
    ~ScopedTimer() { record(id_, (uint32_t) elapsed()); }

    int64_t elapsed() const { return nowUs() - t0_; }

  private:
    SeriesId id_;
    int64_t t0_;
};

// Times one cryptographic phase and hands back its duration, so a handler can
// record the phase and accumulate a crypto total without timing the work twice.
//
//   PhaseTimer t(S_SV_HMAC);
//   ... work ...
//   crypto_us += t.stop();
//
// stop() is idempotent: calling it twice records once.
class PhaseTimer {
  public:
    explicit PhaseTimer(SeriesId id) : id_(id), t0_(nowUs()) {}

    uint32_t stop() {
        if (stopped_) return elapsed_;
        elapsed_ = (uint32_t) (nowUs() - t0_);
        record(id_, elapsed_);
        stopped_ = true;
        return elapsed_;
    }

  private:
    SeriesId id_;
    int64_t t0_;
    uint32_t elapsed_ = 0;
    bool stopped_ = false;
};

// ---------------------------------------------------------------------------
// Per-protocol cycle accounting
// ---------------------------------------------------------------------------
enum ProtocolId : uint8_t { P_SV = 0, P_CLASSICAL, P_SRP, P_ECC, PROTOCOL_COUNT };

struct ProtocolMetrics {
    uint32_t count = 0;        // successful cycles
    uint32_t failures = 0;     // cycles that failed verification or parsing
    double crypto_us_total = 0;  // summed measured crypto time over successes

    // Accumulated energy, derived from measured latency under each model.
    double energy_paper_uj = 0;
    double energy_device_uj = 0;
};

extern ProtocolMetrics protocols[PROTOCOL_COUNT];

// Records one successful cycle: converts the measured crypto latency to energy
// under both power models. No literature constant is involved.
void recordSuccess(ProtocolId p, uint32_t crypto_us);
void recordFailure(ProtocolId p);

// Incremented when a measured crypto time exceeds its handler time, which
// should be impossible; exposed in telemetry so it cannot pass unnoticed.
extern uint32_t invariant_violations;

// Characterises the cost of an empty instrumented region (task 4.4).
void measureInstrumentationOverhead(uint16_t samples = 200);

// Clears every series and counter (task 8.6).
void resetAllMetrics();
