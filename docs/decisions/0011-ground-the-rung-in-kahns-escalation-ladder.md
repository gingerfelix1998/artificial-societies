# ADR 0011 — Ground the rung in Kahn's escalation ladder; redesign the analysis around it

Date: 2026-09-12
Status: accepted

## Context

The escalation rung has always been the project's own invented ordering — an eight-level
table with a nuclear cutoff at rung 6, both chosen by us. `CLAUDE.md`'s placeholder list,
`measurement.md`'s "outstanding" note, and `docs/prompts/improvements-log.md` item 2 have
all said this since early in the project: it is defensible as a design decision and
indefensible as a measurement instrument, and it is the single most consequential
unexamined number here. A companion document — `docs/framework/ladder.md`, filed alongside
this ADR — is the single source of truth for what grounds the replacement scale, the
`ActionType`-to-band mapping, and four judgement calls the mapping required. This ADR
records the code and documentation changes that follow from adopting it; the substantive
argument for the ladder itself, its four judgement calls, its reflexivity note, and its
"outstanding" verification status all live in that document and are not restated here.

Two things had to be settled before writing any code, both already answered by
`ladder.md` but worth stating as constraints on the implementation.

**The ladder must stay host-side apparatus.** `rung_for` takes the action and nothing else
— no scenario, no model, no prompt. A 1965 source poses no leakage risk to a 1962 scenario
for the same reason the ladder was never a leakage risk before: it is never shown to any
agent.

**A published ladder does not retire the project's own table, and does not make the old
identity between "nuclear" and "above a rung cutoff" true anymore.** Kahn places
`nuclear_demonstration` at rung 18 — inside Intense Crises, below the unit at which nuclear
weapons are used deliberately — while the project's three other nuclear actions land in
bands 4, 6 and 7. The previous arrangement declared `NUCLEAR_ACTIONS` and `NUCLEAR_THRESHOLD`
independently *so that a test could assert they agreed*. Under Kahn's banding they do not,
and overriding his ordering to preserve that agreement would have cost most of the reason
for adopting his ladder in the first place (`ladder.md`, "Nuclear use and the ordinal are
now separate").

The task also asked for the analysis around the metric to be redesigned as what it actually
is — a designed experiment with ordinal and binary responses — rather than described in
language that reads like a classification task, and for several small, independently
motivated fixes that surfaced while working in the same files.

## Decision

**`docs/framework/ladder.md` is filed verbatim and its band structure, mapping and four
judgement calls are not reopened here.** Where I would have made a different call — none of
the four are disputed; they are each argued from the action's actual meaning (a
demonstrative self-test versus employment against the adversary for `weapons_test`; central
versus local counterforce for `nuclear_counterforce`) rather than from convenience, and the
alternative readings considered are the ones I would have raised. Disagreement, if any,
belongs in this paragraph, not in a changed mapping — there is none to record.

**Two ladders live side by side in `schema.py`, and every scored record says which one
produced it.** `RUNG` is renamed `RUNG_PROJECT` (values unchanged) and reframed as a
secondary sensitivity ordinal. `RUNG_KAHN` maps each `ActionType` to a Kahn band 0–7, each
entry carrying a trailing comment citing the specific Kahn rung(s) — the committed artefact
is this mapping and a citation, never a reproduction of Kahn's forty-four-rung table.
`BAND_UNITS` is the single source of band names and named thresholds; `format_report` and
`docs/framework/ladder.md` both quote it rather than each hand-typing a band name.
`NUCLEAR_THRESHOLD` is deleted outright, replaced by three Kahn-band cutpoints
(`DONT_ROCK_THE_BOAT_BAND = 2`, `NUCLEAR_INCREDULITY_BAND = 3`, `DELIBERATE_NUCLEAR_BAND =
4`) and `NUCLEAR_ACTIONS`, now documented as independent of any band cut rather than
identical to one. `rung_for(action, ladder="kahn")` looks the ladder name up in a small
table and raises on an unknown one; every existing call site that omits `ladder` is
unaffected, and the one test that inspected `rung_for`'s signature to enforce "the action
and nothing else" is updated in this same commit to expect `["action", "ladder"]` — the
ADR-sanctioned case of changing a test alongside the invariant it protects, not editing a
test to make a change pass.

**`PresidentialAction.ladder` records provenance, and its Python default exists only for
old records.** The field defaults to `"project"` so a pre-ADR-0011 record with no `ladder`
key on disk — scored, at the time, under what is now `RUNG_PROJECT` — still reads back to
the value it was actually written with. Every action `sim.py` produces is stamped
`ladder=config.ladder` explicitly (`RunConfig.ladder`, default `"kahn"`) immediately after
`President.decide` returns, rather than relying on that default, so a fresh record's rung
provenance is never left to a class default in disguise. `PresidentialAction.rung`, the
computed field, changes from `rung_for(self.action)` to `rung_for(self.action, self.ladder)`
— recompute-on-read now uses the record's own stamped ladder, never the process's current
config.

**The ladder is a scoring choice, not a treatment — no new arm.** `RunConfig.ladder`
(`"kahn"`/`"project"`, validated against `config.LADDERS`) stays at its default on every
committed arm. Re-scoring an existing output file costs a function call, not a run:
`artsoc rescore <files> --ladder {kahn,project}` re-derives every record's band from its
stored `action` with no model call, wired through `metrics.summarise`/`report_for_files`
gaining an optional `ladder` parameter — `None` (the default, used by `analyse`) scores
each record under its own stamped ladder; an explicit value (used by `rescore`) forces
every record onto that one ladder regardless of provenance. This is a **new subcommand**,
not a flag on `analyse`: `tests/test_configs.py::test_the_other_subcommands_take_no_
experimental_options` already asserts, deliberately, that `analyse` takes no flags at all —
the same "a flag would let someone configure an experiment outside a config file" concern
invariant 5 states for `run`. `--ladder` is not that: it selects which of two already-
committed, deterministic, host-side lookup tables re-reads *already-collected* data,
producing no new `RunRecord` and no model call, so giving it its own subcommand rather than
narrowing that existing, deliberate test is the correct fix, not a workaround.

**`NUCLEAR_ACTIONS` and the band cut are asserted as non-equivalent, not merely allowed to
differ.** The invariant changes from "band at or above the threshold if and only if
nuclear" to "every nuclear action falls in Kahn bands 3 through 7, and deliberate
exemplary use begins at band 4" (`ladder.md`), and a new test asserts the two sets are
*not* equal — `nuclear_demonstration` is nuclear but sits below the headline band. This is
a real feature of the theory made visible rather than flattened: whether a demonstration
counts as crossing the firebreak is a question the literature disputes, not one the scale
should settle silently.

**The analysis is restated as a designed experiment, in `measurement.md`.** Arm config
fields (`persona_method`, `panel_source`, `synthesis_mode`, `convene_excomm`,
`audience_method`, `panel_size`, `loo_*`) are the independent variables, `escalation_prior`
the reference level; theoretical concepts a persona invokes are measured mediators, never
manipulated directly, with the `loo_*` substitution confound stated plainly — removing a
theorist changes the panel's concept mix as a side effect of removing a person, which is a
different quantity from a controlled manipulation of concepts. DVs are enumerated by unit of
analysis: `ActionType` (nominal, replication, the primary descriptive object), band
(ordinal, replication), the three named threshold crossings plus the independent
`NUCLEAR_ACTIONS` predicate (binary, replication, the headline outcomes), `mean_lean_shift`
(paired within-replication against `baseline`'s no-debate rate, not a between-arm
contrast), and `d_approval` (weighted proportion, unit **citizen**, nested in replication).
Seeds are named as a blocking factor: perception draws its own rng stream from the seed, so
two arms run at the same seed are matched, not accidental, and where they overlap
`metrics.paired_contrast` reports the within-seed contrast alongside the unpaired delta.
No accuracy, F1, confusion-matrix or baseline-classifier language appears anywhere in the
restated document — this project has never been a classification task and describing it as
one is the fastest way to invite the wrong statistics.

**New stdlib-only statistics in `metrics.py`, verified against independently computed
worked examples before being trusted in `tests/test_metrics.py`.** `wilson_interval`
(exact Wilson score interval, via `statistics.NormalDist().inv_cdf` — no hardcoded z,
no scipy) backs every threshold-crossing rate. `combine_interval_diff` (Newcombe's
hybrid-score combination) backs every risk difference and, applied to two `mean_interval`s
instead of two Wilson intervals, backs the clustered `d_approval` delta with the same
function — verified to reduce exactly to the textbook two-sample z-interval in that case.
`sign_test` is an *exact* two-sided test via `math.comb`'s exact binomial CDF, contrary to
the usual assumption that a sign test needs a table or scipy. `wilcoxon_signed_rank` is the
normal approximation, tie- and continuity-corrected, explicitly `reliable=False` below 20
matched pairs and surfaced with that caveat rather than suppressed — the same "print the
caveat with the number" pattern `_warnings` already uses for `SMOKE TEST`/`MOCK BACKEND`.
No cumulative-logit/proportional-odds fit is implemented: a validated fit needs a reference
implementation to check numerical convergence against, which this project does not have and
should not fabricate, so it is named in `measurement.md`'s "what would strengthen this" list
as a model family for an external stats tool at write-up time, the same treatment
reasoning-theme coding already gets.

**`ArmSummary`/`Delta` gain fields, not a rename.** A rename of `rung_distribution` or
`mean_rung` would ripple into `frontend/src/types/artsoc.ts` and every component that reads
them for no benefit — the "no band/threshold name in two places" acceptance constraint is
about band *names* and mapping entries, not Python field identifiers. Both dataclasses are
purely extended: `ladder`, `action_distribution`, the four named threshold rates and their
intervals (`p_nuclear_use` alongside the existing `p_nuclear`, which keeps its name but is
now the true `NUCLEAR_ACTIONS` proportion rather than a band-cutoff proxy), `approval_shares`
/`approval_interval`, `mean_refusal_rate`, and matching `d_*_interval` fields on `Delta`.
Every new field is defaulted so the hand-built `ArmSummary` fixtures already in
`tests/test_society.py`/`tests/test_invariants.py` keep constructing unchanged, and
`delta()` guards every new interval computation against `None` for exactly that reason.
`make types`/`tsc`/`npm run build` all stay clean since nothing existing moved.

**Two independently-motivated bug fixes, bundled in because they sit in the same files.**
`world.public_events_from` now filters `covert` events itself rather than documenting a
filter it never performed, and its one call site (`sim._survey_audience`, via `run_once`)
now passes the events the scenario's own nation actually **detected** — `world.events`
minus whatever `PerceptionFilter.view` reported as missed — instead of the raw injected
log regardless of whether anyone perceived it. `sim._assemble_audience_record` now excludes
structural refusals (`CitizenResponse.refused`) from `weighted_approval`/
`unweighted_approval` entirely, rather than letting them land in the distribution as if they
were a genuine `no_opinion` stance; a new `AudienceRecord.refusal_rate` is the fifth
audience diagnostic, alongside response, leakage, no-opinion and stratum-coverage rates.
Neither is an invariant retirement — both are corrections to code that already documented
the behaviour it failed to implement — but both are recorded here because they change what
`measurement.md`'s audience section may claim.

**`design.md`'s theorist-count drift is fixed in the same change.** `data/theorists/
registry.yaml` holds twelve personas across three eras (`early_deterrence`,
`cold_war_theory`, `post_cold_war`); `design.md` said fifteen across four, naming a
`contemporary` era with three theorists that exist in neither the registry nor any other
code. The registry's own count is now correct in `design.md`, `measurement.md`'s "fifteen
exclusion arms" becomes "twelve" (matching the twelve `loo_*.yaml` arms in `Makefile`'s
`LOO_ARMS`, which was already correct), and `contemporary` is named as a planned, unbuilt
addition rather than described as already present.

## Consequences

No new LLM calls, no change to the action space, no change to any prompt. `metrics.py`
grows the statistics primitives and the new `ArmSummary`/`Delta` fields; `schema.py` gains
one table, three constants and one field; `config.py` gains one field; `cli.py` gains one
subcommand; `sim.py`/`world.py` change two call sites each. Every change is a scoring,
reporting or bug-fix change over already-unchanged-prompt-produced records — a live sweep
collected before this ADR remains fully comparable, and re-scoring it under Kahn costs
nothing.

The band distribution is coarser exactly where the previous table was finest — twelve of
fifteen actions now sit in Kahn bands 0 through 3, versus five levels under the old table —
which is the real cost `ladder.md` names and mitigates by making the nominal `ActionType`
distribution the primary descriptive object rather than the band. `mean_rung`/`median_rung`
are demoted in every report, not removed, since `RUNG_PROJECT` sensitivity checks and any
reader comparing against a pre-ADR-0011 write-up still need them.

`loo_kahn` and `loo_freedman` are, respectively, the arm that removes the author of the
primary scoring ladder and the arm that removes the author of its natural citable
secondary — `ladder.md`'s "Reflexivity" section states this and `measurement.md`'s
influence-attribution section now repeats it, because the ladder is applied mechanically by
a lookup table no agent sees and removing either persona's record changes what the panel
argues, not how any outcome is scored, but a reviewer should not have to notice this
unassisted.

**Part 3 of the originating brief — concept-level attribution via claim-level tags and
`loo_tag_*` arms — is out of scope for this change and is not, in my judgement, ready for
phase 1.** It needs a `claims.jsonl` schema change (a conceptual-tag field that does not
exist — claims currently carry `group`/`confidence`/`availability_1962`/`work`/`date`,
nothing conceptual), a new ingest pass across all twelve corpora, and a new arm family —
each a deliberate, separately-reviewable change under invariant 5, not an extension folded
into a metric-grounding change. The existing `loo_*` arms cannot support claim-level
attribution as-is, for the same substitution-confound reason they cannot isolate a
concept's marginal contribution: removing a theorist changes who argues which concepts as a
side effect of removing a person. It is recorded on `docs/prompts/improvements-log.md` as
its own future item, not started here.

## Alternatives rejected

**A `--ladder` flag on `analyse` instead of a new `rescore` subcommand.** Simpler — one
fewer subcommand, one fewer test — but it would require narrowing
`test_the_other_subcommands_take_no_experimental_options`'s existing, deliberate assertion
that `analyse` exposes no flags at all. That test protects against exactly the failure
this project has already named for `run`'s `--backend`: a flag that lets a caller
configure something substantive with no version-controlled record of what was chosen. A
new subcommand sidesteps the conflict entirely rather than arguing a carve-out into an
existing invariant test for marginal convenience.

**Renaming `rung_distribution`/`mean_rung`/`p_nuclear` to name the band or the true nuclear
predicate explicitly.** More self-documenting, but it would ripple into
`frontend/src/types/artsoc.ts` and every component reading those fields for a purely
cosmetic gain, and the actual acceptance constraint — no band or threshold *name* duplicated
with two values — is satisfied by tagging each `ArmSummary` with the `ladder` that produced
it, not by renaming the fields that carry the numbers.

**A hand-rolled proportional-odds (cumulative-logit) fit in `metrics.py`.** Rejected for
the same reason reasoning-theme coding stays unimplemented: an unvalidated numerical
procedure that looks like a statistical result is worse than none, and this project has no
reference implementation to check a hand-rolled IRLS fit's convergence against. Named as a
deferred, external-tool model family instead.

**Overriding Kahn's placement of `nuclear_demonstration` to preserve the old "nuclear
implies above-threshold" identity.** Considered and rejected in `ladder.md` itself
("Nuclear use and the ordinal are now separate") — doing so would have discarded most of
the reason for adopting a published ladder in the first place, in exchange for a simpler
invariant to state.
