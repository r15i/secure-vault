// Device configuration TEMPLATE — committed, contains no secrets.
//
// Setup:
//   cp src/config.example.h src/config.h
//   then edit src/config.h with your real values.
//
// src/config.h is git-ignored and MUST NOT be committed: it holds WiFi
// credentials. This template is the authoritative list of what config.h
// must define — the build fails with a naming error if any field is missing.
//
// Non-secret measurement constants (the two power-model values) do NOT live
// here. They belong in tracked source, since an ignored file would not survive
// a fresh clone.

#pragma once

// --- WiFi credentials (required) ---
#define WIFI_SSID     "your-network-name"
#define WIFI_PASSWORD "your-network-password"

// --- Optional: static IP ---
// Leave undefined to use DHCP, which is how the device currently operates.
// The address it receives is reported over serial at boot and by GET /api/status.
// #define DEVICE_STATIC_IP  "192.168.1.128"
// #define DEVICE_GATEWAY    "192.168.1.1"
// #define DEVICE_SUBNET     "255.255.255.0"
