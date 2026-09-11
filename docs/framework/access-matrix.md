# Access matrix

The project's central design claim is that role differentiation is **structural**, not
prompt-level. Each role is a separate object receiving only what its row permits. There is
no shared conversation and no shared scratchpad.

This document states the boundaries and why each exists. `CLAUDE.md` invariant 1 makes them
non-negotiable; `src/artsoc/agents.py` implements them; `tests/test_access_matrix.py`
enforces them from the outside.

## The matrix

| | Perceived events | Own doctrine | Own record | Peer opinions | Intel brief | Advisor brief | Courses of action | Debate transcript | Secret lean | Host ground truth | Public event/statement |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Intelligence Officer** | read | read | — | — | writes | — | — | — | — | **never** | — |
| **President** (query) | — | read | — | — | read | — | — | — | — | **never** | — |
| **Advisor** (questions) | — | — | — | — | — | — | — | — | — | **never** | — |
| **Advisor** (selection) | — | — | — | roster only | — | — | — | — | — | **never** | — |
| **Theorist** | — | — | read | — | — | — | — | — | — | **never** | — |
| **Advisor** (synthesis) | — | — | — | read | — | writes | — | — | — | **never** | — |
| **Advisor** (COAs) | — | — | — | read | — | — | writes | — | — | **never** | — |
| **President** (lean) | — | read | — | — | read | read | read | — | *writes, host-only* | **never** | — |
| **ExComm member** | read | — | — | — | read | read | read | read *(the point)* | — | **never** | — |
| **President** (chair) | — | — | — | — | — | — | — | read | — | **never** | — |
| **President** (decision) | — | read | — | — | read | read | read | read | — | **never** | — |
| **Citizen** | — | — | — | — | — | — | — | — | — | **never** | *read (the point)* |

The Advisor appears four times because it is four roles in `llm.Role`, with separate prompts
and separate model assignments. Its selection step sees persona ids and declared areas — the
roster — not opinions, which do not exist yet at that point in the loop.

**The Citizen row (ADR 0009) reads a different column from everyone else's.** It is the
only role that never sees the intel brief, the advisor brief, a course of action, or the
debate transcript — and the only role permitted the "public event / statement" column,
which is `PublicEvent[]` and one `PublicStatement`, structurally leaner types than
`PerceivedEvent`/`PresidentialAction` (no collection fields, no rung, no `chosen_coa_id`).
It runs strictly *after* `President` (decision), the only role for which that is true, and
its own output never appears in any other role's row — proven by scanning every earlier
role's prompts for it, the mirror image of how the secret lean is proven never to leak
*forward*.

The **ExComm member** row is the first to carry a `read` in the *peer* sense — the debate
transcript — and to see *Perceived events* / *Intel brief*. That is deliberate and is
argued in ADR 0008: a deliberative committee convened over a specific crisis is a different
kind of body from a decontextualised theorist panel. It still never sees raw theorist
opinions (only the Advisor's compression), the President's secret lean, or the host's ground
truth. The situation it sees is the same anonymised `Nation A / Nation B` the President sees.

The **secret lean** (`RunRecord.secret_lean`, ADR 0008) is written by the President's lean
step and then behaves exactly like `host_ground_truth`: recorded for the analyst, scanned
for by `tests/test_access_matrix.py`, and never re-entered into any prompt — not even the
President's own later decision prompt.

## Why each boundary exists

**Theorists get no situation context.** Three reasons. It keeps the elicitation analytical
rather than advisory, so the answer is a position rather than a recommendation. It prevents a
theorist reasoning about a crisis it has no standing to know about. And it makes answers
reusable across replications, which is the main cost control — a decontextualised question
caches; a situated one does not.

**Theorists cannot see each other.** Peer visibility would make apparent consensus a herding
artifact of call ordering. The multi-agent deliberation literature is consistent on this: the
initiator of a discussion exerts outsize influence, and role-prompted agents converge toward
one another's phrasing without contributing complementary reasoning. Denying peer visibility
is a deliberate defence against a documented failure mode, not an arbitrary restriction.

**The Advisor has no collection access.** If it saw intelligence reporting it would begin
reasoning about the situation, and the brief would stop being a compression of expert opinion
and become a second, unlogged analytic layer. What the Advisor knows must be traceable to
what the panel said.

**The President never sees raw opinions.** The compression from many opinions into a few
hundred tokens is a modelled step, not plumbing. What it drops — usually minority positions —
is itself a finding, which is exactly what `consensus_only` versus `full_range` isolates.

**The ExComm member is peer-visible on purpose (ADR 0008).** The theorist prohibition is a
herding control for decontextualised elicitation, where a position should be the persona's
own. A deliberative committee is the opposite instrument: it exists to test whether
structured debate moves a decision-maker, and a debate whose members cannot see each other
is not a debate. So the ExComm member row carries the transcript, and a *new*
`test_access_matrix.py` assertion checks that round 2 actually contains round 1 — the
inversion documents the exception. The committee is still held to every other boundary: the
Advisor's compression rather than raw opinions, no secret lean, no ground truth.

**The ExComm sees the anonymised situation, not the decontextualised nothing.** It is
briefed the way the President is — the intel brief and the perceived events, in the same
`Nation A / Nation B` register. `render_situation` in `agents.py` carries only `IntelBrief`
and `PerceivedEvent` fields, neither of which has a `ground_truth_detail`. The consequence
for the tests: `test_only_the_io_and_the_excomm_are_shown_collection_output` replaced the
old "the IO alone" assertion, changed in the ADR 0008 commit alongside this document.

**The citizen sees the public event and the decision, and nothing that produced it (ADR
0009).** It is an outcome measure, not an input: it exists to react to what became public,
not to reconstruct why the President chose it. `assert_decontextualised` — the same guard
that closes the President's-query path — runs here too, in the other direction: it checks
the prompt about to be *sent* to a citizen, built fresh each replication from every
theorist name and id, every opinion's citations, the ExComm roster when a debate ran, the
intel brief, and every `ground_truth_detail` string. A response-content scan
(`AudienceRecord.leakage_rate`) catches the complementary failure a build-time guard
cannot: a model naming the real crisis from its own training data, with nothing forbidden
ever having been in its prompt.

**The secret lean is recorded and never prompted (ADR 0008).** The President's private prior
over the three courses is captured before the committee convenes, typed as an `ActionType`
so it scores on the ladder, and then withheld from the simulation entirely — including the
President's own decision prompt. It is the first `RunRecord` field of the
"recorded-but-never-prompted" kind other than `host_ground_truth`, and it is guarded the
same way.

**Ground truth is host-only.** `WorldEvent.ground_truth_detail` records what is actually
happening so the analyst can score misperception. It exists so misperception is measurable,
not so an agent can be correct.

## Three enforcement layers

The boundaries are held in three independent ways. Each catches what the others cannot.

### 1. Type separation

`WorldEvent` carries `ground_truth_detail`; `PerceivedEvent` has no such field. The
Intelligence Officer's signature takes `list[PerceivedEvent]`, so the host's truth is not
withheld from it by care — the type it receives cannot express it. Leaking requires editing a
class, not forgetting a line.

This is the strongest layer because it fails at import time rather than at review time.

### 2. The decontextualisation guard

One path could carry situational detail across a boundary: the **President's query**, written
after reading the intelligence brief and read by the Advisor. Every other boundary is closed
by what the role is handed; this one is closed by what the role writes.

`agents.assert_decontextualised` checks the query and each concern against
`sim.forbidden_tokens(scenario)` — the scenario's nation names and label fragments, derived
from the scenario rather than hardcoded, so a new scenario guards itself instead of silently
inheriting the first one's proper nouns. Matching is whole-word.

**It raises `BoundaryViolation` rather than scrubbing.** A leak that is quietly cleaned up is
a leak nobody finds out about; the run should fail loudly and be investigated.

### 3. The prompt-scanning canary suite

`tests/test_access_matrix.py` wraps the LLM client in a recorder that captures every
`(system, prompt)` pair, plants distinctive canary tokens in the scenario, and asserts they
never appear in a forbidden role's prompt. Because every role stamps a `[[ROLE:...]]` marker
into its own system prompt, the scan can attribute each captured prompt to a role.

This layer catches what the other two cannot: context arriving through a path nobody
anticipated. It is the reason the suite is described in ADR 0002 as having been validated by
deliberately breaking four context boundaries and confirming each was caught — a test suite
that has never been shown to fail is not evidence of anything.

## Rules for changing this

**Never edit a test to make a change pass.** If a boundary genuinely needs to move, say so,
write an ADR in `docs/decisions/`, and change the test and this document together in a commit
that does nothing else. That is the process ADR 0002 followed when retiring the offline-only
invariant, and it is the only acceptable route.

**Do not pass extra context to a role to improve its output.** Giving a theorist the scenario
would produce better-reading answers and would invalidate every run in `out/`. If output
quality is the problem, the fix is the persona's own record, not more context.

That is what ADR 0007 did, and it is the worked example of this rule. Grounded runs were
declining every question, and the fix was to change what a theorist's *own record* consists
of — hand-authored claims shown with the passages arguing them, in place of biography — not
to widen what a theorist may see. A claims block carries no scenario, no peer opinion and no
intelligence reporting, so no row in the matrix above moved. `basis` gained a value; the
boundary did not change.

**A new role needs a new row here before it needs code.** Deciding what a role may see is the
design work; implementing it is the easy part.

## What this does not cover

The matrix governs *situational* context. It says nothing about parametric knowledge already
in the model's weights, which is a separate and unsolved problem: a theorist persona knows
about crises it was never told about, and a period-restricted persona in phase 3 has read
every era. That threat is addressed — imperfectly — by scenario anonymisation and by the
probes described in `docs/measurement.md`, not by this matrix.