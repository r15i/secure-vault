// IoT authentication benchmarking on the ESP32-C3.
//
// Compares three authentication protocols — Secure Vault, Classical AES-128,
// and ECC — against the reference paper (Gupta & Kumaraguru, TrustCom 2018).
//
// This file owns only startup and wiring. Each protocol, the measurement
// machinery, the batch benchmark, and the telemetry surface live in their own
// translation units.

#include <WebServer.h>
#include <WiFi.h>

// Credentials come from src/config.h, which is git-ignored. There is no
// compiled-in fallback: a missing or incomplete config fails the build.
#if __has_include("config.h")
  #include "config.h"
#else
  #error "Missing ESP32_Auth_PIO/src/config.h — copy src/config.example.h to src/config.h and set WIFI_SSID and WIFI_PASSWORD."
#endif

#if !defined(WIFI_SSID) || !defined(WIFI_PASSWORD)
  #error "ESP32_Auth_PIO/src/config.h must define both WIFI_SSID and WIFI_PASSWORD — see src/config.example.h for the required fields."
#endif

#include "auth_classical.h"
#include "auth_ecc.h"
#include "auth_srp.h"
#include "auth_sv.h"
#include "benchmark.h"
#include "metrics.h"
#include "telemetry.h"

static WebServer server(80);

void setup() {
    Serial.begin(115200);
    delay(1000);

    initSecureVault();
    initSRP();

    if (!initECC()) {
        Serial.println("WARNING: ECC key material failed to load; ECC endpoints will error.");
    }

    // Characterise the cost of an empty instrumented region: the floor below
    // which no measured phase can be trusted.
    measureInstrumentationOverhead();
    Serial.printf("Instrumentation overhead: mean %.2f us over %u samples\n",
                  series[S_OVERHEAD].mean, series[S_OVERHEAD].count);

    WiFi.mode(WIFI_STA);
    // Explicitly reset config to ensure DHCP is used
    WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE, INADDR_NONE);
    
    Serial.printf("Connecting to WiFi SSID: %s\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    
    int wifi_attempts = 0;
    while (WiFi.status() != WL_CONNECTED) {
        delay(1000);
        wifi_attempts++;
        Serial.printf("WiFi status: %d (attempts: %d)\n", WiFi.status(), wifi_attempts);
        
        // Re-trigger every 15 seconds if stuck
        if (wifi_attempts % 15 == 0) {
            Serial.println("Connection taking too long. Restarting WiFi...");
            WiFi.disconnect();
            delay(500);
            WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        }
    }
    Serial.print("WiFi connected. Device address (DHCP): ");
    Serial.println(WiFi.localIP());

    registerTelemetryRoutes(server);
    registerSVRoutes(server);
    registerClassicalRoutes(server);
    registerSRPRoutes(server);
    registerECCRoutes(server);
    registerBenchmarkRoutes(server);

    server.begin();
    Serial.println("HTTP server started.");
}

void loop() {
    server.handleClient();
}
