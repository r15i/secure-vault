## Context

See `proposal.md` for motivation. The `Makefile` currently contains the `benchmark` and `clean-results` targets independently. 

## Goals / Non-Goals

**Goals:**
- Automatically wipe out `results/` before starting a new benchmark, ensuring only the freshest results are preserved.

**Non-Goals:**
- Archiving old results.

## Decisions

- **Decision 1**: Add `clean-results` as a dependency for the `benchmark` target. This is a one-line change in `ESP32_Auth_PIO/Makefile`.

## Risks / Trade-offs

- [Risk] Unintended data loss of older benchmark runs → Users must be aware that running `make benchmark` is destructive to old test data.
