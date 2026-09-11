# ADR 0009 — A citizen audience reacts to the decision, as an outcome measure

Date: 2026-09-11
Status: accepted

## Context

Every population modelled so far is either the group this project studies (the theorists)
or an instrument that acts on that group's opinions (President, Advisor, Intelligence
Officer, and — per ADR 0008 — the ExComm, which debates but still feeds *into* the
decision). The requested change adds a third, structurally different population: a
stratified sample of the 1962 US public that reads the President's decision **after** it is
made and reacts to it. Nothing it produces returns to the President; `escalation_prior`'s
two-call shape and the rung-delta logic are untouched. The brief that specifies this in full
is `docs/prompts/06-audience-integration.md`.

Two things had to be settled before writing any code.

**Does the audience see the state's collection picture, or a public-disclosure view?** The
brief poses this explicitly. `PerceivedEvent` — the type the Intelligence Officer's brief is
built from — already carries `confidence`, `degraded` and `source_note`: the IO's
collection reading, not what a member of the public could know. Handing that to the
audience would make it a second intelligence consumer, not a public. The resolution is
reading (a): a new, leaner `PublicEvent` derived straight from `WorldEvent` (`event_id`,
`t`, `actor_nation`, `description` — nothing else), never from `PerceivedEvent`.

**Does the anonymisation pattern ADR 0008 used for the ExComm apply here?** Not directly.
The ExComm's members are 1962-*shaped* stand-ins for real historical figures, so real names
had to be kept out of the registry and every prompt. Citizens are not stand-ins for anyone;
they are constructed from demographic and attitudinal marginals (region, urbanicity, age
band, sex, education, party identification — `data/society/us_1962/strata.yaml`), so there
is no real identity to anonymise. What still has to be kept out is the *year and the
episode*: `build_citizen_identity_prompt` gives era and demographic context without naming
either, the same ADR-0005 discipline applied to a population that has never been told it is
in 1962 at all. **70 citizens, stratified.** Not 100 — the brief settles this explicitly and
this ADR records the number so it never has to be defended from memory: a sample this size
across six stratification dimensions is already a lot of cells to keep populated (see the
coverage diagnostic below), and 70 keeps the per-replication cost proportionate to what the
rest of a `consult_panel: true` replication already costs.

## Decision

**The audience is a second population, and `design.md`'s population statement now says so
once.** Previously: "the group being modelled is the authors of the nuclear-strategy
literature; President, Advisor and Intelligence Officer are instruments." That statement is
rewritten in `design.md` alone to cover both populations, and is not restated elsewhere —
`CLAUDE.md` and this ADR refer to it rather than duplicating it.

**`PublicEvent` and `PublicStatement` are distinct types, not reused ones, so the boundary
is structural rather than remembered.** `PublicEvent` has no `confidence`/`degraded`/
`source_note` (`PerceivedEvent`'s collection fields) and no `ground_truth_detail`
(`WorldEvent`'s). `PublicStatement` — derived from `PresidentialAction` by
`schema.public_statement_from`, the only way to build one — has no `chosen_coa_id` and no
computed `rung`/`is_nuclear`. Both are `extra="forbid"`, so a caller cannot hand the
audience the state's collection picture or the decision's internal structure by passing the
wrong object: the type it receives cannot express either.

**The audience is ungrounded by construction, and its context is a closed, tested list.**
`agents.CitizenPanelist.respond` builds a prompt from `PublicEvent[]`, one
`PublicStatement`, and the citizen's own stratum attributes — nothing else — and calls the
existing `assert_decontextualised` on the built prompt before sending it, in the opposite
direction from every other call site: guarding what is about to be *sent*, not what a role
writes forward. `forbidden_tokens` is assembled fresh per replication in
`sim._audience_forbidden_tokens`: every theorist name and id (the full registry when no
panel was consulted, since the audience must be guarded even under `escalation_prior`),
every opinion's citations, every ExComm `member_id`/`role_title` when a debate ran, the
intel brief's text, and every `ground_truth_detail` string. `tests/test_access_matrix.py`
scans for all of it the way it scans for the secret lean, in the mirror-image direction: a
citizen's own response must never reach any *earlier* role's prompt either, since the
audience runs last.

**Two independent leakage mechanisms, because they catch different things.**
`assert_decontextualised` is a build-time guard: it raises `BoundaryViolation` if a
forbidden token was ever *in the prompt*, and a run that trips it stops rather than
continuing on a scrubbed prompt. It cannot catch a model naming the real crisis unprompted,
from its own parametric knowledge — nothing forbidden was in the text it was given. That is
`AudienceRecord.leakage_rate`: a response-content scan for the real participants' names and
post-1962 markers, reported as a diagnostic rather than raised as an error, because it is
evidence about the model's training data, not about a prompt that leaked.

**Construction and validation marginals are committed in separate files, and the
independence assumption is stated, not hidden.** `data/society/us_1962/strata.yaml` is what
`society.sample_citizens` draws from; `validation_targets.yaml` is a held-out check, read
only to compute `AudienceRecord.validation_distance`, never to construct the sample. Moving
an item between the two files invalidates the validation reading for every run recorded
before the move (stated in the frame's own `README.md`). The sampler draws each citizen's
stratum values **independently per dimension** and then computes RIM (iterative
proportional) raking weights so the *weighted* panel matches the target marginals — a real
simplification, since 1962's actual population had correlated dimensions (region and party
identification, notably) that this construction does not model. Some of `strata.yaml`'s
marginals are marked `# UNVERIFIED` where I could not confirm them against a primary table
in the session that authored this file, following the same honesty discipline `CLAUDE.md`
already holds `corpus_notes` and `prominence` to.

**The audience is a second, independent top-level conditional in `sim.py`, not nested
inside `consult_panel` the way `convene_excomm` is.** `convene_excomm` changes what the
President sees before deciding, so it had to live inside the `consult_panel` path. The
audience reacts to `action`, which exists whether or not a panel was consulted, and the
brief requires it to compose with `escalation_prior` too — so it cannot be nested there.
This does not violate the "exactly one conditional on arm behaviour" rule as that rule is
actually enforced: `test_sim_has_exactly_one_arm_conditional` pins the literal count of
`config.consult_panel` specifically, which this change does not touch, and `routing_mode`
inside `_consult` already varies arm behaviour on a second axis for the same underlying
reason. A dedicated test pins `config.audience_enabled`'s own occurrence count the same
way, so neither can silently grow a third branch later.

**The citizen role never touches the disk cache, which is stronger than `cacheable=False`
everywhere else.** A citizen's input is the decision and its justification — the thing that
varies by design — so `LLMClient.complete` refuses the cache outright for `Role.CITIZEN`
regardless of `cacheable`/`cache_enabled`, rather than only seed-salting the key the way
`PRESIDENT_DECISION` and `PRESIDENT_LEAN` do. The stronger guarantee exists because, unlike
the decision, two different replications' citizens could plausibly receive byte-identical
public events and statements (a low-diversity arm, or a repeated seed), where seed-salting
alone would not obviously prevent a coincidental cross-replication cache hit.

**`d_approval` is an across-arm delta, computed by `metrics.delta`, not a new
within-replication shape like `mean_lean_shift`.** The brief asks for the audience number to
be read "consistent with how every other number in this project is interpreted" — read
literally, that is `delta()`, the mechanism every other interpretable figure already uses,
rather than inventing a second within-run contrast. `Delta.d_approval` is the weighted
"approve or strongly approve" share, arm minus control, and is `None` unless both summaries
recorded an audience.

**Four diagnostics gate the audience the way three already gate the theorist panel.**
Response rate (a missing share is a dropped stratum, not just a smaller n); leakage rate
(any nonzero rate is flagged — unlike the ratio-based coverage warning, a single leaked
reference is worth surfacing at n=70); no-opinion rate (a near-zero rate is a warning, not a
success, the out-of-record-rate reading applied to a new population); and the worst
per-dimension stratum-coverage ratio across the raw draw. `metrics.audience_by_stratum`
computes a by-stratum approval breakdown — tested, rendered by nothing yet, the same status
ADR 0008 left `views.deliberation_flow` in — with an explicit multiple-comparisons note:
six dimensions times several categories each is a lot of chances to find a difference that
is not there.

**`SCHEMA_VERSION` moves to `1.4.0`, and for once that is purely additive.** Every prior
bump (`1.1.0` through `1.3.0`) recorded a change to the *mechanism* producing `action`.
`RunRecord.audience` is populated by a stage that runs strictly after `action` is decided
and cannot feed back into it, so a pre-1.4.0 record's `action` is still exactly reproducible
from its config and seed — the version still moves because `RunRecord`'s shape moved, and
the reason is recorded here even though, unusually, it is the boring one.

**`session.estimate_calls` adds the citizen role unconditionally on `consult_panel`.**
Because the audience composes with either arm shape, the added `citizen` row sits outside
the `if config.consult_panel:` branch that the rest of `per_role` is built inside, so it
applies to a two-call control-arm estimate exactly as it does to a full panel arm's.

## Consequences

`audience_size` defaults to 70, uncacheable by construction. On top of a `baseline`-shaped
replication (~21 calls) this is a **~4.4×** increase per replication; on top of
`excomm_debate` (~22–37 added calls, ADR 0008) it is a smaller relative but still large
absolute increase (+70 calls flat). None of it is recovered by a warm cache on a re-run,
unlike the theorist fan-out, which is the main reason the cost estimate calls this out
separately rather than folding it into the existing panel-arm cost note. `citizen` is priced
at Haiku (many short, uncached calls — the theorist's character of work); nothing about the
primary metric's model assignment changes.

`d_approval` inherits the same base-rate confound every other delta in this project carries
(Rivera et al., FAccT 2024): the absolute approval share on any one arm is not a finding,
only the contrast against the control is. The frame's sourcing is partially unverified
(`data/society/us_1962/README.md`), so a live sweep built on it should be read as
demonstrating the mechanism, not as a calibrated finding, until the marginals are checked
against primary Census/Gallup/SRC-NES tables — the same status the claim-retrieval
thresholds (ADR 0007) currently have. The independence-assumption sampler is a second,
separate limitation from the sourcing one and is tracked as its own follow-up in
`docs/prompts/improvements-log.md`.

The citizen fan-out reuses the theorist fan-out's index-keyed, re-sorted `ThreadPoolExecutor`
pattern, so `max_concurrency` does not change the record. It draws on its own `random.Random`
stream, seeded identically to perception's, so turning `audience_enabled` on or off cannot
shift panel, routing or perception draws at the same seed — the property that keeps a
`baseline` vs `baseline`-plus-audience contrast clean.

## Alternatives rejected

**Handing the audience `PerceivedEvent[]` directly, collapsing it with `PublicEvent`.** Less
code, but it would make the audience a second intelligence consumer rather than a public —
exactly the reading the brief calls out and rejects. Keeping the types distinct also means a
caller cannot pass the wrong list by accident; collapsing them would remove that guarantee.

**A joint, correlated construction instead of independent-draw-plus-raking.** More faithful
to the true 1962 population, but requires either a real joint table (which was not available
in this session) or a much larger modelling effort for a first pass. Independent draw plus
raking is a standard, well-understood survey-weighting technique and is honest about its own
limitation, which is stated rather than hidden.

**Nesting `audience_enabled` inside `config.consult_panel`, to keep `sim.py`'s literal
conditional count at its current value.** Rejected because it is wrong, not merely
inconvenient: the audience must react to the decision under `escalation_prior` too, so
nesting it would silently disable half of what the brief asks for. The actual invariant —
one conditional gating whether the advisory apparatus runs — is preserved and documented
instead.

**Folding `d_approval` into a new within-replication shape, mirroring `mean_lean_shift`.**
There is no equivalent "prior" for the audience to be compared against within one
replication — the audience has no earlier stage to contrast itself with, unlike the
President's lean-then-decide. An across-arm delta against the control is the correct shape
here, not a stylistic choice to differ from ADR 0008.

**Treating any leakage rate below a small threshold as acceptable, mirroring the coverage
ratio's `0.5`.** Rejected because the failure mode is different in kind: a single response
that names the real crisis is direct evidence the era-framing did not hold for at least one
citizen, and averaging it away behind a ratio would hide exactly the finding the diagnostic
exists to surface.
