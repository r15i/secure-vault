## Why

The user requested that whenever the benchmark batch is run again, the previous results are automatically deleted. This ensures that old data doesn't clutter the results directory and that users are always looking at the freshest benchmark output. The most natural way to achieve this is to make the `benchmark` Makefile target depend on `clean-results`.

## What Changes

- Modify the `Makefile` so that the `benchmark` target has `clean-results` as a prerequisite.
- No requirements or specs are altered (purely a tooling/developer experience improvement).

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None.

## Impact

- `ESP32_Auth_PIO/Makefile` will be updated.
- Running `make benchmark` will now silently clear out `results/` before starting a new run.
