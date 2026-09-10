# CLAUDE.md

Guidance for agents working in this repository. Read this before changing anything.

## What this is

A research instrument, not a product. It simulates how a panel of nuclear-strategy theorists,
mediated by an advisor and an intelligence officer, shapes a single presidential decision
under crisis. Phase 1 is one nation, one injected event, one closed loop, replicated under
Monte Carlo.

The output is a **distribution over escalation rungs across many replications**, plus ablation
contrasts. It is not a prediction, and no single transcript is a result.

Read the **Delivery** section of `README.md` first. It states what the project is delivering,
the claim it is building toward, and what will never be claimed. Judge implementation
trade-offs against that: a shortcut that makes the code work but weakens what can be claimed
is a net loss, even when tests pass.

## Which document is authoritative for what

This file holds the invariants and nothing else. Detail lives in one place only, because two
sources of truth drift apart and the copy you happen to read wins.

| Question | Document |
|---|---|
| What is this delivering, and what will never be claimed? | `README.md` → Delivery |
| How is it built, and why is it built that way? | `docs/framework/design.md` |
| Who may see what, and why each boundary exists? | `docs/framework/access-matrix.md` |
| What is measured, and what may be claimed from a run? | `docs/framework/measurement.md` |
| What still needs fixing before results are presented? | `docs/prompts/improvements-log.md` |
| Why was a past decision made? | `docs/decisions/` |
| What is a specific piece of work? | `docs/prompts/` |
| How do I run the local viewer, and what may it show? | `frontend/README.md` |

If this file and one of those disagree, this file wins on invariants and the other wins on
detail — and the disagreement is a bug to be fixed in the same change, not left standing.

## Non-negotiable invariants

Enforced by `tests/test_access_matrix.py`, `tests/test_invariants.py`, `tests/test_configs.py`
and `tests/conftest.py`.

**Never edit a test to make a change pass.** If an invariant genuinely needs to change, say so,
write an ADR in `docs/decisions/`, and change the test and the docs together in a commit that
does nothing else. ADR 0002 is the worked example: it retired an invariant properly by stating
the original reasoning, showing the precondition was met, and replacing it with something
narrower and stronger.

**The numbers below are load-bearing.** Invariants 1, 4 and 5 are referenced by number in
`agents.py`, `personas.py`, `retrieval.py`, `cli.py`, `config.py`, `base.yaml`,
`docs/framework/access-matrix.md`, `docs/approach/` and four test modules. Never renumber.
Append new invariants at the end.

1. **Role context boundaries.** Theorists get a decontextualised analytical question and their
   own record — no scenario, no peer opinions. The Advisor never sees intelligence reporting.
   The President never sees raw theorist output, only the brief. `ground_truth_detail` never
   reaches any agent. Do not pass extra context to a role to improve its output: that is the
   experiment leaking, and it invalidates every run in `out/`. Reasons for each boundary are in
   `docs/framework/access-matrix.md`; knowing them is what prevents well-meant violations.

2. **The escalation rung is deterministic.** `schema.RUNG`, keyed on the typed action, and
   `rung_for` sees nothing else. Never introduce a model judge, heuristic or free-text parse
   into the primary metric. A judge may code *reasoning*; it may never feed the rung.

3. **The action space is closed.** The President selects one `ActionType`. No free-text
   actions. A new action goes into `ActionType` **and** `RUNG` in the same change — a test
   fails otherwise.

4. **No silent fallback from grounded to ungrounded retrieval.** A real retriever raises rather
   than degrading to `StubRetriever`, and `grounded` travels with the retriever rather than
   being set by a caller. A silent fallback would let an ungrounded run be written up as
   corpus-grounded, and no test downstream could detect it afterwards.

5. **Arms are config files.** Anything that changes what is being tested goes in
   `configs/arms/*.yaml` and `RunConfig`. Only `--n`, `--seed0`, `--out-dir` and `--append` may
   be CLI-only, because they are operational, not experimental.

6. **Never commit `data/corpora/`, `out/` or `.env`.** Corpora are copyrighted source material.
   Run outputs are reproducible from a config plus a seed. A key committed once stays in the
   history whether or not it is later removed — treat an accidental commit as a leaked key and
   rotate it rather than rewriting history.

7. **The test suite never reaches a live backend.** `tests/conftest.py` refuses to construct
   one, autouse and unconditional. `make test` must run on a disconnected machine with no API
   key and must never spend money. This holds regardless of what `configs/base.yaml` says,
   which is the point: protecting it by config alone breaks the moment someone switches over
   for a live run. (ADR 0002.)

8. **A live backend fails loudly without credentials.** It never degrades to the mock. Same
   rule as invariant 4 and for the same reason: a mock run written up as a live one is the
   failure that cannot be detected afterwards. `configs/base.yaml` ships `backend: mock` and a
   live run is opted into. Mock output stays `MOCK_PREFIX`-marked and content-nonsense so the
   two remain distinguishable in the record.

9. **Provenance comes from what happened, not what was asked for.** `RunRecord.models` records
   which model actually served each role, taken from the backend that served it.
   `RunRecord.grounded` comes from the retriever that produced the text. A record that cannot
   say what produced its numbers is not a record.

10. **Prompts do not leave the process.** `call_log` holds every system and user prompt, which
    is exactly what the access-matrix tests scan. Do not persist it into `RunRecord`, serialise
    it over an API, or send it to a browser. Doing so creates a second surface where context
    can cross a boundary, outside the tests that guard the first.

11. **No experimental knob on any user-facing surface.** A UI or API may select among committed
    arm configs and scenarios. It may not accept arbitrary `RunConfig` overrides. If a control
    would let someone construct a configuration that no file in `configs/` describes, it breaks
    invariant 5 by another route and makes results untraceable.

## Known confound you must not paper over

Off-the-shelf models escalate in wargame settings even from neutral starting conditions, and do
so unpredictably (Rivera et al., FAccT 2024). The absolute rung distribution from any arm is
therefore **not** a finding about nuclear strategists. Only the contrast against
`escalation_prior` is interpretable. Report deltas against that arm; never report absolute
escalation rates as results.

## Interpretation constraints

Full detail in `docs/framework/measurement.md`. The three most easily forgotten:

- **Report distributions, never a modal narrative.** One run reaching a nuclear rung is an
  anecdote.
- **A near-zero out-of-record rate is a warning, not a success.** It means the escape hatch is
  not firing and personas are extrapolating past their record.
- **Say which variance you measured.** With caching on it is variance in the decision step
  given fixed advisory input; with it off it is whole-system variance. Both are legitimate and
  they answer different questions.

On influence: attribution comes from the `loo_*` forced-exclusion arms, where the persona is
absent from the panel, every roster and every prompt. That is causal. The observational
alternative — comparing runs where a persona happened to be routed in against runs where it was
not — is confounded and is not used here. Any influence figure must state which produced it.

## Placeholders that must not be described as finished

- `registry.yaml` `corpus_notes` are one-line paraphrases. Still used by `StubRetriever`
  (the `synth_only` arm) and as the M3 identity text; not evidence, and no grounding claim
  rests on them.
- `prominence` values are invented and weight nothing.
- **No persona has primary text.** Every persona is `corpus_source: markdown` (ADR 0007):
  `data/corpora-src/<persona_id>/*.md` are project-written **summaries** of specific
  publications, claim-indexed, each carrying an accurate `confidence` field. Better than an
  encyclopedia article *about* the author; still secondary, and it does not support the
  held-out-writings check. Wikipedia is retired — its ingest code and tests remain for a
  persona moved back, and `registry.yaml`'s `wikipedia` / `semantic_scholar` / `key_works`
  fields are kept but unread.
- Corroboration depth is a diagnostic about corpus breadth, not evidence of agreement.
  Grouping is negation-blind, and with a few documents per theorist almost every group is a
  singleton — depth reads ≈1 everywhere, so `SINGLE-SOURCE POSITIONS` fires on every run and
  is a note, not a severe banner.
- Claim-retrieval thresholds (`retrieval_claim_min_terms`, `retrieval_claim_top_k`) are
  reasoned, not calibrated against a live sweep the way the passage thresholds were. At the
  committed default (`retrieval_claim_min_terms: 3`) a mock run's panel declines every
  question — the mock question bank shares too few terms with any claim.
- `schema.RUNG` has not been validated against a published escalation ladder.
- Reasoning-theme coding does not exist.
- Arm contrasts have no confidence intervals and no multiple-comparisons correction.

Never report a run as grounded in more than what actually served it: `StubRetriever` is
never grounded at all, and `grounded: true` alone does not say whether the text was a
summary or a generated belief — read `corpus_tier`. If asked to "finish phase 1",
`docs/prompts/improvements-log.md` is the ordered backlog — P0 are where a claim is currently
false or unsupportable.

## Working practice

- Run `make test` before and after any change. The mock backend exercises the whole loop with
  no API key, so there is no excuse for skipping it.
- Prefer adding an arm config over adding a branch in `sim.py`. There is exactly one conditional
  on arm behaviour in that module; a new arm needing a second one means the thing being varied
  belongs in `RunConfig`.
- Prefer making a failure impossible to express over remembering to prevent it. `PerceivedEvent`
  having no `ground_truth_detail` field is the pattern: leaking requires editing a class, not
  forgetting a line.
- Prefer raising over scrubbing. `assert_decontextualised` fails the run rather than cleaning
  the text, because a leak that is quietly cleaned up is a leak nobody finds out about.
- Put derivations in Python with tests, not in a client. Anything a UI needs computed belongs in
  a module that `pytest` can reach.
- Keep mock outputs shape-correct and content-nonsense. Plausible mock output gets mistaken for
  real output.
- Ask before spending money, before adding a dependency, and before changing `schema.py`. Any
  change that increases per-run API calls needs an estimate attached, not just an
  implementation.
- Do not add an orchestration framework. The control flow is hand-rolled so every prompt, seed
  and selection is recoverable from an output record; a framework's internal prompt handling
  would sit inside the access matrix without being tested.

## Where to look

| Concern | File |
|---|---|
| Message types, action space, rungs, records | `src/artsoc/schema.py` |
| Role prompts and context boundaries | `src/artsoc/agents.py` |
| Persona construction M1–M3, tag vocabulary, routing | `src/artsoc/personas.py` |
| Retrieval interface and the grounded boundary | `src/artsoc/retrieval.py` |
| Corpus building, chunking, the claim index | `src/artsoc/ingest.py` |
| The committed source of record, and what may go in it | `data/corpora-src/README.md` |
| Model choke point, roles, backends, caching | `src/artsoc/llm.py` |
| Orchestration loop and the Monte Carlo runner | `src/artsoc/sim.py` |
| `RunConfig` and arm loading | `src/artsoc/config.py` |
| World log, perception filter, scenarios | `src/artsoc/world.py` |
| Outcome metrics, diagnostics, report rendering | `src/artsoc/metrics.py` |
| CLI surface and the flag invariant | `src/artsoc/cli.py` |
| Derived views a client consumes, all tested here | `src/artsoc/views.py` |
| Model-written summaries, and what they may see | `src/artsoc/narrative.py` |
| Sessions, the cost gate, provenance flags | `src/artsoc/session.py` |
| Local read-only API (optional `api` extra) | `src/artsoc/api.py` |
| The localhost viewer | `frontend/`, and `frontend/README.md` first |