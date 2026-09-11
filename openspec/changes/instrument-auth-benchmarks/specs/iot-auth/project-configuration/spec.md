## Purpose

Establishes that every deployment-specific value — device address, network credentials, serial port, and measurement constants — has exactly one authoritative definition, that secrets never live in tracked files, and that a fresh checkout can build, flash, and benchmark on any machine using the commands the documentation actually lists.

## ADDED Requirements

### Requirement: Secrets are not stored in tracked files

Network credentials and any other secret material SHALL NOT appear in files tracked by version control. The firmware SHALL obtain credentials from a local configuration source that version control ignores, and the repository SHALL provide a committed, secret-free example of that source.

#### Scenario: Tracked files contain no credentials

- **WHEN** the tracked contents of the repository are searched for the WiFi SSID and password
- **THEN** neither value is present in any tracked file

#### Scenario: Fresh checkout has a documented path to a build

- **WHEN** a developer clones the repository and has no local configuration file
- **THEN** a committed example configuration file is present, showing every required field with placeholder values
- **AND** the documentation states how to derive the real configuration from it

#### Scenario: Missing configuration fails clearly

- **WHEN** a build or a benchmark run is attempted with the local configuration absent
- **THEN** it fails with a message naming the missing file and the fields it must contain
- **AND** it does not fall back to a compiled-in or committed default credential

#### Scenario: Prior exposure is disclosed

- **WHEN** credentials are removed from tracked source
- **THEN** the change records that the previously committed values remain in version-control history and must be rotated at the access point
- **AND** does not represent their removal from the working tree as revoking them

### Requirement: Single authoritative definition per configuration value

Each configuration value SHALL have one authoritative definition on each side of the system — one for the firmware, one for the host tooling — and all other references SHALL derive from it rather than restating it. Documentation SHALL point at the authoritative definition instead of duplicating its value.

Values in scope include: device network address, WiFi credentials, serial port, the two power constants, and the default cycle and repetition counts.

#### Scenario: Address is defined once per side

- **WHEN** the device address is changed in the host configuration
- **THEN** every host-side consumer of that address uses the new value with no further edits

#### Scenario: Documentation does not restate values

- **WHEN** the documentation refers to a configuration value
- **THEN** it names where that value is defined rather than reproducing the value itself
- **AND** changing the value does not make the documentation incorrect

#### Scenario: Firmware and host agree on shared constants

- **WHEN** the power constants reported by the device are compared with those recorded by the host in the result dataset
- **THEN** they are identical
- **AND** a mismatch is reported as an error rather than silently reconciled

### Requirement: Build and test interface is portable

The build, flash, monitor, and benchmark commands SHALL work from a fresh checkout on any machine and at any checkout path, without editing tracked files. Tool locations and device connection details SHALL be overridable, with defaults that work in the documented setup.

#### Scenario: No absolute developer-specific paths

- **WHEN** the build configuration is inspected
- **THEN** it contains no absolute path tied to one user's home directory or checkout location

#### Scenario: Overridable without editing tracked files

- **WHEN** an operator needs a different serial port or toolchain location
- **THEN** they can supply it at invocation time or through local configuration
- **AND** no tracked file requires modification

#### Scenario: Declared dependencies

- **WHEN** a developer sets up the host tooling from a fresh checkout
- **THEN** every Python package the tooling imports is listed in a dependency manifest in the repository
- **AND** installing from that manifest is sufficient to run the benchmark

### Requirement: Documented commands exist and work

Every command the project's documentation instructs a reader or agent to run SHALL exist and SHALL perform what the documentation claims. Documentation and the real interface MUST NOT drift.

#### Scenario: Documented targets are present

- **WHEN** each command listed in the project guidelines and architecture documentation is looked up in the build interface
- **THEN** a corresponding target exists

#### Scenario: Renamed or removed commands

- **WHEN** a command is renamed or removed
- **THEN** the documentation is updated in the same change
- **AND** no documentation continues to reference the old name

### Requirement: Generated and derived artifacts are not tracked

Build output, virtual environments, caches, and generated benchmark results SHALL be excluded from version control. Generated results SHALL be written under a dedicated directory rather than alongside source.

#### Scenario: Build output is ignored and untracked

- **WHEN** a firmware build is run and version-control status is checked
- **THEN** no build output file appears as tracked, modified, or untracked-and-unignored

#### Scenario: Results are separated from source

- **WHEN** a benchmark run writes its dataset and charts
- **THEN** they are written under the dedicated results directory
- **AND** that directory is excluded from version control

#### Scenario: Environments are ignored

- **WHEN** version-control status is checked with virtual environments present in the project
- **THEN** they do not appear as untracked-and-unignored entries

### Requirement: Documentation is internally consistent

The project's documentation SHALL NOT contain recommendations that contradict decisions the project has recorded. Superseded guidance SHALL be marked as superseded or removed, not left standing alongside the decision that replaced it.

#### Scenario: Superseded measurement guidance is reconciled

- **WHEN** the documentation is read end to end
- **THEN** no document recommends an approach that another document records as rejected
- **AND** superseded guidance either states what superseded it or is removed

#### Scenario: One owner per fact

- **WHEN** a device, endpoint, or command fact appears in more than one document
- **THEN** one document owns it and the others reference that owner
