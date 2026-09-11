# Phase 1 Approach:
LLM persona panels for simulating nuclear escalation dynamics. Phase 1: one nation, one event, one closed decision loop, replicated under Monte Carlo.

```bash
make install
make test          # full loop, mock backend, no API key needed
artsoc arms
artsoc run baseline --n 30
artsoc analyse out/baseline.jsonl
```

Full sweep: `make phase1`.

There is **no `--backend` flag**, and there was never meant to be one. Invariant 5 permits
only `--n`, `--seed0`, `--out-dir` and `--append` on the command line, because those are
operational. The backend changes what produced the numbers, so it is experimental: it
lives in `configs/base.yaml` and is recorded in every output record.
`tests/test_configs.py` asserts the parser exposes nothing else.

The mock is the code default (`RunConfig.backend`) and is deliberately shape-correct and
content-nonsense, so no number it produces is a finding. `configs/base.yaml` opts into the
live Anthropic backend per ADR 0002 — a live run needs credentials and fails loudly without
them; `make test` still runs disconnected with no API key, on the mock and the stub
retriever.

## Delivery
Wider context for anyone — human or agent — working in this repo. What follows is what the code is *for*, so that implementation trade-offs can be judged against it.

### What is actually being delivered

Not a simulator. The deliverable is **a defensible methods argument**: a demonstration that a panel of LLM personas, grounded in a real expert literature, produces something more informative about a consequential decision than a single model answering alone — plus an honest account of the conditions under which that stops being true. The originating brief anticipates presenting conclusions and defending methods to senior decision-makers, so every design choice is ultimately judged by whether it survives hostile questioning, not by whether it runs.

That reframes what counts as progress. A shortcut that makes the code work but weakens what can be claimed is a net loss, even when tests pass.

### The claim we are building toward

1. The group being modelled is the **authors of the nuclear-strategy literature**.
   Theorists are the 100 personas; President, Advisor and Intelligence Officer are
   instruments that aggregate and act on those opinions, not samples of the population.
2. This population is unusually well suited to LLM personas because its authorship is
   nearly enumerable and has a written record, so personas can be grounded in primary
   text and checked against held-out writings — a check most persona work cannot run.
3. Whether grounding, panel size, and the reporting of minority views change *decisions*
   rather than just prose is an empirical question, answered by the arms in
   `configs/arms/`, not asserted.
4. Absolute escalation rates say nothing, because base models escalate in wargame
   settings from neutral starting conditions. Only contrasts against `escalation_prior`
   are interpretable.

### What "phase 1 done" means

Every arm run at n≥100 with a live backend; the claim-match retrieval thresholds calibrated
against a live sweep (the mechanism is in place, ADR 0007; the numbers are not calibrated);
the rung mapping reconciled with a published escalation ladder; reasoning themes validated
against a hand-coded stratified sample; and a written result stated as a distribution and a
delta, with the limitations section written before the findings section.

### What we will never claim

That this predicts state behaviour. There are nine nuclear crises and no instances of
central war, so there is no outcome ground truth and the simulation cannot be validated against outcomes — only against reasoning. The honest framing is structured elicitation of a bounded expert literature under crisis conditions: a tool for surfacing which theoretical commitments drive which recommendations. That framing is both truthful and more useful than a prediction claim, and it should not be quietly upgraded in any write-up.

### Where the design absorbs the known threats

| Threat | Where it is handled |
|---|---|
| Base-model escalation prior | `escalation_prior` arm; report deltas only |
| Personas confabulating positions | M2 out-of-record escape hatch; citation integrity metric |
| Celebrity effects over position effects | M3 synthetic personas (`synth_only` arm) |
| Herding across the panel | Theorists cannot see each other (`test_access_matrix.py`) |
| Minority views lost in compression | `consensus_only` vs `full_range` arms |
| Nominal panels ("100" that is really 6) | `metrics.panel_coverage`, routing tests |
| Historical outcome leakage | Anonymised nations; counterfactual scenario variants |

Detail lives in `docs/framework/design.md` (methods and roadmap), `docs/framework/access-matrix.md`
(boundaries), `docs/framework/measurement.md` (metrics and interpretation limits), and
`CLAUDE.md` (the invariants).

## Layout

```
CLAUDE.md              guardrails for agentic work — read first
configs/
  base.yaml            defaults inherited by every arm
  arms/*.yaml          one file per experimental arm; arms are configs, not flags
data/
  theorists/registry.yaml    persona registry (all corpus_source: markdown)
  scenarios/*.json           injected events + presidential doctrine cards
  corpora-src/<id>/*.md       COMMITTED source of record — project-written summaries
  corpora/                    build artefacts (chunks, claims, manifest) — never committed
docs/framework/
  design.md            population choice, persona methods, loop, roadmap
  access-matrix.md     who may see what, and why each boundary exists
  measurement.md       metrics, diagnostics, interpretation constraints
docs/decisions/        ADRs
src/artsoc/
  schema.py            typed messages, closed action space, deterministic rungs
  world.py             append-only world log, perception filter
  llm.py               single model choke point: mock + live backends, disk cache
  personas.py          persona construction M1/M2/M3, tag vocabulary, routing, ExComm roster
  ingest.py            corpus building: markdown chunking + claim index (ADR 0007)
  retrieval.py         M2 grounding: CorpusRetriever (claim index) and StubRetriever
  agents.py            the roles and their enforced context boundaries, incl. the ExComm
                       deliberation and the secret lean (ADR 0008)
  sim.py               orchestration loop, RunConfig, ablation switches
  narrative.py         model-written run/session summaries (never feed the rung)
  metrics.py           outcome distributions, coverage, citation integrity, lean->decision
  views.py             derived views the frontend consumes, all tested here
  session.py           sessions, cost gate, provenance flags
  api.py               local read-only API (optional `api` extra)
  cli.py               artsoc run / analyse / arms / ingest
tests/
  test_access_matrix.py   canary tests: no role sees forbidden context
  test_invariants.py      rungs, routing coverage, perception, configs, end-to-end
  test_markdown_corpus.py claim index: parsing, chunking, retrieval, citations
  test_retrieval.py       Wikipedia ingest + passage retrieval + belief fallback
  test_excomm.py          the ExComm roster: model, loader, identity prompt
out/                   run outputs, gitignored
```

## Status

`make test`: 478 pass, 1 skip (a Wikipedia-belief spot-check that skips with no Wikipedia
store, by design). `make lint`: clean. `frontend` `tsc`: clean.

**The loop runs end to end, on real retrieval.** `artsoc run`, `artsoc analyse`, `artsoc
ingest` and `make phase1` work offline against the mock backend and stub retriever with no
API key; a live sweep is opted into via `configs/base.yaml`.

Built: the full scaffold (`schema.py`, `world.py`, `llm.py` with mock + live backends,
`personas.py`, `agents.py`, `sim.py`, `metrics.py`, `config.py` and the arms in
`configs/arms/`); courses of action (ADR 0006); the localhost viewer (`views.py`,
`session.py`, `api.py`, `narrative.py`, `frontend/`); corpus retrieval — every persona
retrieves from a committed claim index over project-written summaries of its publications
(`ingest.py`, `retrieval.CorpusRetriever`, ADR 0007); and the ExComm deliberation — an
anonymised, 1962-shaped committee debates the three courses of action before the President
decides, whose prior over them is recorded and never re-prompted
(`data/excomm/registry.yaml`, `agents.ExCommMember`, `sim._deliberate`, ADR 0008). Role
context boundaries are enforced by `tests/test_access_matrix.py`, validated by deliberately
breaking four boundaries and confirming each was caught, plus a deliberate *inverted*
assertion for the one role permitted peer visibility. The end-to-end citation path — a claim
in an `.md` file through retrieval, the theorist's citation, `verify_citations`, the record,
and the analyst-facing `resolve_passages` — is exercised in `tests/test_markdown_corpus.py`.

**A running loop is not a finished phase 1.** The project must not be described as producing
grounded *results* until it has:

- The claim-match thresholds (`retrieval_claim_min_terms`, `retrieval_claim_top_k`)
  calibrated against a live sweep. The mechanism is in place; the numbers are reasoned, not
  measured, and at the committed default a mock panel declines everything.
- A corpus deep enough that corroboration depth discriminates — right now every claim is its
  own group and depth reads ≈1 everywhere.
- `corpus_notes` are placeholders, not evidence; `prominence` values are invented and weight
  nothing.
- `schema.RUNG` reconciled with a published escalation ladder.
- Reasoning themes with a hand-coded agreement sample.
- `mean_lean_shift`'s prompt-length confound (`excomm_debate`'s decision prompt carries the
  transcript; `baseline`'s does not) separated from a content effect.
- Every arm run at n≥100 with a live backend, written up as a distribution and a delta,
  limitations section first.

Every number the loop currently produces comes from a mock whose output is deliberately
content-nonsense. Arms differ under it only because their prompts hash differently.

See `CLAUDE.md` for the invariants and `docs/measurement.md` for what may and may not be claimed from a run.