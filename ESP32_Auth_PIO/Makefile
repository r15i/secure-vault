# ESP32 Auth benchmarking — build, flash, and test interface.
#
# Every value here is overridable on the command line, e.g.
#   make upload PORT=/dev/ttyUSB0
#   make test   PYTHON=.venv/bin/python
# Nothing in this file is tied to one machine or checkout path.

# Locate PlatformIO: prefer the local toolchain venv if present, else PATH.
# Resolved relative to this Makefile, so the checkout can live anywhere.
MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
LOCAL_PIO    := $(MAKEFILE_DIR)../.venv_pio/bin/pio
PIO          ?= $(if $(wildcard $(LOCAL_PIO)),$(LOCAL_PIO),pio)

# Host interpreter. Defaults to the project venv when it exists, so `make test`
# works with no arguments after `make venv`; override with PYTHON=... .
LOCAL_PY := $(MAKEFILE_DIR)../.venv/bin/python
PYTHON   ?= $(if $(wildcard $(LOCAL_PY)),$(LOCAL_PY),python3)
UV       ?= uv
PORT   ?= /dev/ttyACM1
CLIENT  = test_client.py

# Device address. Overrides the host config default; also settable via
# the ESP32_IP environment variable.
DEVICE_IP ?=
IP_ARG     = $(if $(DEVICE_IP),--ip $(DEVICE_IP),)

CXX ?= g++

# generate_report.py runs from the project root, so a relative PYTHON (such as
# ../.venv/bin/python) would resolve against the wrong directory after `cd ..`.
ABS_PYTHON := $(if $(findstring /,$(PYTHON)),$(abspath $(PYTHON)),$(PYTHON))

.PHONY: all build upload test monitor help clean test-native benchmark analyze \
        test-sv-long test-cl-long test-ecc-long test-batch test-all-batch \
        plot report mock smoke-test clean-results benchmark-paper-time venv

all: build

help:
	@echo "Setup:"
	@echo "  make venv               - Create the host venv and install deps (uv)"
	@echo ""
	@echo "Build & flash:"
	@echo "  make build              - Build the firmware"
	@echo "  make upload             - Build and upload to the device"
	@echo "  make monitor            - Open the serial monitor (115200 baud)"
	@echo "  make clean              - Remove build output"
	@echo ""
	@echo "Benchmark:"
	@echo "  make benchmark          - Full benchmark run -> results/<run-id>/"
	@echo "  make benchmark-paper-time - Run batches matching the time of 1 paper operation"
	@echo "  make analyze CSV=<path> - Render charts + report from a dataset"
	@echo "  make plot               - Automatically find and plot the latest benchmark results"
	@echo "  make report             - Render the final report to .docx and .pdf"
	@echo "  make clean-results      - Delete generated datasets and report artefacts"
	@echo "  make mock               - Run the mock device (no hardware; synthetic timings)"
	@echo "  make smoke-test         - Exercise the whole pipeline against the mock (SYNTHETIC)"
	@echo ""
	@echo "Tests:"
	@echo "  make test-native        - Unit-test the measurement arithmetic (no device needed)"
	@echo "  make test               - Single authentication cycle per protocol"
	@echo "  make test-sv-long       - Continuous Secure Vault cycles"
	@echo "  make test-cl-long       - Continuous Classical cycles"
	@echo "  make test-ecc-long      - Continuous ECC cycles"
	@echo "  make test-batch         - 500 Secure Vault cycles"
	@echo "  make test-all-batch     - 5 cycles of each protocol"
	@echo ""
	@echo "Overrides (current values):"
	@echo "  PIO=$(PIO)"
	@echo "  PYTHON=$(PYTHON)"
	@echo "  PORT=$(PORT)"
	@echo "  DEVICE_IP=$(if $(DEVICE_IP),$(DEVICE_IP),<host config default>)"

# Create the host venv and install the harness dependencies. Uses uv, which
# resolves and installs an order of magnitude faster than pip and is already the
# toolchain used by the sibling project; falls back to stdlib venv + pip if uv
# is not on PATH.
venv:
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "uv venv $(MAKEFILE_DIR)../.venv"; \
		$(UV) venv $(MAKEFILE_DIR)../.venv; \
		VIRTUAL_ENV=$(MAKEFILE_DIR)../.venv $(UV) pip install -r requirements.txt; \
	else \
		echo "uv not found, falling back to python3 -m venv + pip"; \
		python3 -m venv $(MAKEFILE_DIR)../.venv; \
		$(MAKEFILE_DIR)../.venv/bin/pip install -q -r requirements.txt; \
	fi
	@echo "Host venv ready. 'make test' and 'make benchmark' will use it."

build:
	$(PIO) run

upload:
	$(PIO) run --target upload --upload-port $(PORT)

clean:
	$(PIO) run --target clean

monitor:
	$(PIO) device monitor --port $(PORT)

# Full benchmark: resets statistics, drives every protocol, writes a dataset,
# then renders the charts and the deviation report.
benchmark:
	$(PYTHON) benchmark.py $(IP_ARG) $(BENCH_ARGS)

# Run benchmark configured to execute for roughly the same absolute time as
# ONE operation on the paper's Arduino (AES ~5ms, SV ~6.5ms, ECC ~1s).
# Because the ESP32 is much faster, this means K=100 for symmetric, K=3 for ECC!
benchmark-paper-time:
	@echo "Running batches that take the same wall-clock time as ONE paper operation..."
	$(PYTHON) benchmark.py $(IP_ARG) --k 100 --ecc-k 3 $(BENCH_ARGS)

# Clear generated datasets and report artefacts. results/README.md documents the
# layout and is tracked, so it survives.
clean-results:
	find ../results -mindepth 1 -maxdepth 1 ! -name README.md -exec rm -rf {} +
	rm -f test_log.csv
	rm -f ../paper/Final_Report.docx ../paper/Final_Report.pdf ../paper/Final_Report.tex \
	      ../paper/Final_Report.aux ../paper/Final_Report.log ../paper/Final_Report.out

# End-to-end smoke test of the harness against the mock device. This proves the
# pipeline runs; it measures NOTHING. The mock reports synthetic timings and
# declares itself, so the dataset is stamped device_kind=mock and the report
# carries a warning. Never use its output as a result.
smoke-test:
	@echo "Starting mock device (synthetic timings, not measurements)..."
	@$(PYTHON) mock_device.py > /dev/null 2>&1 & echo $$! > mock.pid
	@sleep 2
	@$(MAKE) clean-results PYTHON=$(PYTHON)
	@$(PYTHON) benchmark.py --k 200 --ecc-k 5 --cycles 10 || true
	@$(MAKE) plot PYTHON=$(PYTHON) || true
	@cd .. && $(ABS_PYTHON) generate_report.py --allow-mock || true
	@echo "Stopping mock device..."
	@kill `cat mock.pid` 2>/dev/null || true
	@rm -f mock.pid
	@echo ""
	@echo "Smoke test done. Everything it produced is SYNTHETIC - run 'make benchmark'"
	@echo "against the board for figures that can be reported."

# Re-render from an existing dataset. No device needed.
analyze:
	@test -n "$(CSV)" || (echo "Usage: make analyze CSV=results/<run-id>/benchmark.csv" && false)
	$(PYTHON) analyze.py $(CSV)

# Automatically find the latest dataset and plot it
plot:
	$(eval LATEST_CSV := $(shell ls -t ../results/*/benchmark.csv 2>/dev/null | head -n 1))
	@if [ -z "$(LATEST_CSV)" ]; then echo "No benchmark.csv found in ../results. Run 'make benchmark' first."; exit 1; fi
	@echo "Analyzing latest dataset: $(LATEST_CSV)"
	$(PYTHON) analyze.py $(LATEST_CSV)

# Render the final report. Both formats come from report_content.py, which reads
# its numbers out of the newest dataset -- so `plot` runs first to make sure the
# charts it embeds match that dataset.
report: plot
	cd .. && $(ABS_PYTHON) generate_report.py

# Run the python mock server
mock:
	$(PYTHON) mock_device.py

# Measurement arithmetic tests. Pure logic, so they run on the host: a timer or
# statistics bug cannot hide behind a hardware-only test cycle.
test-native:
	@mkdir -p .native
	$(CXX) -std=c++17 -O2 -Wall -o .native/test_metrics test/test_metrics.cpp
	@./.native/test_metrics

test:
	$(PYTHON) $(CLIENT) $(IP_ARG)

# Build the archive that accompanies the report, and refuse to produce one that
# carries WiFi credentials. src/config.h is git-ignored but sits in the working
# tree, so a naive zip of the tree would ship a live password; the compiled
# artefacts under .pio have it baked in for the same reason. Both are excluded
# and the result is then searched for the literal values as a backstop.
submission:
	@$(PYTHON) make_submission.py

# Rejection tests: replayed, forged, tampered and out-of-order requests against
# every protocol, each of which the device must refuse. Writes security.json
# beside the newest dataset so the report can cite it.
test-security:
	$(PYTHON) security_tests.py $(IP_ARG)

test-sv-long:
	$(PYTHON) $(CLIENT) $(IP_ARG) --mode long --method sv --delay 0.01

test-cl-long:
	$(PYTHON) $(CLIENT) $(IP_ARG) --mode long --method classical --delay 0.01

test-ecc-long:
	$(PYTHON) $(CLIENT) $(IP_ARG) --mode long --method ecc --delay 0.01

test-batch:
	$(PYTHON) $(CLIENT) $(IP_ARG) --mode long --method sv --iterations 500

test-all-batch:
	@echo "Starting batch test for all protocols (5 iterations each)..."
	$(PYTHON) $(CLIENT) $(IP_ARG) --mode long --method classical --iterations 5 --delay 0.1
	$(PYTHON) $(CLIENT) $(IP_ARG) --mode long --method sv --iterations 5 --delay 0.1
	$(PYTHON) $(CLIENT) $(IP_ARG) --mode long --method ecc --iterations 5 --delay 0.1
	@echo "Done. Per-cycle log in test_log.csv"
