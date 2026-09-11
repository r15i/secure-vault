# Archive

Superseded artifacts, kept for provenance rather than use.

- `test_log.superseded.csv` — the old test client's log: timestamp, method, status.
  It carries **no timing data**, because the firmware did not measure anything when
  it was written; the energy figures of that era were the reference paper's
  constants multiplied by a cycle count. Superseded by the run-scoped datasets under
  `results/<run-id>/benchmark.csv`, which record measured latency and derive energy
  from it. See `docs/Performance Analysis.md` → Historical note.
