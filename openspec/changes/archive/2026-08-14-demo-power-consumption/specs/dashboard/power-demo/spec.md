## Purpose

Visualizes the real-time power consumption of each cryptographic algorithm directly on the dashboard, making efficiency comparisons intuitive for end users.

## ADDED Requirements

### Requirement: Power Consumption Visual Demo
The system SHALL display a visual comparison (e.g. chart or progress bars) showing the relative energy consumption of Secure Vault, Classical AES-128, and ECC on the dashboard.

#### Scenario: Displaying energy consumption
- **WHEN** the dashboard loads or refreshes its statistics from `/api/energy`
- **THEN** it renders a visual power usage component demonstrating how much energy each algorithm consumes based on the latest metrics.
