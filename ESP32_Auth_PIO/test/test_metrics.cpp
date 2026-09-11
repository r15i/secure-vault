// Host-side unit tests for the measurement arithmetic (task 4.5).
//
// These run on your machine, not the device -- the logic under test is pure
// arithmetic, and testing it here means a timer bug cannot hide behind a
// hardware-only test cycle.
//
//   make test-native
//
// Covers:
//   - duration arithmetic across counter wraparound, for both the int64 clock
//     the firmware uses and the uint32 micros() form it deliberately avoids
//   - Welford mean/stddev against a known-answer dataset
//   - the windowed median, including the even/odd and ring-wrap cases
//
// The Series implementation is duplicated here rather than included, because
// src/metrics.h pulls in ESP-IDF headers. The two must stay in step; any change
// to Series::add, stddev, or median belongs in both. The duplication is
// deliberate and cheap compared with cross-compiling the test.

#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>

static int failures = 0;

#define CHECK(cond, msg)                                                    \
    do {                                                                    \
        if (!(cond)) {                                                      \
            printf("  FAIL: %s  (%s:%d)\n", msg, __FILE__, __LINE__);       \
            failures++;                                                     \
        }                                                                   \
    } while (0)

#define CHECK_NEAR(a, b, tol, msg)                                          \
    do {                                                                    \
        if (fabs((double) (a) - (double) (b)) > (tol)) {                     \
            printf("  FAIL: %s  (got %.6f, want %.6f)\n", msg,              \
                   (double) (a), (double) (b));                             \
            failures++;                                                     \
        }                                                                   \
    } while (0)

// --------------------------------------------------------------------------
// Mirror of src/metrics.h Series
// --------------------------------------------------------------------------
static const uint16_t MEDIAN_WINDOW = 256;

struct Series {
    uint32_t count = 0;
    uint32_t min_us = 0;
    uint32_t max_us = 0;
    double mean = 0.0;
    double m2 = 0.0;
    uint32_t ring[MEDIAN_WINDOW] = {0};
    uint16_t ring_len = 0;
    uint16_t ring_pos = 0;

    void add(uint32_t us) {
        if (count == 0) {
            min_us = us;
            max_us = us;
        } else {
            if (us < min_us) min_us = us;
            if (us > max_us) max_us = us;
        }
        count++;
        const double delta = (double) us - mean;
        mean += delta / (double) count;
        m2 += delta * ((double) us - mean);
        ring[ring_pos] = us;
        ring_pos = (uint16_t) ((ring_pos + 1) % MEDIAN_WINDOW);
        if (ring_len < MEDIAN_WINDOW) ring_len++;
    }

    double stddev() const {
        if (count < 2) return 0.0;
        return sqrt(m2 / (double) (count - 1));
    }

    uint32_t median() const {
        if (ring_len == 0) return 0;
        uint32_t tmp[MEDIAN_WINDOW];
        memcpy(tmp, ring, sizeof(uint32_t) * ring_len);
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
};

// --------------------------------------------------------------------------
// Duration arithmetic
// --------------------------------------------------------------------------
// What the firmware does: subtract two int64 microsecond readings.
static int64_t duration_int64(int64_t t0, int64_t t1) { return t1 - t0; }

// What Arduino's micros() would force: unsigned 32-bit subtraction. Correct
// across wraparound *only* while every step stays unsigned, which is exactly
// the fragility design.md Decision 1 avoids.
static uint32_t duration_uint32(uint32_t t0, uint32_t t1) { return t1 - t0; }

static void test_duration_arithmetic() {
    printf("duration arithmetic\n");

    CHECK(duration_int64(1000, 1250) == 250, "normal interval");
    CHECK(duration_int64(0, 0) == 0, "zero interval");

    // The int64 clock: esp_timer_get_time() counts microseconds since boot and
    // would need ~292,000 years to overflow, so wraparound is unreachable.
    const int64_t big = 4294967295LL;  // where uint32 micros() would wrap
    CHECK(duration_int64(big - 100, big + 100) == 200,
          "int64 clock spans the uint32 wrap point without special handling");
    CHECK(duration_int64(big, big + 1) == 1, "int64 clock one tick past the wrap point");

    // The uint32 form is correct across the wrap, and must never be negative
    // or near-maximum for a short interval.
    const uint32_t before = 0xFFFFFFF0u;
    const uint32_t after = 0x0000000Fu;  // 31 us later, having wrapped
    CHECK(duration_uint32(before, after) == 31, "uint32 subtraction spans wraparound");
    CHECK(duration_uint32(before, after) < 1000,
          "wraparound does not yield an implausibly large duration");

    // The failure mode: promoting to a signed type before subtracting.
    const long long naive = (long long) after - (long long) before;
    CHECK(naive < 0, "naive signed subtraction goes negative -- the bug being avoided");

    printf("  ok\n");
}

// --------------------------------------------------------------------------
// Statistics
// --------------------------------------------------------------------------
static void test_welford_known_answer() {
    printf("Welford mean/stddev\n");

    // Sample {2,4,4,4,5,5,7,9}: mean 5, population sd 2, sample sd ~2.13809.
    const uint32_t data[] = {2, 4, 4, 4, 5, 5, 7, 9};
    Series s;
    for (uint32_t v : data) s.add(v);

    CHECK(s.count == 8, "count");
    CHECK(s.min_us == 2, "min");
    CHECK(s.max_us == 9, "max");
    CHECK_NEAR(s.mean, 5.0, 1e-9, "mean");
    CHECK_NEAR(s.stddev(), 2.13809, 1e-5, "sample stddev");

    printf("  ok\n");
}

static void test_single_and_empty() {
    printf("single sample and empty series\n");

    Series empty;
    CHECK(empty.count == 0, "empty count is zero");
    CHECK_NEAR(empty.stddev(), 0.0, 1e-12, "empty stddev is zero, not NaN");
    CHECK(empty.median() == 0, "empty median is zero");

    Series one;
    one.add(42);
    CHECK(one.count == 1, "count");
    CHECK(one.min_us == 42 && one.max_us == 42, "min == max == the sample");
    CHECK_NEAR(one.mean, 42.0, 1e-12, "mean equals the sample");
    CHECK_NEAR(one.stddev(), 0.0, 1e-12, "stddev of one sample is zero");
    CHECK(one.median() == 42, "median equals the sample");

    printf("  ok\n");
}

static void test_median() {
    printf("windowed median\n");

    Series odd;
    for (uint32_t v : {5u, 1u, 3u}) odd.add(v);
    CHECK(odd.median() == 3, "odd count takes the middle element");

    Series even;
    for (uint32_t v : {10u, 20u, 30u, 40u}) even.add(v);
    CHECK(even.median() == 25, "even count averages the two middle elements");

    // Constant series: mean, median, min and max must all agree.
    Series flat;
    for (int i = 0; i < 50; i++) flat.add(7);
    CHECK(flat.median() == 7, "constant series median");
    CHECK_NEAR(flat.stddev(), 0.0, 1e-12, "constant series stddev is zero");

    printf("  ok\n");
}

static void test_ring_wrap() {
    printf("median window saturation\n");

    // Overfill the window: the median must reflect only the most recent
    // MEDIAN_WINDOW samples, while count/mean still cover everything.
    Series s;
    for (int i = 0; i < 100; i++) s.add(1);            // old, discarded from window
    for (int i = 0; i < MEDIAN_WINDOW; i++) s.add(500); // fills the window

    CHECK(s.count == (uint32_t) (100 + MEDIAN_WINDOW), "count covers all samples");
    CHECK(s.ring_len == MEDIAN_WINDOW, "window saturates, does not grow");
    CHECK(s.median() == 500, "median reflects only the recent window");
    CHECK(s.min_us == 1, "min still covers all samples");
    CHECK(s.mean < 500.0 && s.mean > 1.0, "mean covers all samples, unlike the median");

    printf("  ok\n");
}

static void test_energy_conversion() {
    printf("energy conversion\n");

    auto energyUj = [](double power_mw, double latency_us) {
        return power_mw * latency_us / 1000.0;
    };

    // Reproduce the reference paper's Table 1 from its own inputs: at 99.5 mW,
    // one 2.5 ms AES-128 operation costs 248.75 uJ. If this fails, our
    // conversion is not the paper's method.
    CHECK_NEAR(energyUj(99.5, 2500.0), 248.75, 1e-9, "paper AES-128 op = 248.75 uJ");
    CHECK_NEAR(energyUj(99.5, 1500.0), 149.25, 1e-9, "paper HMAC = 149.25 uJ");
    CHECK_NEAR(energyUj(99.5, 5000.0), 497.5, 1e-9, "paper Classical (2 AES) = 497.5 uJ");
    CHECK_NEAR(energyUj(99.5, 6500.0), 646.75, 1e-9, "paper Secure Vault = 646.75 uJ");

    // ECC is the one row where the paper's printed figure is rounded:
    // 1105 ms x 99.5 mW = 109,947.5 uJ, which Table 1 prints as 109.95 mJ.
    // The firmware previously hardcoded 109950.0 uJ, i.e. the rounded value
    // read back as if exact. Assert the product, not the rounding.
    CHECK_NEAR(energyUj(99.5, 1105000.0), 109947.5, 1e-6, "paper ECC = 109947.5 uJ exactly");
    CHECK_NEAR(energyUj(99.5, 1105000.0) / 1000.0, 109.95, 5e-3,
               "which Table 1 prints as 109.95 mJ");

    // Ratios are invariant to the power constant -- the load-bearing property
    // of the whole comparison.
    const double lat_sv = 6500.0, lat_cl = 5000.0;
    const double r_paper = energyUj(99.5, lat_sv) / energyUj(99.5, lat_cl);
    const double r_device = energyUj(82.5, lat_sv) / energyUj(82.5, lat_cl);
    CHECK_NEAR(r_paper, r_device, 1e-12, "ratio is identical under both power models");
    CHECK_NEAR(r_paper, 1.3, 1e-9, "paper SV/Classical ratio is 1.3");

    printf("  ok\n");
}

int main() {
    printf("\nmetrics unit tests\n------------------\n");
    test_duration_arithmetic();
    test_welford_known_answer();
    test_single_and_empty();
    test_median();
    test_ring_wrap();
    test_energy_conversion();

    if (failures == 0) {
        printf("\nAll tests passed.\n\n");
        return 0;
    }
    printf("\n%d check(s) FAILED.\n\n", failures);
    return 1;
}
