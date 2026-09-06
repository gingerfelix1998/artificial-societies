# CLAUDE.md

Guidance for agents working in this repository. Read this before changing anything.

## What this is

Read the **Delivery** section of `README.md` first. It states what the project is
delivering, the claim it is building toward, and what will never be claimed. Judge
implementation trade-offs against that: a shortcut that makes the code work but weakens what can be claimed is a net loss, even when tests pass.

A research instrument, not a product. It simulates how a panel of nuclear-strategy
theorists, mediated by an advisor and an intelligence officer, shapes a single
presidential decision under crisis. Phase 1 is one nation, one injected event, one closed loop, replicated under Monte Carlo.

The output is a **distribution over escalation rungs across many replications**, plus
ablation contrasts. It is not a prediction, and no single transcript is a result.

## Non-negotiable invariants

Enforced by `tests/test_access_matrix.py` and `tests/test_invariants.py`.
**Never edit a test to make a change pass.** If an invariant genuinely needs to change, say so, write an ADR in `docs/decisions/`, and change the test and the docs together in a commit that does nothing else.

1. **Role context boundaries.** Theorists get a decontextualised analytical question and nothing else — no scenario details, no peer opinions. The Advisor never sees intelligence reporting. The President never sees raw theorist output, only the brief. The host's `ground_truth_detail` never reaches any agent. Do not pass extra context to an agent to improve its output. That is the experiment leaking, and it invalidates every run in `out/`.

2. **The escalation rung is deterministic.** It comes from `schema.RUNG`, keyed on the typed action. Never introduce a model judge, heuristic, or free-text parse into the primary metric. A judge may code *reasoning*; it may never feed the rung.

3. **The action space is closed.** The President selects one `ActionType`. No free-text actions. A new action must be added to `ActionType` **and** `RUNG` in the same change — a test fails otherwise.

4. **No silent fallback from grounded to ungrounded retrieval.** A real retriever must raise rather than degrade to `StubRetriever`. A silent fallback would let an ungrounded run be written up as corpus-grounded.

5. **Arms are config files.** Anything that changes what is being tested goes in
   `configs/arms/*.yaml` and `RunConfig`. Only `--n`, `--seed0`, `--out-dir` and
   `--append` may be CLI-only, because they are operational, not experimental.

6. **Never commit `data/corpora/` or `out/`.** Corpora are copyrighted source material.
   Run outputs are reproducible from a config plus a seed.

## Why each boundary exists

Knowing the reason prevents well-meant violations.

- **Theorists get no situation context** — it keeps the elicitation analytical rather than advisory, prevents a theorist reasoning about a crisis it has no standing to know about, and makes answers cacheable across replications, which is the main cost control.
- **Theorists cannot see each other** — otherwise later personas anchor on earlier ones and apparent consensus is a herding artifact of call ordering.
- **The Advisor has no collection access** — otherwise the brief stops being a compression
  of expert opinion and becomes a second, unlogged analytic layer.
- **The President never sees raw opinions** — the compression from many opinions into a few hundred tokens is a modelled step. What gets dropped, usually minority positions, is itself a finding; `consensus_only` vs `full_range` isolates it.
- **Ground truth is host-only** — it exists so the analyst can score misperception, not so agents can be correct.

## Known confound you must not paper over

Off-the-shelf models escalate in wargame settings even from neutral starting conditions, and do so unpredictably (Rivera et al., FAccT 2024). The absolute rung distribution from any arm is therefore **not** a finding about nuclear strategists. Only the contrast against `escalation_prior` is interpretable. Report deltas against that arm; never report absolute escalation rates as results.

## Placeholders that must not be described as finished

- `data/theorists/registry.yaml` → `corpus_notes` are one-line paraphrases written to make the loop run. They are not evidence.
- `prominence` values are invented. Set them from citation counts before using weighting.
- Real corpus retrieval is unimplemented; `StubRetriever` is in use.
- `schema.RUNG` has not been validated against a published escalation ladder.
- Reasoning-theme coding has no hand-coded agreement sample.

If asked to "finish phase 1", these are the real work. Never report the project as
producing grounded results while `StubRetriever` is in use.

## Interpretation constraints on any analysis you add

- Report distributions, never a modal narrative. One run reaching a nuclear rung is an anecdote; "10% of 100 replications crossed the threshold" is a result.
- **Panel coverage** gates the panel-size claim. If distinct personas consulted is far below declared panel size, the "100 personas" claim is nominal and must be restated.
- **A near-zero out-of-record rate is a warning, not a success.** It means the escape hatch is not firing and personas are extrapolating past their record.
- **Influence figures are observational, not causal** — routing correlates with question tags, which correlate with outcome. Label them wherever printed. Defensible attribution needs forced-inclusion and forced-exclusion arms.
- **Caching changes what the variance means.** With caching on, measured variance is variance in the decision step given fixed advisory input; with it off, it is whole-system variance. Both are legitimate and they answer different questions. Always state which.

## Working practice

- Run `make test` before and after any change. The stub backend exercises the whole loop with no API key, so there is no excuse for skipping it.
- Prefer adding an arm config over adding a branch in `sim.py`.
- Log everything needed to reproduce a decision: config, seed, routing, opinions, brief, action. If a change would make a past record unreproducible, bump a version field rather than mutating the schema silently.
- Keep stub outputs shape-correct and content-nonsense. Do not make the stub plausible; plausible stub output gets mistaken for real output.
- Ask before spending money. Any change that increases per-run API calls should be flagged with an estimate, not just implemented.
- Do not add an orchestration framework. The control flow is hand-rolled so that every prompt, seed and selection is recoverable from an output record; a framework's internal prompt handling would sit inside the access matrix without being tested.

## Where to look

| Concern | File |
|---|---|
| Message types, action space, rungs | `src/artsoc/schema.py` |
| Role prompts and context boundaries | `src/artsoc/agents.py` |
| Persona construction M1–M3, tags, routing | `src/artsoc/personas.py` |
| Retrieval interface for M2 grounding | `src/artsoc/retrieval.py` |
| Orchestration loop, `RunConfig`, ablations | `src/artsoc/sim.py` |
| World log and misperception | `src/artsoc/world.py` |
| Outcome metrics and diagnostics | `src/artsoc/metrics.py` |
| Project intent and claim structure | `README.md` → Delivery |
| Why a decision was made | `docs/decisions/` |

`docs/design.md`, `docs/access-matrix.md` and `docs/measurement.md` are not yet written. Until they are, this file and the test suite are the only record of the invariants — so treat a change here as a change to the experiment, not to documentation.