# `artsoc` local frontend

A localhost-only React + TypeScript viewer for creating simulation sessions, running them,
and inspecting one representative run in detail. Demoware: it shows the instrument working.
It is not a way to configure an experiment.

Built to `docs/prompts/02-frontend.md`. Read that first, then `CLAUDE.md`,
`docs/framework/measurement.md` and `docs/framework/access-matrix.md`. This document covers
only what running it needs and where it departed from the spec.

## Running it

```
make install-api      # FastAPI + uvicorn, an optional extra
make install-ui       # npm install
make types            # regenerate src/types/artsoc.ts from the pydantic models
make demo             # build the UI and serve it with the API on http://127.0.0.1:8000
```

For development, two processes instead: `make api` (port 8000) and `make ui` (port 5173,
proxying `/api`).

**Every session started from this UI spends money.** `configs/base.yaml` names the backend
and currently declares a live one. `make demo-fixture` produces a free mock-backed session
to develop and demo against; it is banner-marked as mock and nothing it produces is a
finding.

## What it may and may not do

The guardrails are not conventions — several of them are the difference between a defensible
result and an undefendable one.

- **It selects among committed configs. It cannot define one.** The request body is a
  `SessionSpec`: a scenario id, arm *names*, `n` and `seed0`. Arm names are resolved against
  `configs/arms/`, so a UI control cannot construct a configuration no file describes
  (invariants 5 and 11).
- **`escalation_prior` is locked on.** Absolute escalation rates are not findings; only the
  delta against the control is interpretable. A session without it is offered nowhere.
- **Provenance and warnings render above the charts**, because `docs/framework/measurement.md`
  treats them as gates on interpretation rather than footnotes.
- **Term frequency is never called theme coding.** There is no theme coder in this project.
- **The representative run is never called the result**, and its arm's distribution stays on
  the same screen.
- **`host_ground_truth` needs the reveal toggle** and is labelled host-only.
- **No prompt reaches the browser.** `RunRecord` carries none, because `call_log` is never
  persisted into it (invariant 10). The analytical question *is* shown — it is recorded
  output written by the Advisor, not the prompt a theorist was sent.
- **A cited passage can be read, and an invented one is marked as invented.**
  `GET /api/passages/{persona}` resolves ids from a record against that persona's own store.
  It is analyst-facing and outside the retrieval path: it never selects, ranks or assembles
  a block, and an id the store does not contain comes back as `unresolved` rather than being
  filled in — that rate is the citation-integrity finding.

## Types are generated

`src/types/artsoc.ts` is produced by `make types` from `RunRecord`, the `views.py` models,
`session.py` and — via `TypeAdapter` — the `metrics` dataclasses. Do not hand-edit it. A
hand-maintained copy drifts from the schema the moment a field moves, and the drift surfaces
as a blank panel rather than a compile error.

It is committed so the UI builds without a Python environment; the JSON Schema it is built
from is an intermediate and is not.

## Where this departed from the build spec

Four places. Each is a case where the codebase did not match what the spec assumed, in the
same spirit as the spec's own Part 0.

**The Sankey's middle stage is the panel's basis mix, not the synthesis mode.**
`synthesis_mode` is set by config, so within one arm it is a single node and the stage would
carry no information. Basis mix — sources-led, belief-led, mostly declined — varies per
replication and is the ADR 0004 diagnostic.

**The cost gate quotes calls, not dollars.** Tokens per call vary by an order of magnitude
across roles and are not known before a run, so a pre-run USD total would be the most
quotable invented number on the page. The gate shows exact call counts per arm per role with
each model's published rate; spend is then metered from each record's `est_cost_usd` as the
session runs, and projected from what has actually billed.

**Call counts are computed per arm.** The spec's flat
`n × arms × (5 + n_questions × (1 + k_per_question))` over-counts `escalation_prior` tenfold:
with `consult_panel: false` a replication makes two calls, not twenty.

**Only one scenario ships.** `data/scenarios/` holds one file, and adding more means adding
arm configs per scenario plus a Make variable, because `tests/test_configs.py` asserts the
Makefile and `configs/arms/` cannot drift. The scenario picker is built for several and
currently shows one.

## Reading the advisory exchange

The run-detail view has two ways in, for two different questions.

**Panel responses** is for reading. One block per analytical question: the question the
Advisor wrote, its stated reason for choosing whom to ask, then each theorist's answer with
position and reasoning separated, and the passages it cited expandable to their full text.

**The event log** is chronological and drives playback, alongside the Gantt and the graph.

Both present the loop as **fan-out and gather, not a conversation.** Each theorist is asked
once and answers once; none can see another's answer. That is invariant 1, and the reason is
in `docs/framework/access-matrix.md` — peer visibility would make apparent consensus a
herding artifact of call ordering. Laying it out as a dialogue would imply deliberation that
did not happen.

A decline is rendered as prominently as a position, because "this falls outside my record"
is the escape hatch working, and it is the answer that separates "X held this" from "a model
impersonating X generated this".

## Playback

Pace is **seconds per step**, not a multiplier: the question is how long you get to read one
step, and a theorist's position plus reasoning is a paragraph. Default 1s, down to 20s.
The controls stick below the topbar, because the panels they drive are taller than a screen
and controls that scroll away leave no way to pause what you are reading.

## Layout

```
src/
├── api/client.ts              fetch wrappers and the SSE subscription. No derivations.
├── context/SessionContext.tsx the session store: what is running and what it has cost
├── lib/                       playback cursor, term frequency, passage lookup, formatting
├── views/                     SessionCreate · SessionList · SessionRunning ·
│                              SessionResults · RunDetail
└── components/                charts, tables, banners, PanelResponses, and the three
                               playback-driven run-detail panels
```

Derivations live in `src/artsoc/views.py`, not here. Anything a UI needs computed belongs
where `pytest` can reach it — the selection rule for the representative run, the loop-step
ordering and the graph construction are all tested in Python, and the browser only draws
them.
