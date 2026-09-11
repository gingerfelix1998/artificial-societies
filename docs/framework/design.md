# Design

What this project models, how the code is arranged, and why each structural choice was
made. For the invariants themselves see `CLAUDE.md`; for the boundaries in detail see
`docs/access-matrix.md`; for what a run may be claimed to show see `docs/measurement.md`.

## The populations being modelled

The brief asks for 100 personas modelling one group of humans. Here there are, as of ADR
0009, **two** groups modelled, and everything else in the loop is an instrument acting on
one or between them.

**The authors of the nuclear-strategy literature.** The theorists are the population.
President, Advisor and Intelligence Officer are *instruments* — they aggregate and act on
the panel's opinions, and they are not samples of anything. This distinction is the first
thing to state when defending the work, because "a president persona" is not an answer to
"whose opinions is this capturing?". The ExComm (ADR 0008) is a second instrument, not a
second population: it is convened over the decision and feeds *into* it, structurally
unlike either group below.

**The 1962 US public.** A stratified sample (`data/society/us_1962/`, ADR 0009) that reads
the President's decision after it is made and reacts to it. Unlike the theorists, it is not
grounded in a written record and is not checked against held-out writings — it is
constructed from demographic and attitudinal survey marginals (region, urbanicity, age
band, sex, education, party identification) via `society.sample_citizens`, which draws each
stratum value independently and then rakes the sample's weights back to the target
marginals. That independence assumption is a real simplification: the true population's
dimensions were correlated, and this construction does not model that correlation — stated
here and in the frame's own `README.md` rather than left implicit. It is an **outcome
measure**, not an input: nothing it produces returns to the President, and it exists to ask
whether the advisory apparatus this project builds changes anything the public would
notice, not to change what the apparatus does.

The population choice suits LLM personas unusually well: the field's authorship is close to
enumerable and every member left a written record, so personas can be grounded in primary
text and checked against it. That check is what most persona work cannot run.

`data/theorists/registry.yaml` holds **15 real theorists** across four eras:
`early_deterrence` (Brodie, Schelling, Kahn, Wohlstetter), `cold_war_theory` (Jervis,
Waltz, Posen, George), `post_cold_war` (Sagan, Tannenwald, Freedman, Blair) and
`contemporary` (Narang, Talmadge, Lieber & Press). The `era` field is not decoration — it
is the phase 3 experimental variable.

**On 15 versus 100.** The default panel is 15. Fifteen theorists with a written record are
worth more than eighty-five synthetic personas padding a headcount, and `synthetic_panel(n)`
exists for the arms where a larger anonymous panel is the point. The claim this project
defends is about grounding and panel structure, not panel size; where size matters it is
varied as an arm (`small_panel`) rather than fixed at a number taken from the brief. A
100-persona run is `panel_source: synthetic` with `panel_size: 100`, and any write-up of it
must say that 85 of those personas are position-defined constructs.

## Persona construction

Three methods. Each returns a system prompt (`personas.build_identity_prompt`) and a user
prompt (`personas.build_question_prompt`). ADR 0001 records why identity and question are
separate: the identity prompt carries no record and no question, so it is stable across
every question a persona is ever asked, and the retrieved record travels in the user prompt
where the backend's structured markers are read.

| Method | Construction | What it tests |
|---|---|---|
| **M1** | Name only: "You are X, a nuclear-strategy theorist." No record. | The base model's parametric belief about X. The null. |
| **M2** | Name plus retrieved record, citations required, out-of-record hatch offered. | The primary method. Does grounding change decisions or only prose? |
| **M3** | Position only, anonymous, explicitly told not to claim an identity. | Separates position effects from celebrity effects. |

M1 is deliberately **not** offered the escape hatch. With no record to be outside of, "out
of record" would have no meaning, and M1 exists precisely to show what a name alone
produces.

**The out-of-record hatch is load-bearing.** `_OUT_OF_RECORD_INSTRUCTION` tells the persona
that declining is a correct answer and that it must not construct a position it did not hold
in order to fill the slot. Without it a persona confabulates to fill the slot, and the
distinction between "X held this" and "a model impersonating X generated this" is lost. The
mechanism that fires it is an empty retrieval: the retriever returns `""` — no claim group
matched the question (`CorpusRetriever._retrieve_claims`), or no note exists
(`StubRetriever`) — and `build_question_prompt` substitutes `NO_RECORD_MARKER`. On the claim
path an empty return now means "this theorist argued nothing relevant" rather than "no
passage shared enough terms" (ADR 0007). Empty retrieval is a feature to be tested, not an
error to be fixed.

**M3 must stay genuinely anonymous.** `synthetic_panel` builds personas with ids prefixed
`synth_`, names of the form "Anonymous theorist 003", and positions drawn from the tag
vocabulary so the synthetic panel spans the same analytical space and stays routable. If the
panel effect survives anonymisation it was the positions; if it does not, some of it was the
model's prior about famous people. That contrast only works if no real name leaks into an M3
prompt.

## The tag vocabulary contract

`schema.TAG_VOCAB` is a closed list of 18 analytical tags shared by both ends of routing: the
Advisor tags each question from it, and every persona is tagged from it.

This is enforced at **load time**, not at route time. `Persona._tags_must_be_in_vocab` raises
on an off-vocabulary tag, because such a tag is not an error that surfaces later — it is a
persona that quietly stops being reachable by tag, arriving only via top-up and contributing
less than the registry implies. A routing bug of exactly that shape once collapsed a
nominally large panel to six actual respondents, which is why this is a hard failure at load.

Question tags are treated more leniently: `AnalyticalQuestion._normalise` lowercases and
strips but keeps off-vocabulary tags, because a model-generated tag that matches nothing is
specified behaviour and stays visible in the routing record.

## Roles and the loop

Twelve call sites, enumerated in `llm.Role`, each stamping a `[[ROLE:...]]` marker into its
own system prompt. The marker is what lets the mock backend route and what lets the
access-matrix tests scan by role.

```
scenario events → WorldLog
  → PerceptionFilter (delay, detection, noise, bias-conditioned degradation)
  → PerceivedEvent[]         ← the only event type an agent ever sees
  → intelligence_officer     → IntelBrief
  → president_query          → PresidentialQuery   [decontextualisation guard runs here]
  → advisor_questions        → AnalyticalQuestion × n_questions
  → advisor_selection        → RoutingRecord per question (roster shown, reasons recorded)
  → theorist × k_per_question → TheoristOpinion + citation verification
  → advisor_synthesis        → AdvisorBrief
  → advisor_coas             → CourseOfAction × 3               (ADR 0006)
  → president_lean           → the secret prior, HOST-ONLY      (ADR 0008)
  [if convene_excomm] → excomm_member × roster × round, president_chair × round
                                                                 (ADR 0008)
  → president_decision       → PresidentialAction (one ActionType, deterministic rung)
  [if audience_enabled] → citizen × audience_size → CitizenResponse (ADR 0009)
```

The bracketed deliberation stage is gated entirely inside the `consult_panel` path (see
`sim.py`'s single arm conditional), never runs on `escalation_prior`, and its transcript —
not the lean above it — is what `president_decision` sees when it runs.

The bracketed audience stage is different in kind: it is a **second, independent**
conditional (`config.audience_enabled`), not nested inside `consult_panel`, because it
reacts to `PresidentialAction` regardless of whether a panel produced it — it runs under
`escalation_prior` too, when turned on. It is the only stage that runs after
`president_decision` and the only one whose output — `RunRecord.audience` — is read by
nothing upstream of it.

Defaults are `n_questions: 3` and `k_per_question: 4`, so up to twelve opinion slots are
drawn from a fifteen-persona panel.

**Question formulation is a first-class component, not glue.** How the President's query is
decomposed determines which theorists are consulted and therefore what the President hears.
It is a separate role with its own model assignment and its output is recorded separately in
`RunRecord.questions`.

**Routing is a modelled decision by default.** `routing_mode: advisor` shows the Advisor the
roster and asks it to pick, recording its stated rationale — this is the actual social act of
deciding whom to consult, so the reason is data. `routing_mode: tag` is the deterministic,
model-free alternative and exists as the `tag_routing` arm. `RoutingRecord` keeps
`matched_by_tag`, `chosen_by_advisor` and `topped_up` in separate fields so a panel reached
mostly by top-up — nobody judged those personas relevant — is visible in the record rather
than inferred. Ids the Advisor names that were not on the roster land in `hallucinated`,
dropped rather than honoured; the rate is a finding about how reliably a model routes.

**The ExComm deliberation is a second panel, not the theorist panel again (ADR 0008).**
Where the theorist panel is decontextualised and independent by construction, the ExComm is
briefed on the (anonymised) situation and debates it in the open — the two panels sit on
opposite sides of the access matrix on purpose, and `docs/framework/access-matrix.md` argues
why that is not a contradiction. Before it convenes, the President's prior over the three
courses is recorded and then withheld from the simulation entirely, including its own later
decision prompt — `RunRecord.secret_lean` is host-only in exactly the sense
`host_ground_truth` is. The measurable this produces is `rung(action) - rung(secret_lean)`
per replication, read as `excomm_debate`'s mean shift against `baseline`'s no-debate noise
floor — see `docs/framework/measurement.md`.

## Type-level enforcement of the host boundary

`WorldEvent` carries `ground_truth_detail`. `PerceivedEvent` — the only event type any agent
sees — has no such field. Leaking the host's truth into a prompt therefore requires changing
a class, not forgetting a `del`.

That instinct recurs. `retrieval.Retriever.grounded` is a property of the retriever rather
than a flag the caller sets, so `RunRecord.grounded` comes from the object that actually
produced the text and a config cannot claim grounding it did not perform. `RunRecord.models`
records which model actually served each role, taken from the backend that served it rather
than the config that requested it: a single `backend` string was adequate while one backend
served every role, and becomes a lie the moment different models serve different roles.

## Misperception

`world.PerceptionFilter` is the only place misperception is modelled, parameterised by
`delay_steps`, detection probability, `noise_prob` and a bias string. A nation always sees
its own actions; foreign events can be delayed, missed entirely, or arrive degraded with part
of the observable signature stripped, conditioned on what the service is looking for.

In phase 1, with one nation and one event, this mostly degrades the host event. It becomes
load-bearing in phase 2. It is built now because retrofitting perception into a loop that
assumed ground truth is far more invasive than carrying it from the start — and because the
Jervis strand of the panel would say misperception is the mechanism that matters most.

## Arms are configs, not branches

`configs/base.yaml` holds defaults; each arm overlays it and should differ in as few fields
as possible, so "baseline vs X" isolates exactly the field X varies. The loader rejects
unknown keys, so a typo fails loudly instead of silently running the default.

`sim.py` contains exactly one conditional gating whether the advisory apparatus runs at
all — `config.consult_panel`, the structural difference between the control arm and
everything else. A new arm needing a new branch there is a signal that the thing being
varied belongs in `RunConfig`. The citizen audience (ADR 0009) is the one deliberate
exception: `config.audience_enabled` is a second, *independent* top-level conditional,
because it must react to the decision whether or not a panel was consulted — it is not
nested inside `consult_panel` the way the ExComm deliberation (ADR 0008) is, and both
conditionals' occurrence counts are pinned by dedicated tests so neither grows a third.

| Arm | Varies | Question |
|---|---|---|
| `escalation_prior` | `consult_panel: false` | What does the President do with no advisory apparatus? **The control.** |
| `baseline` | nothing | Reference configuration. |
| `m1_ungrounded` | `persona_method: m1` | Does grounding change decisions or only prose? |
| `synth_only` | `panel_source: synthetic`, `persona_method: m3` | Positions, or celebrity? |
| `small_panel` | `panel_size: 4` | What does panel size buy? |
| `consensus_only` | `synthesis_mode: consensus_only` | What does suppressing minority views cost? |
| `tag_routing` | `routing_mode: tag` | Does a model-selected panel differ from a deterministic one? |
| `full_stack_variance` | `cache_enabled: false` | Whole-system rather than decision-step variance. |
| `loo_<theorist>` × 15 | `excluded_personas: [x]` | Forced exclusion, per theorist. |

The `loo_*` arms are why influence estimates here can be causal rather than observational.
Exclusion happens in `build_panel`, before anything sees the registry, so an excluded persona
is absent from the panel, from every roster the Advisor is shown, and from every prompt — the
world operates as though they never existed. Filtering later, at routing say, would leave
them visible to the Advisor as someone it declined to pick, which is a different
intervention entirely.

## Caching is an experimental choice

Theorist questions are decontextualised, so their answers are identical across replications
of an arm and cache well. With `cache_enabled: true`, measured variance is **variance in the
decision step given fixed advisory input**. With it false, it is whole-system variance. Both
are legitimate and they answer different questions; `full_stack_variance` runs the second.
`cache_enabled` is recorded in every output record so the two can never be confused after the
fact.

The presidential decision is never cached. Caching it would collapse the Monte Carlo
distribution to a point mass, and it *is* the primary metric.

## Model assignment

`configs/base.yaml` assigns a model per role by measured cost share: the presidential
decision (~45% of billable input, never cached) and the low-volume upstream roles get the
strongest model; theorist calls (~38% of calls but caching down to ~22% of tokens) get the
cheapest. `models_override` forces every role onto one model for wiring smoke tests and is
marked loudly, because a run under it measures something different from a run without it — it
is not a cheaper version of the same experiment.

## Why no orchestration framework

The control flow is fan-out, gather, decide. What the project needs is full replay
auditability: every prompt, seed, retrieval id and model version recoverable from an output
record. A framework makes that harder rather than easier, and its internal prompt handling
would sit inside the access matrix without being tested. `sim.py` is explicit and boring on
purpose.

## Roadmap

**Phase 1 (current).** One nation, one injected event, one closed loop, Monte Carlo over
seeds. Corpus retrieval is in place: every persona retrieves from a committed claim index
over project-written summaries of its publications (ADR 0007). A deliberative ExComm can sit
between the courses of action and the decision, with the President's prior recorded before
it convenes (ADR 0008). A stratified 1962-US-public audience can react to the decision
after it is made, as an outcome measure with its own delta against the control (ADR 0009).
What remains is calibrating the claim-match thresholds against a live sweep, reconciling
`RUNG` with a published ladder, reasoning-theme coding, and — for the ExComm specifically —
a corpus deep enough for a disposition-ablation arm and President-driven turn-taking rather
than round-robin; for the audience, calibrating `strata.yaml`'s marginals against primary
Census/Gallup/SRC-NES tables and a joint (correlated) construction in place of the
independent-draw-plus-raking sampler — see `docs/prompts/improvements-log.md`.

**Phase 2.** Multiple nations signalling, asymmetric perception filters, reciprocity and
arms-race metrics measured against the phase 1 single-nation baseline.

**Phase 3.** Comparative periods: restrict the panel by `era`, hold scenario and seeds fixed.
Corpus swap is a clean manipulation on the population of interest and is the most defensible
experiment in the design. Watch for parametric leakage — the base model has read every era,
so period-restricted personas must be probed with post-cutoff concepts to measure how often
they answer anyway.