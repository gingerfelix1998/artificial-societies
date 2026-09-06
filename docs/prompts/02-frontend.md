# Build spec — `artsoc` local frontend

A localhost-only React + TypeScript UI for creating simulation sessions, running them, and
inspecting a single representative run in detail.

Read `CLAUDE.md`, `docs/design.md`, `docs/access-matrix.md` and `docs/measurement.md` before
starting. This spec assumes the invariants in those documents hold and adds none of its own
exceptions.

---

## Part 0 — Architecture assumptions, re-checked

Five things in the original request do not match what the codebase produces. Read this
section before anything else; building to the request as stated would produce a UI that
displays quantities the simulation does not compute.

### 0.1 There is no escalation *path* in phase 1

**Assumed:** a chart showing "paths to escalation rungs".

**Actual:** `run_once` produces exactly one `PresidentialAction` per replication. The
`RunRecord` has a single terminal `rung: int`. There is no sequence of rungs, because phase 1
is explicitly a one-event, single-decision closed loop (`docs/design.md`, Roadmap).
Multi-step escalation arrives in phase 2, when Presidents signal to each other.

**Build instead:** two charts.

1. **Rung distribution histogram** — counts per rung 0–8 across the sweep. This is the
   primary result and must lead, per `docs/measurement.md`.
2. **Loop-stage Sankey** — flow through the pipeline for a single arm:
   `intel confidence band → advisor synthesis mode → terminal rung`, with band widths as
   replication counts. This gives the "paths" affordance honestly: it shows what varied
   upstream of each terminal rung, without implying a temporal escalation ladder that was
   never simulated.

Do not label anything "escalation path" or "escalation trajectory". Label the Sankey
"Pipeline flow to terminal rung".

### 0.2 Theme coding does not exist

**Assumed:** "wordclouds of key themes/ideas raised".

**Actual:** there is no theme coder in the repo. `docs/measurement.md` lists secondary
reasoning-theme coding as **not implemented**, and states that when it exists it needs
inter-coder agreement against a hand-coded sample before any theme count appears in a claim.

**Build instead:** a client-side **term-frequency cloud**, computed in the browser from text
already in the record — `TheoristOpinion.position`, `TheoristOpinion.reasoning`,
`AdvisorBrief.consensus_points`, `AdvisorBrief.minority_positions`,
`PresidentialAction.justification`. Stopword-filtered, lowercased, no stemming.

It must carry a visible label: **"Term frequency, not validated theme coding."** This is not
optional politeness — mislabelling raw term counts as themes is exactly the overclaim
`docs/measurement.md` exists to prevent.

Offer a source toggle (theorist text / advisor brief / presidential justification) because a
cloud mixing all three is uninterpretable.

### 0.3 Influence attribution is cross-arm, not within-arm

**Assumed:** "stats on which theorists engaged and how that affected the output", from one
simulation.

**Actual:** a single arm cannot answer this. `docs/measurement.md` is explicit that the
observational approach — comparing runs where a persona happened to be routed in against runs
where it was not — is confounded, because routing correlates with question tags which
correlate with outcome. Causal attribution comes from the fifteen `loo_*` **forced-exclusion
arms**, which are separate runs.

**Build instead:** split the claim into two clearly-labelled panels.

- **Engagement** (within-arm, always available): consultation counts per persona, out-of-record
  decline rate per persona, mean stated `confidence`, times topped-up versus chosen, and
  hallucinated-id counts. All descriptive, no causal language.
- **Influence** (cross-arm, only when exclusion arms were run): mean-rung delta for
  `loo_<persona>` against `baseline`. Greyed out with an explanatory note when those arms are
  absent from the session.

A session must therefore be able to run **multiple arms**. See 1.2.

### 0.4 There is no per-call timing for a wall-clock Gantt

**Assumed:** a Gantt chart of agent engagement over the simulation.

**Actual:** `llm.CallRecord` has `role`, `system`, `prompt`, `response`, `cached`, `model` —
no timestamp and no duration. `call_log` is not persisted into `RunRecord` at all; only
`llm_calls` and `cache_hits` counts survive. The only timing anywhere is run-level
`started_at` and `wall_time_s`.

**Build instead:** a Gantt over **logical loop steps**, not wall-clock. This is better, not a
compromise: step indices are deterministic, reproducible from config plus seed, and free of
API latency noise that means nothing about the simulation.

Derive the step sequence client-side from record structure (exact algorithm in 4.2). Label the
x-axis "Loop step", never "Time".

Do **not** add per-call timing to the backend for this. It would mean persisting `call_log`,
which contains full system and user prompts for every role — those prompts are precisely what
the access-matrix tests scan, and shipping them to a browser creates a second, untested
surface where context can cross a boundary. If wall-clock profiling is wanted later it belongs
in a separate profiling path, not in `RunRecord`.

### 0.5 Only one scenario exists, and scenario is not a CLI flag

**Assumed:** the user picks from three scenarios.

**Actual:** `data/scenarios/` contains only `phase1_tel_dispersal_v1.json`. `scenario_id` is a
`RunConfig` field set in `configs/base.yaml`; `artsoc run` exposes only `--n`, `--seed0`,
`--out-dir`, `--append`, because `CLAUDE.md` invariant 5 restricts CLI flags to operational
parameters and scenario choice is experimental.

**Build instead:** two new scenario files plus one arm config per scenario, so the UI selects
among **committed configs** and the invariant is preserved exactly. See 1.1.

---

## Part 1 — Backend work required first

The frontend cannot be built against the current backend. Do this first, in order, keeping
`make test` green at each step.

### 1.1 Two additional scenarios and their arms

Add `data/scenarios/phase1_early_warning_v1.json` and
`data/scenarios/phase1_exercise_ambiguity_v1.json`, following the existing file exactly:
`scenario_id`, `schema_version`, `_notes`, `self_nation`, `adversary_nation`, `now`,
`doctrine_card`, `perception`, `events`.

Design constraints, from the existing scenario's `_notes`:

- **Nations stay anonymised** as Nation A / Nation B. A named dyad lets a model retrieve how
  the real episode ended.
- **The event must be genuinely ambiguous.** Its `observable_signature` should be consistent
  with at least two readings. An unambiguous event is decided by the intelligence brief alone
  and the panel stops mattering.
- **`ground_truth_detail` is host-only** and exists so the analyst can score misperception.

Suggested framings, to be written properly rather than copied:

| Scenario | Ambiguity |
|---|---|
| `phase1_tel_dispersal_v1` (exists) | Mobile launcher dispersal: survivability hedge, or launch preparation. |
| `phase1_early_warning_v1` | Early-warning system reports a launch signature: real launch, sensor artefact, or a third party. |
| `phase1_exercise_ambiguity_v1` | Large adversary exercise crosses previously observed patterns: routine training, or exercise-as-cover. |

Then add one arm per scenario pinning `scenario_id` and nothing else, e.g.
`configs/arms/baseline_early_warning.yaml`. Each is a committed config, so every run remains
traceable to a file in the repo.

Add a test asserting every scenario in `data/scenarios/` loads and validates, and that its
`forbidden_tokens` are non-empty — a scenario whose guard is empty silently disables the
decontextualisation check.

### 1.2 A session runner

A session is a named set of arm runs over one scenario. Add `src/artsoc/session.py`:

```python
@dataclass
class SessionSpec:
    session_id: str          # uuid4 hex
    label: str
    scenario_id: str
    arms: list[str]          # arm config names
    n: int                   # replications per arm
    seed0: int = 1
```

Minimum viable arm set for a session: `escalation_prior` (the control — every interpretable
number is a delta against it) and one `baseline_*`. The UI should default to those two and
offer the rest, including the `loo_*` family, as opt-in.

Sessions persist to `out/sessions/<session_id>/`: `spec.json`, one `<arm>.jsonl` per arm, and
`summary.json` produced by `metrics.summarise` / `delta`. Nothing new goes into `RunRecord`.

Add `out/sessions/` to `.gitignore` if `out/` does not already cover it.

### 1.3 A derived-views module

Add `src/artsoc/views.py`. Pure functions, no model calls, no I/O beyond reading records. This
is where the average-run selection and the graph/Gantt derivations live, so they are
**tested in Python** rather than reimplemented untested in TypeScript.

Required functions, algorithms specified in Part 4:

```python
def representative_run(records: list[RunRecord]) -> RunRecord: ...
def loop_steps(record: RunRecord) -> list[LoopStep]: ...
def interaction_graph(record: RunRecord) -> InteractionGraph: ...
def engagement_stats(records: list[RunRecord]) -> list[PersonaEngagement]: ...
```

Each returns a pydantic model so it serialises with the same guarantees as the rest of the
schema. Tests: determinism (same input, same output), and that `representative_run` returns a
record actually present in the input.

### 1.4 A read-only local API

Add `src/artsoc/api.py` using FastAPI, exposed as an **optional extra** in `pyproject.toml`:

```toml
[project.optional-dependencies]
api = ["fastapi>=0.115", "uvicorn>=0.30"]
```

**This is a dependency addition — per `CLAUDE.md`, confirm before implementing.** Optional
extra rather than a core dependency so the offline test guarantee and the core install stay
untouched.

Endpoints:

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/scenarios` | id, label, one-line description per scenario |
| `GET` | `/api/arms` | arm name, `notes`, which fields it varies |
| `POST` | `/api/sessions` | creates a session from a `SessionSpec`, returns `session_id` |
| `GET` | `/api/sessions` | list of session summaries |
| `GET` | `/api/sessions/{id}` | spec, status, per-arm progress |
| `GET` | `/api/sessions/{id}/events` | **SSE** progress stream while running |
| `GET` | `/api/sessions/{id}/summary` | `ArmSummary` per arm, `Delta` vs control, warnings |
| `GET` | `/api/sessions/{id}/runs/{arm}/representative` | the representative `RunRecord` plus its derived views |

Run execution happens in a background task; `run_many` is already a generator, so emit one SSE
progress event per completed replication with `{arm, completed, total, rung}`.

**Three hard rules for the API layer:**

1. **Read-only with respect to experiment definition.** It may select among committed arm
   configs. It may not accept arbitrary `RunConfig` overrides from the client. A UI that can
   invent configurations breaks invariant 5 and makes results untraceable.
2. **Never serialise prompts.** Do not add `call_log`, system prompts, or user prompts to any
   response. See 0.4.
3. **`host_ground_truth` is analyst-facing and must be gated.** It is in `RunRecord` for
   scoring misperception. Expose it only behind an explicit "reveal ground truth" toggle,
   clearly marked as host-only and not visible to any agent, so a demo viewer cannot mistake
   it for something the President knew.

### 1.5 Cost and provenance guardrails in the API

The frontend can spend real money. `configs/base.yaml` currently sets `backend: anthropic`.

- `POST /api/sessions` must return an estimated call count — `n × arms × (5 + n_questions × (1 + k_per_question))` as an upper bound before caching — and require an explicit `confirm: true`.
- Every summary response must carry `backend`, `models`, `grounded`, `cache_enabled`,
  `retrieval_mode`, and the `warnings` list from `metrics`.
- If `models` has one distinct value across all roles, the response must be flagged
  `smoke_test: true`, and the UI must render a persistent banner reading
  **SMOKE TEST — NOT A RESULT**.
- If `backend == "mock"`, flag `mock: true` and banner accordingly. Mock text is
  `MOCK:`-prefixed nonsense, so the wordcloud will be meaningless — the UI should say so
  rather than render a cloud of the word "placeholder".

---

## Part 2 — Frontend stack and structure

Vite + React 18 + TypeScript, strict mode. No SSR, no router library beyond `react-router-dom`,
no state management library — React Context plus `useReducer` is sufficient and matches "nothing
extra needed for frontend architecture".

```
frontend/
├── package.json  tsconfig.json  vite.config.ts     # proxy /api → localhost:8000
├── src/
│   ├── main.tsx  App.tsx
│   ├── types/artsoc.ts            # GENERATED — see below
│   ├── api/client.ts              # fetch wrappers, SSE subscription
│   ├── context/SessionContext.tsx # the session store
│   ├── views/
│   │   ├── SessionCreate.tsx
│   │   ├── SessionRunning.tsx
│   │   ├── SessionResults.tsx
│   │   └── RunDetail.tsx
│   ├── components/
│   │   ├── RungHistogram.tsx      ArmComparison.tsx   PipelineSankey.tsx
│   │   ├── TermCloud.tsx          EngagementTable.tsx InfluencePanel.tsx
│   │   ├── LoopGantt.tsx          InteractionGraph.tsx EventLog.tsx
│   │   ├── PlaybackControls.tsx   ProvenanceBanner.tsx WarningList.tsx
│   └── lib/playback.ts            # step cursor state machine
```

**Types must be generated, not hand-written.** Add a make target that dumps
`RunRecord.model_json_schema()` and the `views.py` models to JSON Schema, then runs
`json-schema-to-typescript` into `src/types/artsoc.ts`. Hand-maintained types will drift from
pydantic silently, and the drift will surface as blank panels rather than errors.

Libraries: `recharts` (histogram, bar), `d3-sankey` (pipeline flow), `d3-force` (interaction
graph), `d3-cloud` or equivalent (term cloud). Keep the Gantt hand-rolled in SVG — it is a
sequence of positioned rectangles and a library adds more constraint than help.

---

## Part 3 — Views

### 3.1 Session creation

Scenario picker (three cards, each with label and ambiguity description), arm multi-select
(`escalation_prior` pre-selected and locked — it is the control and nothing is interpretable
without it), replication count `n` with a default of 100 and a note that rare-event contrasts
need more, and a cost estimate with explicit confirmation.

### 3.2 Session running

Progress bar per arm from the SSE stream. Live-updating rung histogram as replications land —
this is genuinely useful, since a distribution that is obviously degenerate is worth killing
early. Elapsed time, completed/total, current arm. A cancel control that stops the background
task and keeps completed replications.

### 3.3 Session results

Top: `ProvenanceBanner` (backend, models per role, grounded, cache, retrieval mode) and
`WarningList` rendering `metrics._warnings` output verbatim. These go **above** the charts, not
in a footer, because `docs/measurement.md` makes them gates on interpretation rather than
footnotes.

Then, in order:

1. **Rung distribution** per arm, overlaid or small-multiples. The distribution is the result.
2. **Delta panel** — mean-rung and P(nuclear) deltas against `escalation_prior`, with a header
   stating that only contrasts against the control are interpretable and absolute rates are not
   findings.
3. **Pipeline Sankey** (0.1).
4. **Term cloud** with source toggle and the "not validated theme coding" label (0.2).
5. **Engagement table** (within-arm, descriptive) and **Influence panel** (cross-arm, greyed
   without `loo_*` arms) (0.3).
6. **Run selector** — a link into the representative run. Phase 1 scope is the representative
   run only; the selector should still show it as a list of one with the selection rule stated,
   so it is obvious what is being shown and why.

### 3.4 Run detail

Three coordinated panels sharing one playback cursor:

- **Loop Gantt** (left/top): one row per agent, bars spanning the loop steps where that agent
  was active. Rows for panel personas never consulted are rendered greyed at 20% opacity so the
  unused population stays visible.
- **Interaction graph** (right/top): force-directed, agents as nodes, communications as edges.
  Unconsulted personas greyed but present. Personas that answered `out_of_record` get a
  distinct treatment from those never consulted — declining is a substantive act, not absence.
- **Event log** (side): chronological entries by loop step. Each entry shows the acting agent,
  the recipient where the step is a communication, and the payload — question text, position
  text, brief summary, or action plus justification.

**Playback**: play / pause / step / scrub, speed control, and a step counter. Advancing the
cursor reveals Gantt bars, adds graph edges, and appends log entries in step order. All three
panels read one cursor value from `lib/playback.ts`; do not give them separate state.

---

## Part 4 — Derived-view algorithms

Implement in `src/artsoc/views.py` and test there. The frontend consumes the output.

### 4.1 Representative run selection

The spec says "most average run". Averaging is undefined over records, so select an actual
record deterministically:

1. Compute the median terminal rung across the arm.
2. Take the candidate set of records whose `rung` equals that median.
3. Within candidates, compute the arm-mean of `len(opinions)` and of the count of
   `out_of_record` opinions. Select the record minimising Euclidean distance to that pair on
   z-scored values.
4. Break remaining ties by lowest `seed`.

Return the record and a `selection_note` string explaining the rule, which the UI displays.
A record selected by an unexplained heuristic will be read as typical when it is not.

### 4.2 Loop step derivation

Deterministic from record structure. Emit `LoopStep {index, role, actor, recipient, kind, payload_ref}`:

| Index | Role | Actor → Recipient | Kind |
|---|---|---|---|
| 0 | — | world → intelligence_officer | `perception` (one per `view` entry) |
| next | `intelligence_officer` | IO → president | `brief` |
| next | `president_query` | president → advisor | `query` |
| next | `advisor_questions` | advisor → advisor | `formulate` (one per `questions` entry) |
| per question | `advisor_selection` | advisor → advisor | `select` (from `routing[i]`) |
| per selected persona | `theorist` | advisor → persona | `consult` |
| per opinion | `theorist` | persona → advisor | `opine` (or `decline` when `out_of_record`) |
| next | `advisor_synthesis` | advisor → president | `synthesise` |
| last | `president_decision` | president → world | `decide` |

Order within a question follows `routing[i].selected` order, which is
`matched_by_tag + chosen_by_advisor + topped_up`. Match opinions to consultations on
`(question_id, persona_id)`.

A Gantt bar for an agent spans from its first to its last step index, with gaps rendered where
it is inactive — so the Advisor shows as a long bar with visible idle stretches while theorists
answer, which is an accurate picture of the loop.

### 4.3 Interaction graph

Nodes: `world`, `intelligence_officer`, `president`, `advisor`, plus one per **panel** persona
— not per consulted persona, so the unused population is present and greyable.

Node state: `active` (produced an opinion), `declined` (`out_of_record: true`), `unconsulted`
(in panel, absent from `personas_consulted`), `excluded` (in `config.excluded_personas`, for
`loo_*` arms — render distinctly, since these were removed by intervention rather than unchosen).

Edges carry `{source, target, step_index, kind}` and are typed by kind so the UI can style
consultations, opinions, declines and the final decision differently. Edge weight is call count
where a pair communicates more than once.

Also surface `routing[].hallucinated` — ids the Advisor named that were not on the roster. These
should appear as dashed edges to a phantom node, because the hallucination rate is a finding
about how reliably a model routes and hiding it in a tooltip buries it.

### 4.4 Engagement statistics

Per persona across the arm: times consulted, times chosen by advisor versus topped up, decline
rate, mean `confidence`, citation count, unsupported-citation count. Descriptive only — no
influence language in this panel.

---

## Part 5 — Guardrails

These bind the frontend as much as the backend.

1. **Never present an absolute rate as a finding.** Every rung distribution and P(nuclear)
   figure appears alongside its delta against `escalation_prior`, or with an explicit note that
   the control was not run.
2. **Never label a stub run as grounded.** `grounded` comes from the retriever. Surface it.
3. **Never call term frequency "themes".**
4. **Never call the representative run "the result".** One replication is an anecdote; label it
   as an illustrative single run and keep the distribution visible on the same screen.
5. **Never render `host_ground_truth` without the reveal toggle and its host-only label.**
6. **Never send prompts to the browser.**
7. **Do not add experimental knobs to the UI.** Arm and scenario selection means choosing among
   committed configs. If a control would let a user construct a configuration that no file in
   `configs/` describes, it does not belong.

---

## Part 6 — Build order

Each step ends with `make test` green and something runnable.

1. Scenarios and their arms (1.1), with the load test.
2. `views.py` with `representative_run`, `loop_steps`, `interaction_graph`,
   `engagement_stats`, and tests. **No frontend yet** — these are the pieces most likely to be
   wrong, and they are cheapest to fix in Python.
3. `session.py` and session persistence.
4. `api.py` behind the optional extra, with the guardrails in 1.4 and 1.5. Confirm the
   dependency first.
5. Type generation from JSON Schema, wired into a make target.
6. Frontend skeleton: session creation, running with SSE, results with histogram and delta panel
   only.
7. Sankey, term cloud, engagement and influence panels.
8. Run detail: Gantt, then graph, then event log, then playback last — playback is a cursor over
   three already-working panels and is much easier once they render statically.

## Acceptance

- `make test` passes offline with no API key, unchanged. The API layer must not be importable in
  a way that breaks `tests/conftest.py`.
- A session over `escalation_prior` + one `baseline_*` at n=20 on `backend: mock` completes,
  renders both distributions, shows the delta, and displays a mock banner.
- The representative run renders a Gantt, a graph and an event log that agree on step count, and
  playback advances all three from one cursor.
- Personas never consulted appear greyed in both Gantt and graph rather than being absent.
- Every warning `metrics` emits appears in the UI.
- Selecting a scenario changes which committed arm runs; no request body can specify a config
  that is not on disk.

## Ask before

- Adding the FastAPI dependency (1.4).
- Any change to `RunRecord` or `schema.py`. The frontend should need none; if it seems to, the
  derivation belongs in `views.py` instead.
- Persisting `call_log` or any prompt text.
- Any UI control that varies an experimental parameter not represented by a committed arm.

## Out of scope

Authentication, deployment, multi-user, database persistence, phase 2 multi-nation views, live
editing of scenarios or registry, and inspecting runs other than the representative one.