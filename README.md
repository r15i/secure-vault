# Secure Vault authentication on the ESP32-C3

Course project for Cyber-Physical Systems and IoT Security. Implements the Secure Vault
mutual-authentication protocol of **Gupta & Kumaraguru (TrustCom 2018)** on an
**ESP32-C3 SuperMini** (~EUR 4), and measures its cost against the three baselines the
paper compares it with: a classical pre-shared-key AES-128 challenge-response, the single
rotating password of its Figure 3, and ECDSA over P-256.

The question under test is the paper's efficiency claim — that Secure Vault buys key
rotation and replay resistance for a small constant-factor premium over plain symmetric
authentication, while asymmetric authentication costs orders of magnitude more.

## Reproducibility and Code Access

Every number and chart in the accompanying report is regenerated directly from the measured dataset by the commands below; nothing is typed into the text by hand.

### Instructions

```bash
# Clone the repository
git clone https://github.com/r15i/secure-vault.git
cd secure-vault/ESP32_Auth_PIO

# Configure WiFi credentials
cp src/config.example.h src/config.h   # set WIFI_SSID and WIFI_PASSWORD

# Set up environment and flash device
make venv                              # uv venv + install host deps
make upload PORT=/dev/ttyACM0          # flash; monitor prints the IP

# Run tests and collect data
make benchmark DEVICE_IP=<ip>          # -> results/<run-id>/
make test-security DEVICE_IP=<ip>      # -> results/<run-id>/security.json
```

Without hardware, you can test the harness using the native test suite and a mock device:
```bash
make test-native      # unit-tests the measurement arithmetic
make smoke-test       # whole pipeline against the mock — SYNTHETIC, not results
```

## Repository Structure

- `ESP32_Auth_PIO/` - Firmware (C++) and host harness (Python).
- `ESP32_Auth_PIO/src/` - Firmware implementation: auth protocols, metrics, telemetry.
- `ESP32_Auth_PIO/test_client.py` - Real protocol peer; mirrors vault and verifies replies.
- `ESP32_Auth_PIO/benchmark.py` - Drives a run, cross-checks both paths, writes dataset.
- `results/` - The generated datasets (JSON/CSV) from benchmark runs.
- `docs/` - Architecture, measurement strategy, and how to read results.
