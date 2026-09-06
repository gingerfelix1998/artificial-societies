# Phase 1 Approach:
LLM persona panels for simulating nuclear escalation dynamics. Phase 1: one nation, one event, one closed decision loop, replicated under Monte Carlo.

> The commands below are the intended interface. Only `make install` and `make test` work
> today — `cli.py` is not written. See **Status** at the end of this document.

```bash
make install
make test          # full loop, mock backend, no API key needed
artsoc arms
artsoc run baseline --n 30 --backend mock
artsoc analyse out/baseline.jsonl
```

Real model calls: `export ANTHROPIC_API_KEY=...` then `artsoc run baseline --n 100 --backend api`.
Full sweep: `make phase1`.

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

Every arm run at n≥100; real corpus retrieval in place of `StubRetriever`; the rung
mapping reconciled with a published escalation ladder; reasoning themes validated against a hand-coded stratified sample; and a written result stated as a distribution and a delta, with the limitations section written before the findings section.

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

Detail lives in `docs/design.md` (methods and roadmap), `docs/access-matrix.md`
(boundaries), `docs/measurement.md` (metrics and interpretation limits), and `CLAUDE.md` (the invariants).

## Layout

```
CLAUDE.md              guardrails for agentic work — read first
configs/
  base.yaml            defaults inherited by every arm
  arms/*.yaml          one file per experimental arm; arms are configs, not flags
data/
  theorists/registry.yaml    persona registry (corpus_notes are PLACEHOLDERS)
  scenarios/*.json           injected events + presidential doctrine cards
  corpora/                   theorist source texts — never committed
docs/
  design.md            population choice, persona methods, loop, roadmap
  access-matrix.md     who may see what, and why each boundary exists
  measurement.md       metrics, diagnostics, interpretation constraints
  decisions/           ADRs
src/artsoc/
  schema.py            typed messages, closed action space, deterministic rungs
  world.py             append-only world log, perception filter
  llm.py               single model choke point: mock backend + disk cache
  personas.py          persona construction M1/M2/M3, tag vocabulary, routing
  retrieval.py         M2 grounding interface — CorpusRetriever is UNIMPLEMENTED
  agents.py            the four roles and their enforced context boundaries
  sim.py               orchestration loop, RunConfig, ablation switches
  coder.py             secondary coding of reasoning (never feeds the rung)
  metrics.py           outcome distributions, coverage, citation integrity
  cli.py               artsoc run / analyse / arms
tests/
  test_access_matrix.py   canary tests: no role sees forbidden context
  test_invariants.py      rungs, routing coverage, perception, configs, end-to-end
out/                   run outputs, gitignored
```

## Status

The **Layout** section above is the target architecture, not an inventory. Most of it does
not exist yet. Status as of 2026-09-06:

Built and passing (`make test`: 23 tests, `make lint`: clean):

- `schema.py` — the closed action space, the deterministic rung ladder, every message type
- `world.py` — append-only world log, President-only write access, perception filter
- `llm.py` — the single model choke point, offline mock backend, disk cache
- `data/scenarios/phase1_tel_dispersal_v1.json` — the ambiguous injected event

Not written yet: `personas.py`, `retrieval.py`, `agents.py`, `config.py`, `sim.py`,
`coder.py`, `metrics.py`, `cli.py`. `configs/base.yaml`, `configs/arms/*` and
`data/theorists/registry.yaml` are empty; so are `docs/design.md`, `docs/access-matrix.md`
and `docs/measurement.md`. There is no `tests/test_access_matrix.py`, so **no role context
boundary is currently enforced by a test** — the invariant is stated in `CLAUDE.md` and
nothing yet checks it. `pyproject.toml` declares the `artsoc` console script, but `cli.py`
does not exist, so the command does not run.

So the foundation layer is done and the four roles, persona construction, routing,
orchestration and metrics are untouched.

Beyond that scaffold, and not to be described as done: real corpus retrieval
(`StubRetriever` is not written; nothing is grounded), rung validation against a published
ladder, `prominence` weights from real citation counts, hand-coded agreement sample for
reasoning themes.

See `CLAUDE.md` for the invariants and `docs/measurement.md` for what may and may not be claimed from a run.