# `artsoc` local viewer

A localhost-only React + TypeScript reader for simulation sessions. Three pages: a
simulation, the sweep it produced, and one replication in full.

Read `CLAUDE.md`, `docs/framework/measurement.md` and `docs/framework/access-matrix.md`
first. This document covers only what running it needs, what it may and may not show, and
where it departed from `docs/prompts/02-frontend.md`.

## Running it

```
make install-api      # FastAPI + uvicorn, an optional extra
make install-ui       # npm install
make types            # regenerate src/types/artsoc.ts from the pydantic models
make demo             # build the UI and serve it with the API on http://127.0.0.1:8000
```

For development, two processes instead: `make api` (port 8000) and `make ui` (port 5173,
proxying `/api`).

**Every session started from this UI spends money**, and so does every distinct question
asked of the interpretation panel. `configs/base.yaml` names the backend and currently
declares a live one. `make demo-fixture` produces a free mock-backed session to develop and
demo against; it is banner-marked as mock and nothing it produces is a finding.

## The three pages

**A simulation** (`/sessions/:id`) — the scenario, a three-line account of how the society
responded, the headline figures, and whose positions the chosen course of action cited. Two
entry cards lead to the sub-pages.

**Across all runs** (`/sessions/:id/macro`) — diagnostics first, because they gate whether
anything below may be read; then the rung distributions, because the distribution is the
result; then the contrasts, because they are the only interpretable quantity. Then the
course-of-action spread, panel engagement, per-theorist attribution, and a written
interpretation with follow-up questions.

**One run in full** (`/sessions/:id/run/:arm`) — the panel as an interactive graph, any
participant openable for what they were asked and what they answered, the provenance chain
from cited source text to the decision, the activity timeline and the event log. All four
share one playback cursor, pinned to the bottom of the viewport.

Each deliberation is its own step. An edge is revealed once any step it covers has
happened, not at the first — the Advisor consults each persona in turn, and lighting the
whole edge at the first consultation made every one after it invisible to someone stepping
through. The step at the cursor is drawn in ink while the rest recede, and its opening
words are captioned over the edge it travelled or, for a step with no counterpart, over the
participant that took it. The caption is `LoopStep.excerpt` — a truncation of the record's
own words produced in `views.py`, never a paraphrase, which would be a second account of
what was said sitting beside the first.

## What it may and may not do

Several of these are the difference between a defensible result and an undefendable one.

- **It selects among committed configs. It cannot define one.** The request body is a
  `SessionSpec`: a scenario id, arm *names*, `n` and `seed0`. Arm names resolve against
  `configs/arms/`, so no control can construct a configuration no file describes
  (invariants 5 and 11).
- **`escalation_prior` is locked on.** Absolute escalation rates are not findings; only the
  delta against the control is interpretable.
- **Diagnostics render above the figures**, because `docs/framework/measurement.md` treats
  them as gates on interpretation rather than footnotes.
- **Course-of-action support is never called influence.** It records whose opinions the
  Advisor cited when writing the option that was chosen — a property of that document, not
  a measure of what anyone changed. Causal attribution comes from the `loo_*` arms only.
- **A provenance link is drawn only from a recorded id.** Never from lexical overlap: such a
  link would look identical on screen and mean nothing.
- **The representative run is never called the result**, and its arm's distribution stays on
  the same screen.
- **`host_ground_truth` needs the reveal toggle** and is labelled host-only.
- **No prompt reaches the browser.** `RunRecord` carries none (invariant 10). The analytical
  question *is* shown — it is recorded output written by the Advisor, not a prompt.
- **The written interpretation is labelled interpretation.** It is given summary statistics
  and diagnostics only — no transcript, no prompt, no ground truth — and it adds nothing to
  the figures it describes. It cannot touch the rung (invariant 2).

## Design

Editorial rather than dashboard: paper ground, serif display against a clean sans body,
hairline rules, whitespace instead of boxes. Colour is scarce on purpose and each signal
colour has exactly one meaning — the nuclear threshold, the chosen path through a decision,
a declined answer, a warning that gates interpretation. When everything is coloured nothing
reads as a signal, and the diagnostics here are what must never become easy to skip past.

Charts are hand-rolled SVG. They are bar charts over a fixed nine-value scale plus a
four-stage flow; a chart library brings a default idiom that has to be fought and, in the
case of the one previously used here, weighed more than the rest of the application. The
force layout for the panel graph is the only remaining chart dependency (`d3-force`), and it
is layout maths rather than styling — run to a fixed tick count so the same run always draws
the same picture.

## Types are generated

`src/types/artsoc.ts` is produced by `make types` from `RunRecord`, the `views.py` models,
`session.py`, `narrative.py`, the `api.py` response models and — via `TypeAdapter` — the
`metrics` dataclasses. Do not hand-edit it. A hand-maintained copy drifts from the schema the
moment a field moves, and the drift surfaces as a blank panel rather than a compile error.

It is dumped in **serialization** mode, not the default validation mode: computed fields like
`RoutingRecord.selected` and `PresidentialAction.rung` are written into records but are not
inputs, so a validation schema omits them and a client typed from it cannot see a field the
record plainly contains.

## Where this departed from the build spec

Five places, each a case where the codebase did not match what `docs/prompts/02-frontend.md`
assumed — in the same spirit as that document's own Part 0.

**There is now a real provenance chain.** The spec was written before ADR 0006, when
`CourseOfAction.supporting_opinions` did not exist and the middle of this chain could only
have been inferred by matching words. It is now drawn from recorded ids end to end.

**The cost gate quotes calls, not dollars.** Tokens per call vary by an order of magnitude
across roles and are not known before a run, so a pre-run USD total would be the most
quotable invented number on the page. Spend is metered from each record's `est_cost_usd`.

**Call counts are computed per arm.** The spec's flat formula over-counts `escalation_prior`
tenfold: with `consult_panel: false` a replication makes two calls, not twenty.

**The pipeline Sankey and the term cloud were dropped** in the redesign. The Sankey's middle
stage carried no information within an arm, and term frequency over model output was a
weaker version of what the provenance chain now shows properly. `views.pipeline_flow`
remains in Python and tested; nothing renders it.

**Only one scenario ships.** Adding more means adding arm configs per scenario plus a Make
variable, because `tests/test_configs.py` asserts the Makefile and `configs/arms/` cannot
drift. The scenario picker is built for several and currently shows one.

## Layout

```
src/
├── api/client.ts              fetch wrappers and the SSE subscription. No derivations.
├── context/SessionContext.tsx the session store: what is running and what it has cost
├── lib/                       playback cursor, passage lookup, formatting
├── views/                     SessionList · SessionCreate · SessionRunning ·
│                              SimulationLanding · MacroAnalysis · RepresentativeRun
└── components/                charts, tables, notices, and the playback-driven panels
```

Derivations live in `src/artsoc/views.py`, not here. Anything a UI needs computed belongs
where `pytest` can reach it — the representative-run selection rule, the loop-step ordering,
the graph, the provenance chain and the course-of-action support are all tested in Python,
and the browser only draws them.
