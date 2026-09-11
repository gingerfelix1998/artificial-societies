# ADR 0010 — Real ExComm names and live advisor/citizen chat, in the viewer only

Date: 2026-09-11
Status: accepted

## Context

Two requests, both about the human-facing viewer rather than the simulation: show each
ExComm member's real historical name (mapped from the anonymised `member_id`, per
`docs/excomm/roster-key.md`) so a user can "talk to an advisor and see their reasoning";
and let a user click a population segment in an audience breakdown and talk to a few of
that segment's actual sampled citizens. Confirmed with the user: both are **live,
interactive chat**, not a static transcript viewer.

This runs directly into two things the project currently states without qualification.
`docs/excomm/roster-key.md`'s own header says "No code reads it"; `CLAUDE.md` and ADR 0008
say "read by nothing" / "nothing in the code path reads it." And every live model call in
this codebase so far is either part of the Monte Carlo sweep (`sim.run_once`) or a
neutral, roleless analyst reading figures after the fact (`narrative.summarise_run`,
`narrative.answer_question`) — nothing has previously continued an in-character
conversation with a persona outside the recorded loop.

Both are resolved by narrowing a claim precisely, the way ADR 0002 retired the no-live-
backend invariant: state the original reasoning, show it still holds where it matters, and
replace the claim with something narrower and just as strong.

## Decision

**The real-name map is read by exactly one module, and an existing test already proves
it can never reach further.** `api.py::_load_roster_key` is the only reader of
`docs/excomm/roster-key.md` anywhere in `artsoc`.
`tests/test_api.py::test_nothing_in_artsoc_imports_the_api` already asserts, by walking
every module's AST, that no core module — `sim.py`, `agents.py`, `personas.py`, `llm.py` —
imports `api.py`. That test needed no change to extend its guarantee here: it now also
proves, structurally, that a real name can never reach the simulation or a prompt. The
narrowed claim is: **no real name reaches the simulation or a prompt** — true before this
change and true after it, and tested the same way. What was previously also true, and is
no longer, is the stronger and unnecessary claim that no code anywhere reads the file. That
was never load-bearing; the load-bearing property was always the narrower one.
`docs/excomm/roster-key.md`'s header, `CLAUDE.md`, and ADR 0008's sentence about the file
are corrected in this commit to say so.

**The model is never told the real name, in a live chat either.** `agents.ExCommMember.chat`
builds its system prompt from `personas.build_excomm_identity_prompt` — the same anonymous
function `contribute()` uses — plus one added instruction for the case a chat uniquely
raises: a user can simply ask "who are you really?", so the prompt now says explicitly to
stay in character and decline rather than confirm or guess a real identity.
`agents.CitizenPanelist.chat` has no equivalent identity risk: a `Citizen` has no name to
begin with (ADR 0009). `api.py::_overlay_excomm_names` is the only place a real name enters
an API response, and it runs *after* `views.interaction_graph`/`views.agent_details` have
already produced an anonymous `label` from the record — the overlay is a display
substitution on the way out, never an input to anything upstream.

**New roles, not reused ones — a chat turn is a different prompt shape.** `Role.EXCOMM_CHAT`
and `Role.CITIZEN_CHAT` are new rather than folding into `EXCOMM_MEMBER`/`CITIZEN`, on the
same reasoning ADR 0006 gave `propose_coas` its own role instead of a field on
`synthesise`: `llm.py`'s stated design is one prompt shape per role, and a chat turn
(a growing history plus a free-text question, sent by a human rather than produced by the
loop) is not the fixed shape `contribute()`/`respond()` are. Both get their own
`DEFAULT_MODELS` entry (Sonnet — low-volume, on-demand, quality matters, the
`PRESIDENT_LEAN`/`PRESIDENT_CHAIR` precedent), their own mock handler, and their own
access-matrix row.

**The guard runs on the host-assembled portion only, never on the user's own message.**
`assert_decontextualised` is called on the system prompt plus the situation/brief/COA/
transcript context (or the public event plus statement, for a citizen) — exactly the
inputs the original recorded call was guarded on, with the same forbidden-token list. It
is deliberately *not* run on the growing conversation history or the new message: those
are not something the system assembled and could leak, and raising on a human's own typed
curiosity would be a strange UX for no safety gained. The model's own in-character
instruction is what handles a direct question about identity, not a string-match guard.

**Chat is session-directory state, like the narrative and the analysis — never
`RunRecord`, never `SCHEMA_VERSION`.** A chat is triggered from the viewer after a run has
already finished, is not part of the sweep, and does not feed any metric — the same
category `narrative.summarise_run`/`narrative.answer_question` already occupy.
`session.send_excomm_chat_message`/`send_citizen_chat_message` persist to
`sessions/<id>/chat/<excomm|citizen>/<run_id>/<who_id>.json`, mirroring
`session.analysis_path`'s pattern, and rebuild their context (situation/brief/COAs/
transcript, or public event plus statement) from that run's own record alone — nothing
here re-runs the sweep or reaches for anything not already recorded.

**A per-conversation turn cap, because chat has no dedup-by-question cache.**
`ask_analysis` is billed once per distinct question, ever, because re-asking the same
thing is definitionally the same call. A chat has no equivalent: each turn depends on the
whole growing history, so "the same message" sent twice in two different conversations is
not the same call, and there is nothing to dedupe. `session.CHAT_TURN_CAP = 20` is a plain
spend-safety ceiling instead, past which the session functions raise rather than silently
capping. This cost is on-demand, outside `estimate_calls`, the same accounting
`narrative`/`ask_analysis` already get — it is not part of any arm's per-replication figure
and never will be, because it cannot happen during the sweep.

**ExComm reuses the existing interaction graph; the audience gets a new view — because
they are actually different shapes.** The committee is roughly a dozen named seats, the
same shape the theorist panel already is in `InteractionGraphView`/`AgentPanel`, so
`views.interaction_graph`/`views.agent_details` gained one node/detail per member who
spoke, fully anonymous, and the existing click-to-open-a-panel machinery needed no new
concept — only `AgentPanel`'s header gained a chat box when `kind === 'excomm_member'`. The
audience is 70 anonymous citizens per run, grouped by six strata; that is not
one-node-per-agent, so it gets its own `AudiencePanel` component — bar groups in the
existing `RungHistogram`/`CoaDistribution` idiom, driven by `metrics.audience_by_stratum`
(written for ADR 0009, wired into nothing until now) — rather than being forced into the
theorist-panel graph's shape.

**A citizen segment opens onto the citizens of the run being viewed, not the whole arm.**
`AudienceRecord.citizens`/`.responses` are already inside the `/representative` payload's
record — nothing new had to be shipped to browse them. The aggregate breakdown chart above
them is pooled across the arm's replications (`metrics.audience_by_stratum(arm_records(...))`),
which is more statistically meaningful than one run's 70 citizens; the two are read
together deliberately; the chart states the population-level picture and the cards below
it are illustrative individuals from the one run on screen, the same "representative run,
not the result" framing this page already carries for the theorist panel.

## Consequences

Nothing here changes `schema.py`, `SCHEMA_VERSION`, or what a replication measures. The
cost of a chat is genuinely open-ended per conversation (up to the turn cap) and is not
reflected in any session's cost estimate before it happens, unlike a sweep's — a user who
opens many chats has no pre-flight total the way starting a session does. This is an
accepted, deliberate asymmetry: `invariant 11`'s "no experimental knob" is about
constructing an untraceable *arm configuration*, and a chat message is neither an arm nor
a configuration — it is closer to `ask_analysis`, which carries the same property and has
since it shipped.

`personas.excomm_seat_title` is a small new shared helper (`role_title` up to its own
em-dash) — the display trim `agents.render_deliberation` already did inline, factored out
so the graph label, the transcript line, the roster endpoint, and the panel subtitle
cannot drift apart on how they shorten the identity prompt's longer seat description.

## Alternatives rejected

**A static transcript viewer instead of live chat.** Simpler and zero marginal cost, and
was the recommended default — the user explicitly chose live chat for both features
instead, twice, so this ADR builds that.

**Reading `roster-key.md` from `personas.py` or `agents.py`, gated by a runtime flag.**
Even an unconditionally-false flag puts the file's contents one code change away from the
simulation's own import graph, which is exactly the kind of failure the project's
"structural absence" pattern (`PerceivedEvent` has no `ground_truth_detail` field) exists
to avoid. `api.py` already carries a test proving no core module imports it; reusing that
boundary costs nothing and is strictly stronger than a flag.

**Reusing `Role.EXCOMM_MEMBER`/`Role.CITIZEN` for the chat calls.** They are, in one sense,
"the same participant, continuing to speak" — but the access-matrix suite's per-role
assumptions (one fixed prompt shape per role) would then have to special-case a role that
sometimes takes a debate turn and sometimes takes an open-ended human message, which is
exactly the ambiguity `llm.py`'s one-shape-per-role rule exists to prevent.

**Billing chat the way `ask_analysis` does (dedup by question, cached forever).** Rejected
because a chat's cost is a property of the conversation, not the message: the same words
sent into two different histories are two different calls with two different answers, so
there is nothing meaningful to deduplicate. A turn cap is the honest cost control instead.

**Putting the audience's citizens in the same interaction graph as the theorist panel and
the committee.** Seventy additional nodes on one force-directed graph, grouped by six
overlapping strata, does not read as a graph — approval-by-category is a bar-chart shape,
which is the app's own existing idiom for exactly this kind of comparison.
