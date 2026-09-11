// Telemetry and the dashboard route: everything the host reads to learn what
// the device measured.
#pragma once

#include <WebServer.h>

// Registers GET /, GET /api/status, and GET /api/energy.
void registerTelemetryRoutes(WebServer& server);
