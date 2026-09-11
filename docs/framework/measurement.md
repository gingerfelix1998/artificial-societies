# Measurement

What is measured, what gates a number being read as a result, and what may never be claimed.
Implemented in `src/artsoc/metrics.py`; the primary metric is defined in
`src/artsoc/schema.py`.

## The primary metric: escalation rung

Deterministic. The President selects exactly one `ActionType` from a closed set of fifteen;
`RUNG` maps each to an ordinal 0–8. `rung_for` takes the action and nothing else — it has no
access to the justification, the brief, or a model.

This buys three things. The metric cannot drift between runs or between model versions.
There is no inter-coder agreement to defend for the headline number. And two identical
actions with different justifications score identically, which a judge model would not
guarantee.

It is enforced at the schema level too: `PresidentialAction.rung` is a computed field, and
`_Model._drop_computed_fields` discards any `rung` present in a file being read back and
recomputes it. A hand-edited rung in a JSONL record cannot override the ladder.

`NUCLEAR_THRESHOLD = 6`. `NUCLEAR_ACTIONS` is declared independently of `RUNG` so a test can
assert the two agree rather than deriving one from the other.

**Outstanding: the ladder is not externally validated.** `RUNG` carries an explicit note that
it has not been reconciled with a published escalation ladder. Until it is, the ordering is
this project's own and must be described that way. Reconciling it with a Kahn-derived scale
and cross-scoring against a published framework would make the numbers comparable to the
wargaming literature.

## What a report contains

`format_report` renders, per arm: n, the rung distribution as a histogram, mean and median
rung, P(rung ≥ 6), and the conditions that produced them — backend, models per role,
`cache_enabled`, `retrieval_mode`, `grounded`.

**The distribution leads, because the distribution is the result.** A single run reaching a
nuclear rung is an anecdote. "This proportion of n replications crossed the threshold" is a
finding.

## The only interpretable quantity

`CONTROL_ARM = "escalation_prior"`. Every interpretable number in a report is a **delta
against it**.

This is not a stylistic preference. Off-the-shelf models escalate in wargame settings even
from neutral starting conditions, and this behaviour is well documented across several
independent replications. The absolute rung distribution from any arm is therefore the base
model's prior, not a finding about nuclear strategists. Only the contrast — what the advisory
apparatus changed — is attributable to the thing this project builds.

`delta(arm, control)` computes it; `Delta` is documented as the only interpretable quantity
in the module.

## A second interpretable quantity: lean → decision (ADR 0008)

`Delta` compares two arms. `mean_lean_shift` compares two moments of *the same*
replication: `RunRecord.secret_lean`, the President's prior over the three courses of action
recorded before the ExComm convenes, against `RunRecord.rung`, where the decision actually
landed, both scored through `rung_for` (invariant 2 — the primary metric is never a free-text
judgement). It is the first within-replication contrast in the project; every other
diagnostic here compares across replications or across arms.

**The absolute number is not a finding, for the same reason absolute rung distributions are
not.** A President that moves off its prior on `baseline` — where no debate ran — is not
evidence of deliberation; it is the decision call's own instability, since the lean and the
decision are two independent calls over the same inputs. That instability is the noise floor,
and it is why the lean is recorded on `baseline` as well as `excomm_debate` rather than only
where a debate actually happens.

**The interpretable quantity is `excomm_debate.mean_lean_shift − baseline.mean_lean_shift`.**
Read together with `p_moved` (the share of replications where the decision differs from the
lean at all) and `mean_deliberation_rounds` / `abstention_rate` (whether the debate that
produced the shift was substantive or nominal — a near-zero abstention rate is a committee
performing participation, the same reading `metrics._warnings` already gives a near-zero
out-of-record rate).

**Two confounds to hold in view.** First, the Rivera confound applies here exactly as it does
to the rung: an off-the-shelf model's tendency to move under social pressure in a wargame
setting is not evidence about the underlying phenomenon. Second, `excomm_debate`'s decision
prompt is strictly longer than `baseline`'s — it carries the transcript — so some of any
measured shift is a prompt-length effect rather than a content effect, and the two are not
currently separated.

## A third interpretable quantity: audience approval (ADR 0009)

`RunRecord.audience`, populated when `audience_enabled` is set, carries a stratified
70-citizen sample's reaction to the President's published decision — the label and the
justification, never the reasoning behind it. Unlike `mean_lean_shift`, this is not a new
within-replication shape: `metrics.Delta.d_approval` is an **across-arm** delta, the same
kind as `d_mean_rung`, because the audience has no earlier stage of its own to be
contrasted against. `d_approval` is the weighted "approve or strongly approve" share, arm
minus control, computed only when both summaries recorded an audience.

**The absolute approval share is not a finding, for the same reason absolute rung
distributions are not.** The Rivera confound applies to a model asked to role-play public
opinion exactly as it applies to a model asked to role-play a decision-maker. Read
`audience_d1.weighted_approval`'s share only as a contrast against whatever control arm
also ran with `audience_enabled: true`.

**Four diagnostics gate the audience the way three already gate the theorist panel.**
Response rate (a missing share is a dropped stratum, not just a smaller n — check
`AudienceRecord.failures` before reading the approval share at all). Leakage rate — the
share of citizen responses that named the real crisis, its real participants, or a
post-1962 event, unprompted. Unlike the panel-coverage ratio, **any nonzero leakage rate is
flagged**, not just a rate below a threshold: a single leaked reference at n=70 is direct
evidence the era-framing failed for at least one citizen, and a ratio-based warning would
average that away. No-opinion rate: **a near-zero rate is a warning, not a success**, the
same reading a near-zero out-of-record rate gets for the theorist panel — it means the
audience is performing an opinion it does not have. Stratum coverage: the worst
per-dimension achieved/target ratio in the raw draw, before raking; a low floor means some
stratum cell's weighted contribution is doing outsized work.

**Two leakage mechanisms exist because they catch different failures.**
`agents.assert_decontextualised`, run at prompt-build time on every citizen call, raises
if a forbidden token (a theorist's name, a claim id, an ExComm label, ground truth) is
about to be *sent*. The leakage-rate diagnostic above catches what that guard structurally
cannot: a model naming the real episode from its own parametric knowledge, with nothing
forbidden ever having appeared in its prompt.

**By-stratum breakdowns are a multiple-comparisons exposure, exactly like the `loo_*`
attribution.** `metrics.audience_by_stratum` computes a weighted-approval share per
stratum category — six dimensions, several categories each — and is tested but rendered by
nothing in `format_report` yet. Reading any one cell as a finding without a correction is
the same error fifteen uncorrected `loo_*` comparisons would be; report it descriptively or
state the correction.

**The sampler's independence assumption is a fact about the method, not about public
opinion.** `society.sample_citizens` draws each stratum dimension independently and rakes
the weights back to the target marginals; the true population's dimensions were
correlated, and this construction does not reproduce that correlation. `data/society/us_1962/README.md`
states this, and any read of a by-stratum breakdown should hold it in view the same way a
corroboration-depth reading holds the corpus's thinness in view.

## Diagnostics that gate interpretation

Three diagnostics decide whether a distribution may be read at all. `_warnings` raises them
into the report automatically.

**Panel coverage.** Distinct personas actually consulted against declared panel size, plus
mean per-run coverage. Below `COVERAGE_WARNING_RATIO = 0.5` the panel is nominal and the
panel-size claim must be restated. This exists because a routing bug once reduced a
nominally large panel to six respondents while every other number looked healthy.

**Citation integrity.** The out-of-record decline rate and the count of unsupported
citations. At or below `OUT_OF_RECORD_WARNING_RATE = 0.02` the escape hatch is suspected of
not firing — personas are answering everything, which means they are extrapolating past their
record rather than declining. **A near-zero decline rate is a warning, not a success.**

`unsupported_citations` are passage ids an opinion cited that were absent from the block it
was shown. They are reported, never corrected: the rate is a finding about the method, and
silently dropping bad citations would erase it.

**What a stated position rested on.** `TheoristOpinion.basis` is `sources`, `claims`,
`beliefs` or `none`, taken from the retriever rather than from the model. It is read
*together with* the decline rate.

Every persona is now `corpus_source: markdown` (ADR 0007), so in practice `basis` is
`claims` or `none` and the live diagnostic is **corroboration depth** — `corroboration` on
each opinion, the number of distinct publications the *deepest* matched claim group spans
(per group, then the maximum, never the union across the groups a block shows). `metrics`
raises `SINGLE-SOURCE POSITIONS` when most claims-basis positions rest on one publication.

Read corroboration depth as a fact about the corpus before reading it as one about the
panel. With two or three documents per theorist almost every group is a singleton — depth
is ≈1 everywhere and the warning fires on every run, which is why it is a note rather than a
banner. And grouping is normalised-token Jaccard, which is negation-blind — two claims
differing only by a "not" share every content token — so depth attests to vocabulary
overlap, never to agreement. It must not be reported as evidence that a position was
corroborated.

ADR 0004's diagnostic — a low decline rate together with most positions resting on
`beliefs`, the sign of a panel asserting ideology where it has no evidence — no longer
applies: no persona uses the belief fallback, so `beliefs_share` is structurally zero. The
`POSITIONS REST ON BELIEF` warning and the belief-store code remain for a persona moved back
to the `wikipedia` pipeline.

**Provenance.** `RunRecord.models` records which model actually served each role. One
distinct value across every role means a smoke test under `models_override`, and the report
marks it **SMOKE TEST, NOT A RESULT** — the presidential decision is the primary metric, and
serving it from the same cheap model as everything else changes what was measured, not just
what it cost.

Mock output is `MOCK_PREFIX`-marked and content-nonsense by design, so a mock sweep can never
be read later as a cheap live run. Under the mock every role reports `"mock"` in
`RunRecord.models`.

## Influence attribution

`_loo_section` contrasts each `loo_<theorist>` arm against the others. Because exclusion is a
**forced intervention** — the persona is absent from the panel, every roster and every prompt
— this is causal in a way the earlier observational approach was not.

The observational alternative, comparing runs where a persona happened to be routed in
against runs where it was not, is confounded: routing correlates with question tags, which
correlate with outcome. That approach is not used here, and any influence number reported
must state which of the two produced it.

Fifteen exclusion arms against one baseline is a multiple-comparisons exposure. With fifteen
theorists you will find a most-influential one whether or not one exists. Pre-register the
comparison and state the correction, or report the ranking descriptively without significance
claims.

## Secondary coding

Reasoning-theme coding of the President's justification is where an LLM judge genuinely adds
something a lookup table cannot: variation in phrasing is the object of study rather than
noise. It is **not implemented**. When it is, it may never feed the rung, and it needs
inter-coder agreement against a hand-coded stratified sample before any theme count appears
in a claim.

## Standing constraints on any claim

**No prediction claim.** There have been nine nuclear crises and no instances of central war.
There is no outcome ground truth, so the simulation cannot be validated against outcomes —
only against reasoning. The honest framing is structured elicitation of a bounded expert
literature under crisis conditions: a tool for surfacing which theoretical commitments drive
which recommendations. That framing must not be quietly upgraded in a write-up, which is
where the upgrade usually happens.

**No grounding claim while `retrieval_mode: stub`.** `StubRetriever` returns registry
paraphrases and reports `grounded=false`. `RunRecord.grounded` is taken from the retriever
that produced the text, so a stub run can never be read as grounded — but nothing stops a
careless write-up saying otherwise. It is stated here so that it cannot be claimed by
accident.

**Say what it was grounded in, not only that it was.** `grounded` is a boolean and stopped
distinguishing runs once a panel could draw on more than one kind of source, so every report
also carries `corpus_tier`: `summary` for the project-written markdown corpus, `encyclopedia`
for Wikipedia and the abstracts alongside it, `belief`, `stub`, `mixed`, or `none`.
`primary` — a theorist's own writing — exists as a value and nothing produces it.

Every persona is `markdown`, so a grounded run reports `summary` (or `none` for a
replication whose panel declined everything). `encyclopedia`, `belief` and `mixed` are
reachable only if a persona is moved back to the `wikipedia` pipeline. A `summary` corpus is
our account of what a publication argued, carrying its own `confidence` field; it is a
better tier than an encyclopedia article *about* the author, and it is still not primary
text. An arm marked `mixed` drew on sources of different evidential weight, so a contrast
against another arm is clean only if that arm mixed them the same way.

**Absolute rates are not findings.** Repeated because it is the constraint most likely to be
forgotten between running a sweep and writing it up.

**State what varied.** `cache_enabled` changes what the variance means: on, it is variance in
the decision step given fixed advisory input; off, it is whole-system variance. Both are
legitimate and they answer different questions. Any reported dispersion must say which.

## What would strengthen the measurement

In rough order of value:

1. Reconcile `RUNG` with a published escalation ladder and cross-score against an established
   framework, so the numbers are comparable to prior work.
2. Calibrate `retrieval_claim_min_terms` and `retrieval_claim_top_k` against a live sweep,
   the way the Wikipedia passage thresholds were. The claim index is in place (ADR 0007) but
   its thresholds are reasoned rather than measured, and at the committed default a mock
   panel declines everything.
3. Deepen corpus corroboration: write claims that deliberately restate a shared position
   across an author's works, or add a model-assisted merge pass, so corroboration depth
   becomes a discriminating metric rather than ≈1 everywhere.
4. Add process-level metrics beyond the terminal rung — which options were raised and
   rejected, the order considerations enter, dispersion of positions across the panel. These
   are richer than a single terminal action and are harder for a model to have memorised.
5. Implement reasoning-theme coding with a validated agreement sample.
6. Probe for parametric leakage directly: ask period-restricted personas about post-cutoff
   concepts and measure how often they answer anyway.
7. Separate the ExComm's prompt-length confound from its content effect (ADR 0008) — run an
   arm where the decision prompt is padded to the debate's length with inert text, so
   `excomm_debate`'s lean-shift can be read against a length-matched noise floor rather than
   only `baseline`'s.
8. Replace round-robin turn-taking with a President-driven chair that calls on specific
   members, closer to how the 1962 ExComm actually ran, and measure whether it changes which
   arguments surface.
9. Calibrate `data/society/us_1962/strata.yaml`'s marginals against primary Census/Gallup/
   SRC-NES tables — several are currently marked `# UNVERIFIED` (ADR 0009), reproduced from
   general knowledge rather than confirmed against a primary source.
10. Replace the audience sampler's independent-per-dimension draw with a joint (correlated)
    construction, so a by-stratum breakdown reflects the true population's structure rather
    than an independence assumption stated as a limitation.