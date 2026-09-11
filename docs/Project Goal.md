# Project Goal: IoT Authentication with Secure Vaults

## Overview
This project implements and compares three authentication mechanisms for the ESP32-C3 SuperMini:
1.  **Secure Vault (SV):** Based on the research paper. Uses multi-key XOR and dynamic HMAC-SHA256 vault updates.
2.  **Classical (AES):** Standard symmetric AES-128 challenge-response.
3.  **ECC (Asymmetric):** ECDSA-based authentication (high overhead benchmark).

The main goal is to evaluate the trade-offs between symmetric algorithms (Classical and Secure Vault) vs. asymmetric algorithms (ECC) in a resource-constrained IoT environment, focusing particularly on security guarantees and energy overhead. Secure Vault is analyzed as a middle ground: offering the symmetric efficiency with resistance to side-channel and dictionary attacks via dynamic keys.
