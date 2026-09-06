# Phase 1 runs entirely offline against the mock backend: no API key, no network.
# `make install` needs the network once to populate .venv; everything after that does not.

PY ?= python3
# The .nosync suffix is not decoration. macOS iCloud Drive syncs ~/Documents, and a venv
# inside a synced folder gets evicted to the cloud: CPython then skips the editable
# install's .pth file (which iCloud flags hidden) and later times out reading library
# files it has to re-download — which would also break the promise that the test suite
# runs on a disconnected machine. iCloud leaves anything ending in .nosync alone.
# Elsewhere the suffix is just part of a directory name and costs nothing.
VENV ?= .venv.nosync
BIN := $(VENV)/bin
N ?= 100
SEED0 ?= 1
ARMS := escalation_prior baseline m1_ungrounded small_panel consensus_only synth_only full_stack_variance

.PHONY: install test lint fmt arms phase1 clean

install:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]"
	@# On macOS, iCloud Drive sets UF_HIDDEN on files it manages (anything under a
	@# synced ~/Documents). CPython >= 3.13 silently skips hidden .pth files, which
	@# breaks the editable install with a bare ModuleNotFoundError. Clear the flag on
	@# the .pth only; no-op on any other platform.
	-@chflags nohidden $(VENV)/lib/python*/site-packages/*.pth 2>/dev/null || true

test:
	$(BIN)/python -m pytest

lint:
	$(BIN)/python -m ruff check src tests

fmt:
	$(BIN)/python -m ruff format src tests

arms:
	$(BIN)/artsoc arms

# Full offline sweep. escalation_prior runs first: it is the baseline every other arm's
# contrast is measured against, and an absolute rate without it means nothing.
phase1:
	@for arm in $(ARMS); do \
		echo "=== $$arm ==="; \
		$(BIN)/artsoc run $$arm --n $(N) --seed0 $(SEED0) || exit 1; \
	done
	$(BIN)/artsoc analyse $(addprefix out/,$(addsuffix .jsonl,$(ARMS)))

clean:
	rm -rf .pytest_cache .ruff_cache .cache
	find src tests -name __pycache__ -type d -exec rm -rf {} +
