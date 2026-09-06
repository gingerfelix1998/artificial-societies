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

There is also no live backend to select. Phase 1 runs entirely offline against the mock,
which is deliberately shape-correct and content-nonsense — no number it produces is a
finding. `llm.get_backend("api")` raises.

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

Status as of 2026-09-06. `make test`: 101 tests passing. `make lint`: clean.

**The scaffold is complete and the loop runs end to end.** `artsoc run`, `artsoc analyse`
and `make phase1` work offline against the mock backend with no API key.

Built: `schema.py` (closed action space, deterministic ladder), `world.py` (world log,
perception filter), `llm.py` (model choke point, mock backend, disk cache), `personas.py`
(M1/M2/M3, tag routing, panel coverage), `retrieval.py` (`StubRetriever`; `CorpusRetriever`
raises), `agents.py` (the four roles), `config.py` and the seven arms in `configs/arms/`,
`sim.py` (orchestration, Monte Carlo, JSONL output), `metrics.py` (distributions, contrasts,
printed caveats), `cli.py`. Role context boundaries are enforced by
`tests/test_access_matrix.py`, which was validated by deliberately breaking four boundaries
and confirming each was caught.

Not written: `coder.py` (reasoning-theme coding), and `docs/design.md`,
`docs/access-matrix.md`, `docs/measurement.md` are still empty.

**A complete scaffold is not a finished phase 1.** Nothing below has been done, and the
project must not be described as producing grounded results until it has:

- Real corpus retrieval. `StubRetriever` returns registry paraphrases and reports
  `grounded=false`; **no run is corpus-grounded**.
- `registry.yaml` `corpus_notes` are placeholders, not evidence; `prominence` values are
  invented and weight nothing.
- `schema.RUNG` has not been reconciled with a published escalation ladder.
- Reasoning themes have no hand-coded agreement sample.
- Every arm run at n≥100 with a live backend, written up as a distribution and a delta,
  limitations section first.

Every number the loop currently produces comes from a mock whose output is deliberately
content-nonsense. Arms differ under it only because their prompts hash differently.

See `CLAUDE.md` for the invariants and `docs/measurement.md` for what may and may not be claimed from a run.