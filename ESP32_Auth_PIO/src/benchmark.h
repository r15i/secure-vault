// On-device batch benchmarking: runs K repetitions of a protocol's
// cryptographic work inside one timed region, so per-operation cost can be
// measured without WiFi latency or clock quantisation in the way.
//
// Placeholder: the route hook exists so main.cpp's wiring is final, but no
// batch endpoint is served yet. Implemented in tasks 8.x.
#pragma once

#include <WebServer.h>

// Registers the batch benchmark and statistics-reset endpoints.
void registerBenchmarkRoutes(WebServer& server);
