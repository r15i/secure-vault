## Purpose

Provides a genuine asymmetric authentication exchange on the device — ECDSA over the NIST P-256 curve — so that the expensive public-key baseline the Secure Vault protocol is compared against is actually executed and measured on the constrained hardware, rather than asserted by a stub that returns success without computing anything.

## ADDED Requirements

### Requirement: Real asymmetric cryptography per cycle

Each ECC authentication cycle SHALL perform real elliptic-curve cryptographic work on the device. The device MUST NOT report an ECC cycle as successful unless the cryptographic operations for that cycle were executed on the device.

The curve SHALL be NIST P-256 (secp256r1) with SHA-256 as the digest, so the operation cost is representative of the ECC schemes the reference paper compares against.

#### Scenario: ECC cycle performs cryptographic work

- **WHEN** an ECC authentication cycle completes successfully
- **THEN** the device reports a non-zero measured duration for signature generation
- **AND** that duration is at least an order of magnitude greater than the device's measured AES-128 block operation duration

#### Scenario: Stub behaviour is rejected

- **WHEN** an ECC verify request is served
- **THEN** the response is derived from the outcome of the cryptographic operations performed for that request
- **AND** success is not returned on the basis of session state alone

### Requirement: Two-operation exchange structure

To keep the asymmetric baseline structurally comparable to the symmetric protocols — each of which performs two cryptographic primitives per cycle — an ECC cycle SHALL perform, on the device, one signature generation and one signature verification, and SHALL report their durations separately.

#### Scenario: Both operations are measured separately

- **WHEN** an ECC authentication cycle completes
- **THEN** the device reports a distinct duration for the signature generation
- **AND** a distinct duration for the signature verification
- **AND** the reported ECC crypto time is the sum of the instrumented ECC phases

### Requirement: Mutual challenge-response authentication

The ECC exchange SHALL authenticate the device to the peer and the peer to the device, using fresh random challenges each cycle so that no cycle can be satisfied by replay.

The exchange SHALL proceed as: the device issues a random challenge and receives one; the device signs the peer's challenge with its private key; the device verifies the peer's signature over the device's challenge; authentication succeeds only if verification succeeds and the peer independently verifies the device's signature.

#### Scenario: Valid mutual exchange succeeds

- **WHEN** both parties sign the counterparty's challenge correctly
- **THEN** the device reports the cycle as authenticated
- **AND** the peer's verification of the device's signature also succeeds

#### Scenario: Invalid peer signature is rejected

- **WHEN** the peer submits a signature that does not verify against its public key over the device's challenge
- **THEN** the device rejects the cycle with an authentication failure
- **AND** the cycle is not counted as a successful ECC cycle

#### Scenario: Replayed challenge is rejected

- **WHEN** a signature from a previous cycle is submitted against the current challenge
- **THEN** the device rejects the cycle
- **AND** the failure is distinguishable from a transport or parsing error

#### Scenario: Challenge freshness

- **WHEN** two consecutive ECC cycles are initiated
- **THEN** the challenges issued by the device differ

### Requirement: Key material availability

The device SHALL possess a P-256 key pair and the peer's public key at the time of an authentication cycle, and per-cycle key generation SHALL NOT be included in the measured authentication cost unless it is reported as its own separately labelled phase.

#### Scenario: Keys are ready before measurement

- **WHEN** the first ECC cycle after boot is executed
- **THEN** the reported per-cycle ECC cost excludes any one-time key setup performed at boot
- **AND** any one-time key setup cost, if reported, is labelled as a distinct setup phase rather than folded into per-cycle cost

#### Scenario: Missing key material

- **WHEN** an ECC cycle is requested and the required key material is unavailable
- **THEN** the device returns an error identifying the cause
- **AND** does not report a successful cycle or accumulate energy for it

### Requirement: Error reporting is distinguishable

Failure modes of the ECC exchange SHALL be distinguishable from one another in the device's responses, so that a benchmark run cannot silently record cryptographic failures as transport noise.

#### Scenario: Failure causes are distinct

- **WHEN** a cycle fails because of a malformed request, an uninitialised session, or a failed signature verification
- **THEN** the device's response distinguishes which of these occurred
