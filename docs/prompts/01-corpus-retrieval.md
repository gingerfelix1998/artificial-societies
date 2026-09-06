## Context
See README.md for wider context on the project.

This repo is a research instrument, not a product. It simulates how a panel of
nuclear-strategy theorists, mediated by an advisor and an intelligence officer, shapes a
single presidential decision under crisis. Phase 1 is one nation, one injected event, one
closed loop, replicated under Monte Carlo. The output is a distribution over escalation
rungs plus ablation contrasts — never a single transcript.

> **This brief describes a future state and is not yet actionable.** As of 2026-09-06 the
> scaffolding it assumes does not exist: `retrieval.py`, `personas.py`, `agents.py`,
> `sim.py`, `config.py` and `cli.py` are unwritten, `registry.yaml` is empty, and there is
> no `tests/test_access_matrix.py`. Only `schema.py`, `world.py` and `llm.py` are built.
> Do not start this task until those are in place; see the Status section of
> `docs/approach/phase-01-approach.md`.

The scaffolding is complete and 23 invariant tests pass under `make test` with no API key
(the `mock` LLM backend exercises the whole loop). What is missing is the piece every
claim about grounding rests on: real per-theorist corpus retrieval. Right now
`retrieval.StubRetriever` returns a one-line paraphrase from the registry, so no run may
be described as corpus-grounded.

## Read first, before planning anything

- `CLAUDE.md` — the invariants. These are not negotiable and are enforced by tests.
- `docs/access-matrix.md` — who may see what, and why each boundary exists.
- `docs/measurement.md` — what may and may not be claimed from a run.
- `docs/design.md` — the M1/M2/M3 persona methods and why the out-of-record escape
  hatch is load-bearing.
- `src/artsoc/retrieval.py` — the interface you are implementing, including the comment
  explaining why `CorpusRetriever` raises rather than degrading.
- `src/artsoc/personas.py`, `src/artsoc/agents.py` (the `Theorist` class),
  `src/artsoc/sim.py`, `src/artsoc/config.py`, `src/artsoc/cli.py`.
- `tests/test_access_matrix.py` and `tests/test_invariants.py` — read these carefully.
  They define correct behaviour.

## Task

Implement real M2 corpus grounding end to end.

1. **Ingestion.** Build an index from `data/corpora/<persona_id>/` where `persona_id`
   matches `data/theorists/registry.yaml`. Two hard requirements, both from
   `data/corpora/README.md`:
   - **One store per persona.** A shared index across theorists destroys the design — a
     persona could retrieve another theorist's argument and cite it as its own.
   - **Passage ids stable across rebuilds.** `TheoristOpinion.citations` are verified
     against the retrieved block. If ids shift when the index is rebuilt, every past
     record becomes unverifiable. Derive ids from content, not position.

2. **`CorpusRetriever.__call__`.** Return a formatted passage block with ids for the
   prompt, or `""` when nothing clears the relevance threshold. Returning `""` is the
   mechanism that makes the persona's `out_of_record` escape hatch fire, so treat the
   empty case as a feature to be tested, not an error path.

3. **Wire it through.** `sim.run_once` currently never passes a retriever. Add a config
   knob so an arm selects stub or corpus retrieval, thread it to `Advisor` and
   `Theorist`, and record in every output record whether the run was actually grounded —
   so a later analysis cannot mistake a stub run for a grounded one.

4. **Citation verification.** Run `retrieval.verify_citations` over every M2 opinion and
   log unsupported citations in the output record. Surface the hallucinated-citation rate
   in `metrics.citation_integrity`.

5. **New tests.** At minimum: passage ids stable across a rebuild; persona A's retrieval
   never returns persona B's text; empty retrieval causes `out_of_record` to fire; the
   grounded flag is recorded truthfully; `CorpusRetriever` still raises rather than
   falling back when the corpus root is missing.

6. **Ingestion entry point.** Decide between an `artsoc ingest` subcommand and a
   standalone script, and justify it. There is currently one CLI entry point and I would
   rather keep it that way.

## Hard constraints

- **Never edit an existing test to make a change pass.** If you believe an invariant
  genuinely needs to change, stop and say so in the plan with an ADR proposed in
  `docs/decisions/`. Changing a test and the code in the same breath is the one move
  that would invalidate the project's integrity guarantee.
- **Do not weaken the access matrix.** Theorists get a decontextualised question and
  their own corpus. Nothing else. Do not pass the scenario, the intel brief, peer
  opinions, or `ground_truth_detail` into a theorist prompt to improve answer quality —
  that is the experiment leaking, and it invalidates every run in `out/`.
- **No silent fallback from grounded to ungrounded.** If the corpus is missing or the
  index fails to load, raise. Never quietly substitute `StubRetriever`.
- **Do not touch the primary metric.** `schema.RUNG` is deterministic and no model judges
  it. Do not add a judge, heuristic, or free-text parse to the rung path.
- **Experiments are config files.** Anything that changes what is being tested goes in
  `configs/arms/*.yaml` and `RunConfig`, not a new CLI flag and not a branch in `sim.py`.
- **Never commit anything under `data/corpora/` or `out/`.** Corpora are copyrighted
  source material; run outputs are reproducible from a config plus a seed.
- **Placeholders must keep declaring themselves.** `registry.yaml` `corpus_notes` are
  paraphrase placeholders and `prominence` values are invented. Do not describe the
  project as producing grounded results while either is still in play.

## Ask me before

- **Adding any dependency.** The embedding choice in particular — local model versus API
  embeddings — is a real trade-off with cost, reproducibility and offline-test
  consequences. Present the options with your recommendation; do not just pick one.
- **Any change that increases per-run API calls**, with an estimate attached.
- **Changing the chunking strategy after it is set**, since chunk boundaries determine
  citation granularity and re-chunking invalidates stored citations. Propose it as ADR
  0003 so the choice is recorded.
- **Modifying `registry.yaml` schema**, since 15 personas and several tests depend on it.

## Out of scope

Do not start phase 2 (multi-nation signalling) or phase 3 (comparative periods). Do not
add an orchestration framework — the control flow is deliberately hand-rolled for replay
auditability, per `docs/design.md`. Do not refactor modules that this task does not
touch. Do not improve the mock backend's realism; mock output is deliberately
shape-correct and content-nonsense so it cannot be mistaken for real output.

## Deliverable for this turn

A plan only. Do not write or edit any files yet.

The plan should contain:

1. A file-by-file list of changes, marking each as new or modified.
2. The chunking and passage-id scheme, with an explicit statement of how ids stay stable
   across rebuilds.
3. The dependency decision presented as options with a recommendation, not a choice
   already made.
4. The new tests you will add, each stated as the invariant it protects.
5. Any place where you think an existing invariant or test is wrong — flagged, not
   changed.
6. A cost estimate for ingesting 15 corpora and for a 100-replication grounded run.
7. Open questions you need me to answer before implementing.

Order the work so that `make test` passes at every intermediate commit. Tell me if that
is not achievable and why.