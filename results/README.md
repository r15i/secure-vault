# Benchmark datasets

One directory per run, named by its UTC run id (`YYYYMMDDTHHMMSSZ`). Contents are
generated and are not tracked in git — regenerate them rather than committing them:

```bash
make benchmark            # writes results/<run-id>/, needs the device
make plot                 # re-renders charts + report.md from the newest dataset
```

## Provenance

`run.json` carries `device_kind`: `device` for a real ESP32-C3, `mock` for a run
driven against `mock_device.py`. A mock run's timings are synthetic and are **not
measurements** — `analyze.py` stamps a warning across the report and
`generate_report.py` refuses to build a submission from one unless `--allow-mock`
is passed. Only a `device_kind: device` dataset may be reported.
