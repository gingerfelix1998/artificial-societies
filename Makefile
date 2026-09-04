# Phase 1 runs entirely offline against the mock backend: no API key, no network.
# `make install` needs the network once to populate .venv; everything after that does not.

PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
N ?= 100
SEED0 ?= 1
ARMS := escalation_prior baseline m1_ungrounded small_panel consensus_only synth_only full_stack_variance

.PHONY: install test lint fmt arms phase1 clean

install:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]"

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
