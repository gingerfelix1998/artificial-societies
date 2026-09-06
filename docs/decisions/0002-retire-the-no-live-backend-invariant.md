# ADR 0002 — Retire "there is no live backend in phase 1"

Date: 2026-09-06
Status: accepted
Supersedes: the invariant asserted by `test_there_is_no_live_backend_in_phase_one`

## Context

`llm.get_backend` raised `NotImplementedError` for every live backend name, and a test
pinned that:

> No network, no API key, no provider dependency until the loop is pinned down.

The reasoning was sound and is recorded in `llm.py`: build the whole loop and pin its
invariants while responses are free, so nothing is paid for while the architecture is
still moving. `pyproject.toml` lists no model-provider SDK for the same reason.

That condition has now been met. Since the invariant was written:

- The loop runs end to end and `make phase1` sweeps eight arms at n=100.
- 120 tests pass, including `tests/test_access_matrix.py`, which was validated by
  deliberately breaking four context boundaries and confirming each was caught.
- Arms are config files, and the CLI is asserted to expose no experimental flag.
- The rung is deterministic, the action space closed, and records round-trip.

The architecture has stopped moving. Continuing to forbid a live backend now prevents the
only thing the project has not yet done: produce a single number that is not mock output.

## Decision

Retire the invariant. A live Anthropic backend may exist behind the `Backend` protocol,
and `configs/base.yaml` may name real models per role.

**What replaces it is narrower and, for the same purpose, stronger.** The old invariant
protected the offline test guarantee by making a live backend impossible. The new one
protects it directly:

1. `backend: mock` remains the default in `configs/base.yaml`. A live run is opted into.
2. **No test may construct a live backend or make a network call.** `make test` still runs
   on a disconnected machine with no API key, which is the promise that actually mattered.
3. A live backend must fail loudly without credentials rather than degrading to the mock —
   the same rule `retrieval.CorpusRetriever` follows, and for the same reason: a mock run
   written up as a live one is the failure that cannot be detected afterwards.
4. `RunRecord` records which model actually served each role, taken from the backend that
   served it rather than from the config that requested it.

Point 4 is the substantive addition. `RunRecord.backend` was a single string, which was
adequate while one backend served every role and becomes a lie the moment different models
serve different roles. A record that cannot say what produced its numbers is not a record.

## Consequences

`test_there_is_no_live_backend_in_phase_one` is replaced by
`test_the_suite_never_reaches_a_live_backend`, which asserts the offline guarantee as a
property of the suite and the defaults rather than as the absence of code. Per `CLAUDE.md`,
this ADR and that test change land in a commit that does nothing else; the backend itself
follows separately.

`pyproject.toml` gains the `anthropic` SDK. This is a real change of character — the
project stops being runnable with no third-party model dependency — and it is why this is
an ADR rather than a commit message.

Mock output remains deliberately content-nonsense and `MOCK_PREFIX`-marked, so a mock run
and a live run stay distinguishable in the record and in the analysis report. Nothing about
the "absolute rates are not findings" constraint changes: a live run is still subject to
the base-model escalation prior, and only contrasts against `escalation_prior` are
interpretable.

## Alternatives rejected

**Keep the invariant and run live from a fork or a branch.** The provenance fields would
then not exist in the schema the records are written against, so a live run could not be
recorded truthfully — which defeats the purpose of running it.

**Allow a live backend but let it fall back to the mock when no key is present.** This is
the failure mode the project guards against everywhere else. A sweep that silently
produced mock output while reporting a live model would be indistinguishable from a real
result after the fact.
