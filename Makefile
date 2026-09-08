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
UI := frontend
PORT ?= 8000
N ?= 100
SEED0 ?= 1
ARMS := escalation_prior baseline m1_ungrounded small_panel consensus_only synth_only full_stack_variance tag_routing

# Forced-exclusion arms: one per theorist, each running a world in which that theorist
# never existed. Kept out of ARMS because they answer a different question — not "does the
# panel matter" but "which member of it does" — and because their contrast is against each
# other, not against escalation_prior.
LOO_ARMS := $(addprefix loo_,brodie schelling kahn wohlstetter jervis waltz sagan posen \
	tannenwald george freedman blair)

.PHONY: install install-live install-api install-ui test lint fmt arms smoke phase1 \
	attribution types api ui demo demo-fixture clean

install:
	$(PY) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]"
	@# On macOS, iCloud Drive sets UF_HIDDEN on files it manages (anything under a
	@# synced ~/Documents). CPython >= 3.13 silently skips hidden .pth files, which
	@# breaks the editable install with a bare ModuleNotFoundError. Clear the flag on
	@# the .pth only; no-op on any other platform.
	-@chflags nohidden $(VENV)/lib/python*/site-packages/*.pth 2>/dev/null || true

# Adds the provider SDK. Separate from `install` so the default path stays offline and
# the test suite keeps running on a machine with no provider dependency.
install-live:
	$(BIN)/python -m pip install -e ".[dev,live]"

# Adds FastAPI and uvicorn for the local frontend's API. Separate from `install` for the
# same reason `install-live` is: nothing in artsoc imports artsoc.api, so the core package
# and the offline test suite must keep working without a web framework present.
install-api:
	$(BIN)/python -m pip install -e ".[dev,api]"

install-ui:
	cd $(UI) && npm install

test:
	$(BIN)/python -m pytest

lint:
	$(BIN)/python -m ruff check src tests

fmt:
	$(BIN)/python -m ruff format src tests

arms:
	$(BIN)/artsoc arms

# First live run. Ten replications of one arm, to check the wiring before a sweep.
# Whether it costs anything depends on `backend` in configs/base.yaml.
smoke:
	$(BIN)/artsoc run baseline --n 10 --out-dir out/smoke
	$(BIN)/artsoc analyse out/smoke/baseline.jsonl

# Full offline sweep. escalation_prior runs first: it is the baseline every other arm's
# contrast is measured against, and an absolute rate without it means nothing.
phase1:
	@for arm in $(ARMS); do \
		echo "=== $$arm ==="; \
		$(BIN)/artsoc run $$arm --n $(N) --seed0 $(SEED0) || exit 1; \
	done
	$(BIN)/artsoc analyse $(addprefix out/,$(addsuffix .jsonl,$(ARMS)))

# Forced-exclusion sweep. Run `make phase1` first: every surviving theorist call is then
# already cached, so each arm here costs only its own advisor synthesis and presidential
# decision rather than a full re-run.
attribution:
	@for arm in $(LOO_ARMS); do \
		echo "=== $$arm ==="; \
		$(BIN)/artsoc run $$arm --n $(N) --seed0 $(SEED0) || exit 1; \
	done
	$(BIN)/artsoc analyse $(addprefix out/,$(addsuffix .jsonl,$(LOO_ARMS)))

# ---------------------------------------------------------------------------
# Local frontend. Everything below is demoware: it selects among committed arm configs and
# renders what a session produced. It cannot construct an experiment that no file in
# configs/ describes, and it never sees a prompt.
# ---------------------------------------------------------------------------

# TypeScript types are GENERATED from the pydantic models, never hand-written. A
# hand-maintained copy drifts from the schema silently, and the drift surfaces as a blank
# panel rather than an error.
types:
	$(BIN)/python scripts/dump_schema.py $(UI)/schema
	cd $(UI) && npm run gen:types

# The API alone, for frontend development against `npm run dev` on 5173.
api:
	$(BIN)/python -m artsoc.api --port $(PORT)

ui:
	cd $(UI) && npm run dev

# The demo: build the frontend and serve it from the same process as the API, so it is one
# command on one port. Localhost only — this API has no authentication.
demo:
	cd $(UI) && npm run build
	$(BIN)/python -m artsoc.api --port $(PORT) --static $(UI)/dist

# A mock-backed session for developing the UI without spending money. It pins `backend:
# mock` onto a committed arm, which is the one place in the repository a config is built
# outside configs/ — the records say `backend: mock`, the UI banners them as such, and this
# path is not reachable from the API.
demo-fixture:
	$(BIN)/python scripts/demo_fixture.py

clean:
	rm -rf .pytest_cache .ruff_cache .cache
	find src tests -name __pycache__ -type d -exec rm -rf {} +
