## Why

The user wants to demonstrate visually the difference in power usage among the implemented algorithms (Classical AES-128, Secure Vault, and ECC). Adding a visual power consumption demo to the existing web interface (`dashboard.h`) will provide a direct and intuitive way to compare the efficiency of each algorithm in real time.

## What Changes

- Update `dashboard.h` HTML/JS to render a visual chart or comparison bars for power consumption.
- Hook the new UI into the existing `/api/energy` JSON telemetry to display real-time energy usage per algorithm.

## Capabilities

### New Capabilities
- `dashboard/power-demo`: Adds a visual comparison demo of power consumption for the different cryptographic protocols on the web dashboard.

### Modified Capabilities
None.

## Impact

- `ESP32_Auth_PIO/src/dashboard.h` will be modified to include the new UI components and JavaScript rendering logic.
- Users accessing the ESP32's IP will see a clear visual representation of power usage differences.
