# Improvements before production

Ordered by whether a claim depends on them, not by effort. Each entry states the current
state, the change, and why it matters — because several of these look like engineering
polish and are actually the difference between a defensible result and an undefendable one.

"Production" here means: results that will be presented and defended, not code serving
traffic. The bar is whether a hostile reviewer can dismiss the finding.

---

## P0 — a claim is currently false or unsupportable without these

### 1. Implement corpus retrieval

**Mechanism done; corpus quality and calibration are what remain.** Every persona is
`corpus_source: markdown` (ADR 0007): `CorpusRetriever` retrieves from a committed claim
index over `data/corpora-src/<id>/*.md` — project-written summaries of each theorist's
publications, chunked and claim-indexed by `ingest.py`, all offline. `base.yaml` ships
`retrieval_mode: corpus`. Wikipedia is retired; its ingest code and tests stay for a persona
moved back. `StubRetriever` is used only by `synth_only` and the test suite. The end-to-end
citation path is exercised in `tests/test_markdown_corpus.py`.

What is left:

- **No persona has primary text.** `corpora-src` documents are secondary — our account of
  what a publication argued, each with a `confidence` field. Better than an encyclopedia
  article; still not the held-out-writings check.
- **The claim-match thresholds are not calibrated.** `retrieval_claim_min_terms` and
  `retrieval_claim_top_k` are reasoned from the shape of the store, not measured against a
  live sweep the way the Wikipedia passage thresholds were. At the committed default
  (`retrieval_claim_min_terms: 3`) the mock question bank matches nothing, so a mock panel
  declines every question.
- **Corroboration depth does not discriminate.** The claims lists do not restate positions
  across an author's works, so every claim is its own group and depth reads ≈1 everywhere.
  Needs claims written to corroborate deliberately, or a model-assisted merge pass (ADR
  0007 flags it as future work).

**Original entry, kept because the reasoning still governs.** Build per-persona indexes over
each theorist's own writings and implement `retrieve`. See
`docs/prompts/01-corpus-retrieval.md`, and `docs/prompts/05-claim-indexed-corpus.md` for the
claim-index brief.

**Why it is first.** The entire M1-versus-M2 contrast currently compares *a name* against *a
name plus one sentence someone wrote by hand*. That is not a test of grounding. Until this
lands, the project's headline claim — that corpus grounding changes decisions where trait
prompting does not — cannot be evaluated at all, and every downstream metric about citation
integrity is measuring the stub.

**On BM25 versus embeddings.** There is no retriever to switch *from*, so this is a design
choice rather than a migration. Start with **BM25**, and treat dense retrieval as a later
comparison rather than the obvious default:

- BM25 needs no embedding model, no API calls at index time, and no GPU, so `make test` stays offline and free — which `tests/conftest.py` currently guarantees and which dense retrieval would put under pressure.
- Passage ids must be content-addressed for `verify_citations` to remain meaningful across rebuilds. BM25 over a fixed chunking makes that trivial; an embedding index adds a second thing that can change underneath stored ids.
- Lexical retrieval is more auditable. When a reviewer asks why a passage was returned, a term-overlap answer is checkable and a cosine similarity is not.
- The known weakness is vocabulary mismatch, which is real here: a question about "credibility" should reach a passage about "the reciprocal fear of surprise attack". That is exactly the case for adding dense retrieval **as an arm** — `retrieval_mode: bm25` versus `retrieval_mode: hybrid` — and measuring whether it changes decisions, rather than assuming it and losing the contrast.

Whatever is chosen, the empty-return threshold is the important parameter, because it is what
makes the out-of-record hatch fire. Tune it deliberately and report it.

### 2. Validate the escalation ladder against a published scale

**Now.** `RUNG` carries an explicit comment that it is not validated against any published
ladder. It is this project's own ordering.

**Change.** Reconcile with a Kahn-derived compressed ladder, document the mapping in an ADR,
and cross-score every action against an established published escalation framework so the
numbers are comparable to prior work.

**Why.** The primary metric is currently ordinal-by-assertion. A reviewer who disagrees with
one placement — is `weapons_test` really level with `forward_deployment`? — can question every
number that follows. Cross-scoring also lets results be compared against the existing
wargaming literature instead of standing alone.

### 3. Remove the smoke-test override from committed config

**Now.** `configs/base.yaml` has `backend: anthropic` and an active
`models_override: claude-haiku-4-5` marked `TEMPORARY — REMOVE BEFORE COLLECTING ANY
RESULTS`.

**Change.** Commit `backend: mock` and no override. Keep live settings in an arm or an
uncommitted local overlay.

**Why.** On a public repo, anyone who clones and runs `artsoc run` immediately spends their
own money and gets output the config itself says is not a result. The warnings mitigate a
default that should not exist. Committed config is the state a stranger should start in, not
the state the last session ended in.

### 4. Fix the empty-docs / prompt mismatch — DONE

`docs/framework/design.md`, `access-matrix.md` and `measurement.md` are written and current.
`CLAUDE.md` no longer claims they are missing. Nothing outstanding.

### 5. Separate the task brief from the README, and check its ownership

**Now.** `README.md` reproduces the originating task brief verbatim, and the repo is MIT
licensed with the author as copyright holder.

**Change.** Replace the verbatim brief with a short paraphrase of the task, or confirm with
whoever wrote it that publishing is fine. Put a legal name in `LICENSE` rather than a GitHub
handle. Add a "Third-party materials" section stating that corpora are not distributed.

**Why.** If the brief came from an employer or programme, the repo is asserting an MIT
licence over text it may not own, and publishing someone else's brief. This is the concrete
version of the IP question, and it is live right now.

---

## P1 — the result is weaker or contestable without these

### 6. Statistical treatment of the arm contrasts

**Now.** `delta` reports point differences in mean rung and P(nuclear). There are no
confidence intervals, no significance tests, and no multiple-comparisons correction across
fifteen `loo_*` arms plus eight others.

**Change.** Bootstrap confidence intervals on every delta. Since rung is ordinal, use a
rank-based test rather than a t-test, or report the full distribution comparison. Apply a
correction across the exclusion family and state it in the report.

**Why.** With twenty-three arms you will find a most-influential theorist whether or not one
exists. A ranked list with no correction is the single easiest thing for a reviewer to
dismiss, and the fix is mechanical.

### 7. Power analysis to set `n`

**Now.** `make phase1` sweeps at n=100 per arm. That number is not derived from anything.

**Change.** Simulate under the observed rung variance to find the n needed to detect a delta
of the size that would be substantively interesting, and record the reasoning in an ADR.

**Why.** "Why 100?" is a question you will be asked, and "it seemed reasonable" is a poor
answer when each run costs money. It may also turn out that n=100 is badly underpowered for
P(nuclear) contrasts, since that is a rare-event rate — detecting a change in a 3% event needs
far more than 100 replications.

### 8. Process-level metrics beyond the terminal rung

**Now.** The primary metric is one ordinal per replication. Rich process data is recorded —
questions, routing, opinions, brief — but not measured.

**Change.** Add metrics over: which options the justification mentions and rejects, dispersion
of positions across the panel, whether minority positions survive into the brief, and the
Advisor's selection rationale patterns.

**Why.** One ordinal per run throws away almost everything the loop produced. Process features
are also harder for a model to have memorised than an outcome, which matters for any
historical-comparison work. And "what did compression drop?" is the genuinely novel question
this architecture is positioned to answer — it deserves a metric, not just an arm.

### 9. Probe for parametric leakage

**Now.** Scenario anonymisation limits historical-outcome leakage. Nothing measures how much
the model already knows.

**Change.** Add a probe suite: ask period-restricted personas about post-cutoff concepts and
measure how often they answer anyway; ask M1 personas questions their corpus does not address
and compare decline rates to M2.

**Why.** Phase 3's entire design rests on era restriction meaning something. If a
`early_deterrence` persona happily reasons about entanglement of modern C2 systems, the corpus
swap is not the clean manipulation the design claims.

### 10. Inter-run reliability and prompt-paraphrase sensitivity

**Now.** Same seed reproduces the same decision. Nothing tests robustness to trivial prompt
rewording.

**Change.** Paraphrase each role's prompt in ways that preserve meaning, rerun, and report how
much the distribution moves.

**Why.** If a semantically neutral rewording shifts mean rung more than the advisory apparatus
does, the finding is about prompt sensitivity rather than about theorists. Better to discover
that yourself.

---

## P2 — engineering and cost, needed before scaling up

### 11. Concurrency above the theorist fan-out

**Now.** The theorist fan-out inside one replication is already parallel — a bounded
`ThreadPoolExecutor` at `config.max_concurrency`, with `test_the_record_is_identical_at_any_concurrency`
pinning that completion order cannot reach the output. What is still serial is everything
above it: `run_many` yields replications one at a time and `run_session` iterates arms one
at a time. The six framing calls per replication (intel → query → questions → brief → COAs →
decision) are a genuine dependency chain and advisor routing is serial by design (each
selection consumes the run rng).

**Change.** Parallelise `run_many` at a bounded width, re-sorting by seed. Replications
share no mutable state — each builds its own client, retriever and rng — and the disk cache
writes atomically. Care needed in `run_session` on the three things currently in the
sequential loop: cumulative cost, progress events, and the cancellation check.

**Why.** Once the response cache is warm a sweep is already fast (≈95% of theorist calls are
disk reads — the seed is deliberately absent from the cache key for cacheable calls). The
win is a cold sweep: replications parallelised from cold all miss the same keys at once, so
the honest shape is a short sequential warm-up until the hit rate saturates, then a wide
fan-out over the now cache-dominated remainder.

### 12. Retry, backoff and partial-failure policy

**Now.** No visible retry logic. A transient API error or a malformed JSON response part-way
through a hundred-replication sweep loses the run.

**Change.** Bounded retry with exponential backoff on transient errors; a schema-repair retry
on unparseable JSON, capped and recorded; and a decision about whether a failed replication is
dropped or the sweep aborts. Record retries in `RunRecord` — a run that needed three attempts
is different data from one that succeeded first time.

**Why.** The schema already shows evidence of this problem: `IntelBrief.confidence` coerces
numeric answers to text because a model answered off-spec on the first live run. That fix was
right, but it is one symptom of a general class, and the general handling is missing.

### 13. Cost accounting per run

**Now.** `llm_calls` and `cache_hits` are recorded. Tokens and spend are not.

**Change.** Record input and output tokens per role per run, and estimated cost. Report totals
in the analysis output.

**Why.** The per-role model assignment in `base.yaml` is justified by measured cost share, but
nothing in the record can verify those percentages. It also makes the pre-sweep estimate the
prompt asks for something you can actually produce.

### 14. Cache key covers the model but not generation parameters

**Now.** `LLMClient._key` hashes backend name, model, `MOCK_VERSION`, role, system prompt,
user prompt and salt. Cross-model contamination — a Haiku smoke-test answer served to an Opus
run — is already prevented, which is the important half and is easy to get wrong.

**Change.** Add `effort` and any other generation parameter that changes output to the key,
and add a test asserting that two clients differing only in `effort` do not share cache
entries. Consider a cache format version alongside `MOCK_VERSION` so a prompt-template change
invalidates stale entries.

**Why.** `effort` is described in `base.yaml` as the main cost dial and it changes output. If
a sweep at `effort: medium` reuses entries written at `effort: low`, the record reports one
setting and the numbers came from another — the same class of provenance failure that ADR
0002 fixed for models.

### 15. CI does not exist

**Now.** No `.github/workflows/`. 145 tests pass locally.

**Change.** Add a workflow running `ruff` and `pytest` on push. The suite is offline by
construction, so no secrets are needed.

**Why.** The invariants are only guaranteed if they run. `conftest.py` protects against
spending money in CI already, so there is no obstacle.

---

## P3 — worth doing, not blocking

### 16. A middle panel-size arm

`small_panel` uses 4 against a base of 15. That confounds "small panel" with "barely a panel".
An arm at 8 makes the size effect readable as a trend rather than a single contrast.

### 17. More scenarios

One scenario means every finding is "in this situation". Two or three with different
ambiguity structure — an unambiguous provocation, an accident, a third-party trigger — would
show whether the advisory effect is scenario-dependent. Cheap to add: scenarios are data, and
`forbidden_tokens` already derives its guard from the scenario rather than from a hardcoded
list.

### 18. Human validation of persona outputs

Even three or four IR academics rating whether persona answers are recognisably that
theorist's position would provide face validity no internal metric can. Worth doing before
corpus retrieval rather than after, so there is a before-and-after comparison.

### 19. Held-out position prediction

Withhold a paper from a theorist's corpus, ask the persona a question that paper answers,
compare. This is the strongest available quantitative check on M2 and it becomes possible the
moment real corpora exist. Report accuracy per method; if M2 does not beat M1, that is
publishable and should be said rather than buried.

### 20. Register a citable version

Zenodo's GitHub integration mints a DOI at a specific date. Given that the methodology is the
asset and a licence does not protect methods, a timestamped citable record is the thing that
actually establishes priority.

### 21. ExComm follow-ups (ADR 0008)

**Now.** The deliberation mechanism landed: the President records a secret lean, an
anonymised 1962-shaped committee debates the three courses round-robin with abstention, the
President chairs within a hard cap, and `mean_lean_shift` reads `excomm_debate` against
`baseline`'s no-debate noise floor.

**What remains, in rough order of value.**

- **Separate the prompt-length confound from the content effect.** `excomm_debate`'s
  decision prompt is longer than `baseline`'s before it differs in content. A length-matched
  padding arm would isolate how much of any measured shift is length rather than argument.
- **President-driven turn-taking.** The committee is round-robin; the real ExComm was chaired
  actively, with the President calling on specific members. Whether that changes which
  arguments surface — and whether it changes the shift — is untested.
- **A disposition-ablation arm**, in the spirit of `loo_*`: remove one seat's disposition
  (replace it with a neutral one) and measure whether the committee's aggregate lean-shift
  moves, the causal-attribution pattern the theorist panel already has.
- **Live calibration of `deliberation_max_rounds` and the roster size**, which are reasoned
  from cost rather than measured against when additional rounds stop changing the outcome.

### 22. Audience follow-ups (ADR 0009)

**Now.** A stratified 70-citizen sample of the 1962 US public reacts to the President's
published decision after it is made: `society.sample_citizens` draws citizens against
committed marginals (`data/society/us_1962/strata.yaml`) and rakes their weights,
`agents.CitizenPanelist` guards every prompt with `assert_decontextualised` and reports a
response-content leakage rate, and `metrics.Delta.d_approval` reads the weighted approval
share against the arm's own control.

**What remains, in rough order of value.**

- **Calibrate the frame against primary sources.** Several of `strata.yaml`'s marginals are
  marked `# UNVERIFIED` — reproduced from general knowledge rather than confirmed against a
  primary Census/Gallup/SRC-NES table in the session that authored the file. This is the
  audience's version of the claim-retrieval thresholds' "mechanism in place, numbers not
  calibrated" status.
- **A joint, correlated construction**, in place of the independent-per-dimension draw plus
  raking. The true 1962 population's stratification dimensions were correlated (region and
  party identification, notably); this sampler does not model that, and a by-stratum
  breakdown read today inherits the gap.
- **A live sweep of `audience_d1` against `escalation_prior`** (or against `baseline`, with
  both running `audience_enabled: true`), to see whether `d_approval` moves at all once real
  models are answering — the mechanism has only been exercised on the mock so far.
- **A second `audience_method`.** Only `"d1"` (independent draw plus raking) is implemented;
  the `RunConfig` field is already there for a second construction method to compare against.
- **A multiple-comparisons correction for `metrics.audience_by_stratum`**, which is currently
  tested but rendered by nothing and carries an explicit caveat instead of a correction.