# ADR 0008 — An ExComm deliberates the courses of action; the President's prior is recorded

Date: 2026-09-10
Status: accepted

## Context

Since ADR 0006 the Advisor proposes three courses of action and the President picks one in a
single `President.decide` call. The requested change inserts a deliberative body between the
proposal and the decision, modelled on the 1962 Cuban Missile Crisis Executive Committee
with the President as chair:

1. The Advisor proposes its three courses (unchanged).
2. The President privately records which one it is currently inclined toward.
3. The President convenes the committee; the three courses, the Advisor's brief and the
   anonymised situation are put to it.
4. The committee debates over rounds. Round-robin; each member sees the running transcript;
   a member with nothing to add abstains. After each round the President, as chair, chooses
   to continue or conclude, up to a hard cap.
5. The President decides, now seeing the transcript — but not the recorded lean.

The measurable is a *within-replication* contrast: `rung(secret_lean) − rung(action)`,
"did the deliberation move the decision-maker off the prior it started with." Nothing like
it exists — `metrics.Delta` only ever compares two arms.

Two things had to be settled before writing any code, because the answers touch invariant 1
directly.

**Can a deliberative body see the situation, and each other?** Invariant 1 says theorists
get a decontextualised question and no peer opinions. Taken literally that would forbid an
ExComm from being briefed or from debating — which is what an ExComm *is*. The resolution is
that invariant 1's theorist boundary is a herding control for *decontextualised elicitation*,
where a persona's position should be its own; a deliberative committee convened over a
specific crisis is a different instrument with its own access row, not a loosening of the
theorist boundary.

**Are the members the historical individuals?** The scenario is `Nation A / Nation B` and not
"Cuba" because a named dyad lets a model retrieve how the real episode ended. A roster of
real names — McNamara, Rusk, RFK — leaks the episode exactly as effectively. So the members
are 1962-*shaped*, not nominal.

## Decision

**The ExComm is a new role set with its own access-matrix row, not an extension of the
theorist panel.** Three new `llm.Role` values — `PRESIDENT_LEAN`, `EXCOMM_MEMBER`,
`PRESIDENT_CHAIR` — each with its own prompt shape, because `llm.py`'s stated design is one
prompt shape per role with no shared scratchpad (the reasoning ADR 0006 used to make
`propose_coas` its own role rather than a field on `synthesise`). `docs/framework/access-matrix.md`
gains rows for all three, and `tests/test_access_matrix.py` gains assertions for each; the
theorist rows are unchanged.

**The ExComm sees the anonymised situation and the running debate; it never sees raw
theorist opinions, the secret lean, or ground truth.** It is briefed the way the President
is — the intel brief and the perceived events in the `Nation A / Nation B` register, through
a single `render_situation` helper that carries only `IntelBrief` and `PerceivedEvent`
fields, neither of which has a `ground_truth_detail`. It reads the Advisor's brief and the
three courses — the compression, not the opinions behind it, the same boundary the President
is held to. Peer visibility is the one channel that is new and intended: a `test_access_matrix.py`
assertion checks that a round-2 member prompt actually contains round-1 statements, so the
exception is documented by an inverted test rather than assumed. The change from "the IO
alone is shown collection output" to "the IO and the ExComm" is made in this ADR's commit,
alongside this document, per the rule that a boundary move and its test change together.

**Members may abstain.** A member with nothing to add returns an abstention and the turn is
recorded with an empty statement, rather than a filler statement being generated to fill the
slot. This is the committee analogue of the theorist's out-of-record hatch, and a near-zero
abstention rate is a warning for the same reason — a panel performing participation.

**The secret lean is typed, recorded on every consulted run, and never prompted.**
`RunRecord.secret_lean` is an `ActionType | None`, so `rung_for` scores it and invariant 2
holds — no free-text parse feeds the primary metric. It is captured by the `PRESIDENT_LEAN`
role before the committee convenes, and then withheld from the simulation entirely: it does
not enter the debate, the chair prompt, or the President's own decision prompt.
`test_access_matrix.py` scans every prompt for it the way it scans for `ground_truth_detail`,
and it is stripped from the client-facing surfaces (`narrative`, `api`, `analysis_payload`)
alongside `host_ground_truth`. It is recorded even on `baseline`, where no debate runs, so
the no-debate lean→decision movement is a measurable decision-instability noise floor.
`None` only on the control arm, where there are no courses to lean over. It is the first
`RunRecord` field of this kind other than `host_ground_truth`, and the pattern is copied
deliberately.

**The lean call is not cached.** It is one endpoint of the lean→decision contrast and the
decision (`PRESIDENT_DECISION`) is never cached, because caching the primary metric would
collapse the Monte Carlo distribution. The two endpoints must have the same variance
treatment, so `PRESIDENT_LEAN` is `cacheable=False` too. Round-1 member turns are cacheable
(their inputs are fixed across replications of an arm); later rounds and the chair are not.

**The President controls the end, within a hard cap.** The `PRESIDENT_CHAIR` call decides
continue-or-conclude after each round; the host forces conclude at `deliberation_max_rounds`
regardless of the model's answer, so the cap is not the model's to override. The cap is
experimental — a `RunConfig` field set in a committed arm, never a CLI flag or a UI control
(invariants 5 and 11).

**The control arm is untouched.** `escalation_prior` has `consult_panel: false`, so the
whole advisory half — including the lean and the deliberation — is skipped; its record has
`secret_lean` `None`, `deliberation` `[]`, `deliberation_rounds` `0`, and `convene_excomm`
is never read. Byte-identical to a pre-change run of the same seed. The new fields default
`None`/`[]`/`0` (ADR 0006's third sub-decision, exactly).

**`SCHEMA_VERSION` moves to `1.3.0`.** Under `convene_excomm: true` the President's decision
prompt gains a debate transcript it did not have before, so `action` cannot be reproduced
from a pre-1.3.0 config and seed. The `secret_lean` and `deliberation` fields look additive
but the mechanism that produces `action` changed — the same test ADR 0006 (`1.1.0`) and ADR
0007 (`1.2.0`) applied. `out/` and `.cache/` hold only dev and smoke records to date, so
nothing is migrated.

**`session.estimate_calls` is updated in the same change.** ADR 0006 added `advisor_coas`
as a real call site in `sim.run_once` and did not add it to the estimate table, so the
pre-run figure has been one call short per replication ever since. That row is added, and so
are `president_lean` and — for a `convene_excomm: true` arm — an upper bound of
`roster_size × deliberation_max_rounds` member turns plus `deliberation_max_rounds` chair
calls (abstention and early conclusion only reduce it). The docstring's "one entry per call
site" claim becomes true again. The per-replication cost is attached below.

**Members are 1962-shaped, not nominal.** Each seat is an institutional `role_title`, an
anonymised `disposition` profile (temperament, ideology, how the member moves under
pressure), and a hand-authored `beliefs` list drawn from that figure's writing — no real
name in the registry file or in any prompt. `data/excomm/registry.yaml` is a separate
population from the theorists; `docs/excomm/roster-key.md` maps `member_id` to the real
figure for maintainers and is read by nothing. The belief system is carried in the identity
prompt, not retrieved — an ExComm member argues in character, it does not do
citation-grounded elicitation, so there is no retrieval call in the debate loop.

## Consequences

The lean adds one call to every `consult_panel: true` arm (nineteen of the twenty committed
arms) — about 5% on a panel arm. The `excomm_debate` arm, with a roster of eleven and a cap
of three rounds, adds roughly 22 calls per replication typically (about 25% of turns abstain
and the chair usually concludes by round two) and 37 at the upper bound, against a current
panel-arm baseline of 21 — so roughly 2× typical, 2.8× worst case, on that one arm.
`excomm_member` is priced at Haiku (many short calls, the theorist's character of work);
`president_lean` and `president_chair` at Sonnet (low-volume judgement); the decision stays
Opus. Develop and test on the mock, which is free. A live `excomm_debate` vs `baseline`
sweep is the only expensive part and is opted into per arm.

The `mean_lean_shift` metric is a new *within-replication* shape and is descriptive, not a
`Delta`. Absolute lean→decision movement inherits the Rivera confound and is not a finding
on its own; the interpretable quantity is `excomm_debate.mean_lean_shift −
baseline.mean_lean_shift`, baseline being the no-debate noise floor. The decision prompt is
also longer on `excomm_debate` even before its content — an inherent confound of the
treatment, acknowledged rather than corrected.

The deliberation loop is sequential by construction (round-robin, each turn depends on the
last), so it does not use the theorist fan-out's `ThreadPoolExecutor` and the "same record
at any concurrency" guarantee is preserved because there is nothing concurrent to reorder.

The following commits wire the stage into `sim.run_once` behind `convene_excomm`, add the
`excomm_debate` arm and the `deliberation_max_rounds` / `excomm_size` `RunConfig` fields,
implement `mean_lean_shift` in `metrics.py`, and update `session.estimate_calls`. This ADR
records the decision; the mechanism it describes — the three roles, the access boundary, the
recorded lean — lands here.

## Alternatives rejected

**Real 1962 individuals in the prompts.** Higher face-fidelity to "mirror the ExComm", but a
roster of real names does to the record what a named dyad would do to the scenario: it
anchors every debate to the real episode's known outcome, which the anonymisation exists to
prevent. The disposition profiles keep the 1962 *distribution* of temperaments without the
leak.

**Full claim-indexed corpora per member (ADR 0007 style).** The belief system is a set of
standing prior positions the member argues from, not a body of evidence it cites. Making it a
retrieval store would add a per-turn retrieval call for no gain and would imply a
citation-integrity story the ExComm does not need.

**Folding the lean into the existing `decide` response.** One prompt shape per role. A
`decide` that also returned a "prior" would be two things in one call, and the lean must be
captured *before* the debate, not alongside the decision that follows it.

**Letting the model override the round cap.** The cap is one of the things being tested. A
chair that could run to any length would make `deliberation_max_rounds` an observation rather
than a control.

**Recording the lean only when the ExComm convenes.** Cheaper — no lean call on the other
nineteen arms — but it removes the no-debate baseline the metric is read against, leaving
`mean_lean_shift` with nothing to be contrasted with.
