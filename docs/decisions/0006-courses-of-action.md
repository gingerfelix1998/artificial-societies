# ADR 0006 — Courses of action: the Advisor proposes three, the President picks one

Date: 2026-09-08
Status: accepted

## Context

The President read `AdvisorBrief` and freely selected any of the fifteen `ActionType`s,
writing a free-text justification that never feeds the rung. Requested change: the Advisor
first proposes three distinct courses of action, each grounded in citable support from the
panel's opinions, and the President chooses one of the three rather than choosing freely.

Two things had to be settled before writing any code, because the answers touch invariant 1
directly.

**Can a course of action quote a theorist?** Invariant 1 states the President never sees
raw theorist output, only the Advisor's compression, and `test_access_matrix.py` names and
enforces this. A course of action that embedded `TheoristOpinion.position` or `.reasoning`
verbatim would be exactly the raw output that test forbids, however it were justified.

**Must the three options span a range of severity?** Forcing a restrained/moderate/firm
spread guarantees the President a meaningful-looking choice, but on a question where the
panel's opinions genuinely converge, manufacturing a spread means inventing a
citation-backed case for an option nobody on the panel actually supports.

## Decision

**A course of action is Advisor-authored and cites by id; it never quotes a theorist.**
This is the same relationship `AdvisorBrief.consensus_points` and `.minority_positions`
already have to the opinions behind them — the Advisor's own prose, backed by, not
copied from, the panel. Invariant 1 is therefore unchanged and its existing test needs no
revision; a new test is added alongside it (`test_access_matrix.py`) asserting the same
property for this specific new prompt, because a boundary that holds by construction in one
place is not verified in another until something scans that place too.

**No mandated spread.** The Advisor is instructed to propose three *distinct* actions, each
with a rationale drawn only from the opinions it was shown, and is explicitly told it need
not spread them across severity. Three closely-clustered options, arrived at honestly, is a
more defensible record than three options where one was manufactured to look like a real
choice. The only hard constraint is distinctness: three identical proposals is not three
courses of action.

**The control arm is untouched.** `escalation_prior` and any arm with `consult_panel:
false` has no panel and therefore nothing to cite a course of action from.
`President.decide` keeps its existing free-choice path for exactly that case — this is what
keeps the arm meaningful as the base-rate measurement it already is, and it is why `coas`
is an optional parameter rather than a required one.

**A model naming an action outside the three offered gets one bounded retry, then raises.**
Mirrors `President.query`'s existing `QUERY_ATTEMPTS` pattern for the same class of failure
— a model not following a closed-choice instruction. No silent substitution: a decision
recorded as chosen when it was actually corrected by the host would misstate what happened
in the one field this project treats as ground truth for what the President did.

**`SCHEMA_VERSION` moves to `1.1.0`.** Every prior additive field this session (`basis`,
`retries`, `token_usage`, `models`) left the mechanism generating `action` untouched — they
added observability, not a different process. This changes the mechanism itself: old code
sampled freely from fifteen actions, new code samples from an advisor-curated three. Per
`CLAUDE.md`'s working-practice rule, that is exactly the case for bumping the version rather
than mutating the schema silently. `out/` and `.cache/` hold only dev and smoke-test records
to date, so nothing is migrated; the bump makes the mechanism change visible in every record
produced from here on.

## Consequences

`Advisor.propose_coas` is its own role (`ADVISOR_COAS`) and its own prompt rather than a
field bolted onto `synthesise`'s response. `llm.py`'s own stated design is one prompt shape
per role with no shared scratchpad; a response mixing a prose brief with three structured
options would conflate two different products for no saving worth the coupling. This costs
one additional model call per replication under `consult_panel: true`, priced the same as
`advisor_synthesis` (Sonnet) — a compression/proposal step, not the primary metric.

`PresidentialAction.chosen_coa_id` is `None` under the control arm and populated otherwise,
so a reader can tell which decision process produced a given record without cross-
referencing `courses_of_action`'s emptiness.

## Alternatives rejected

**Letting a course of action quote theorist text directly.** Rejected — this is the
alternative that would have required revising invariant 1 itself, not merely respecting it,
and no case was made that the vividness gained was worth reopening a boundary this project
has otherwise held everywhere.

**Instructing the Advisor to span severity.** Rejected because it trades honesty for the
appearance of choice. A forced spread is a second, quieter place where the panel's actual
opinions could be misrepresented, on top of the compression `AdvisorBrief` already performs
deliberately and visibly.

**Folding COA proposal into `synthesise`.** Rejected on the same one-role-per-shape
principle that already governs every other step in this loop; kept separate so each is
independently testable and neither response schema has to compromise for the other.
