"""Derived views over run records: everything a client needs computed, computed here.

Pure functions. No model calls, no I/O beyond the records handed in. This module exists
because the alternative — deriving these in TypeScript — puts the selection rule for the
representative run, the loop-step ordering and the graph construction outside anything
`pytest` can reach. `CLAUDE.md` is explicit that a derivation a UI needs belongs in a
module a test can see.

Four things here are load-bearing.

**The representative run is selected by a stated rule, not by a heuristic.** A record
picked by an unexplained rule will be read as typical when it is not, so
`representative_run` returns a `selection_note` that the UI must display alongside it. It
is an illustrative single run and never a result: the distribution is the result.

**Loop steps are logical, not wall-clock.** `llm.CallRecord` carries no timestamp and the
call log is never persisted (invariant 10), so there is no timing to render and a Gantt
over wall-clock would have to invent one. Step indices are deterministic, reproducible from
config plus seed, and free of API latency that means nothing about the simulation. The
x-axis is "Loop step" and never "Time".

**The full panel is recovered, not stored.** `RunRecord` records who was *consulted*, not
who was *available*, but the panel is derivable two ways — `RoutingRecord.roster` is
exactly who the Advisor was offered, and `sim.build_panel` replays deterministically from
config plus seed. Recovering it is what lets unconsulted personas be rendered greyed rather
than silently absent, which is the difference between "nobody asked them" and "they were
not there".

**Nothing here computes influence.** `engagement_stats` is descriptive: who was consulted,
who declined, how confident they said they were. Attribution is cross-arm and comes from
the `loo_*` forced-exclusion arms; the observational version — comparing runs where a
persona happened to be routed in against runs where it was not — is confounded and is not
computed anywhere in this codebase.
"""

from __future__ import annotations

import random
import statistics
from collections import Counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artsoc.schema import NUCLEAR_THRESHOLD, RunRecord, rung_for

#: Node id for the host-side world. Not an agent: it is where events come from and where
#: the President's action lands.
WORLD = "world"

#: Node id for hallucinated routing targets — ids the Advisor named that were not on the
#: roster. Surfaced as its own node rather than hidden in a tooltip, because the rate is a
#: finding about how reliably a model routes.
PHANTOM = "hallucinated"

#: The three instrument roles, in loop order. The population being modelled is the
#: theorists; these aggregate and act on the panel's opinions and are not samples of
#: anything (`docs/framework/design.md`).
INSTRUMENTS: tuple[str, ...] = ("intelligence_officer", "president", "advisor")


class _View(BaseModel):
    """Base for every derived view. Frozen, because a view is a projection of a record.

    Unknown fields are permitted nowhere: these models are the contract the generated
    TypeScript is built from, so a field that exists in one and not the other has to be a
    build error rather than a blank panel.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# Panel recovery
# ---------------------------------------------------------------------------


def panel_for(record: RunRecord) -> list[str]:
    """Every persona this replication could have consulted, consulted or not.

    Two sources, tried in order, because they fail in different circumstances:

    * `RoutingRecord.roster` is who the Advisor was actually shown. Populated under
      `routing_mode: advisor` — the default — and authoritative when present, because it is
      what the run recorded rather than what a replay reconstructs.
    * Otherwise the panel is replayed. `sim.run_once` seeds one rng with the run seed and
      `build_panel` is its first consumer, so `build_panel(config, Random(seed))` returns
      the same personas the run drew. The replay reads the registry as it stands now, so it
      is only exact while the registry is unchanged — hence the preference for the roster.

    Returns `[]` for the control arm, which builds no panel at all.
    """
    roster: set[str] = set()
    for routing in record.routing:
        roster.update(routing.roster)
    if roster:
        return sorted(roster)

    if not record.config.get("consult_panel", True):
        return []

    # Imported here rather than at module scope: `sim` imports `agents`, which imports
    # `llm`, and a client deriving views has no business pulling a backend into the process.
    from artsoc.config import RunConfig
    from artsoc.sim import build_panel

    try:
        config = RunConfig.model_validate(record.config)
        return sorted(p.persona_id for p in build_panel(config, random.Random(record.seed)))
    except Exception:  # noqa: BLE001 - a replay that cannot run is not a reason to fail
        # Fall back to who spoke. Under-reporting the panel greys fewer personas than it
        # should, which is a worse picture but not a wrong one; raising here would take a
        # whole run detail view down because a registry entry moved.
        return sorted(record.personas_consulted)


def _persona_names(record: RunRecord) -> dict[str, str]:
    """Display names for panel members, from whoever actually spoke.

    Only opinions carry a name. A persona that never spoke is shown by id, which is honest:
    the record does not say what it was called.
    """
    return {o.persona_id: o.persona_name for o in record.opinions}


# ---------------------------------------------------------------------------
# Representative run selection
# ---------------------------------------------------------------------------


class RepresentativeRun(_View):
    """One record chosen to illustrate an arm, plus the rule that chose it.

    **Not a result.** One replication reaching a nuclear rung is an anecdote; the
    distribution over replications is the finding. `selection_note` exists so a viewer can
    see why this record and not another, and must be rendered with it.
    """

    record: RunRecord
    selection_note: str
    median_rung: float
    n_candidates: int
    n_records: int


def _z(value: float, mean: float, stdev: float) -> float:
    """Z-score with a zero-variance guard.

    When every candidate has the same opinion count the dimension carries no information,
    so it contributes nothing rather than dividing by zero.
    """
    return 0.0 if stdev == 0 else (value - mean) / stdev


def representative_run(records: list[RunRecord]) -> RepresentativeRun:
    """The record that best illustrates an arm, selected deterministically.

    "The most average run" has no meaning over records — there is no average of a
    justification — so an actual record is selected rather than a synthetic one built:

    1. The median terminal rung across the arm.
    2. Candidates are the records whose `rung` equals it.
    3. Among candidates, the one minimising Euclidean distance to the *arm* mean of
       `(number of opinions, number of out-of-record opinions)`, on z-scored values so a
       count that ranges over 12 does not swamp one that ranges over 3.
    4. Ties break on lowest seed, so the choice is stable across calls and across machines.

    The arm mean is deliberately taken over every record, not over the candidates: the point
    is a record typical of the arm, and restricting the reference to the candidates would
    make it typical only of the median rung.
    """
    if not records:
        raise ValueError("representative_run needs at least one record")

    arms = {r.arm for r in records}
    if len(arms) != 1:
        raise ValueError(f"representative_run expects one arm, got {sorted(arms)}")

    rungs = [r.rung for r in records]
    median = statistics.median(rungs)
    candidates = [r for r in records if r.rung == median] or list(records)

    opinion_counts = [len(r.opinions) for r in records]
    decline_counts = [sum(1 for o in r.opinions if o.out_of_record) for r in records]

    mean_opinions = statistics.fmean(opinion_counts)
    mean_declines = statistics.fmean(decline_counts)
    sd_opinions = statistics.pstdev(opinion_counts)
    sd_declines = statistics.pstdev(decline_counts)

    def distance(record: RunRecord) -> tuple[float, int]:
        opinions = len(record.opinions)
        declines = sum(1 for o in record.opinions if o.out_of_record)
        do = _z(opinions, mean_opinions, sd_opinions)
        dd = _z(declines, mean_declines, sd_declines)
        return ((do**2 + dd**2) ** 0.5, record.seed)

    chosen = min(candidates, key=distance)

    note = (
        f"Illustrative single run, not a result. Selected from {len(records)} replications "
        f"of {chosen.arm}: median terminal rung is {median:g}, "
        f"{len(candidates)} replication(s) landed there, and seed {chosen.seed} is the one "
        f"closest to the arm mean of {mean_opinions:.1f} opinions and "
        f"{mean_declines:.1f} out-of-record declines (ties broken by lowest seed). "
        "The distribution over all replications is the finding; this transcript is an "
        "anecdote."
    )

    return RepresentativeRun(
        record=chosen,
        selection_note=note,
        median_rung=median,
        n_candidates=len(candidates),
        n_records=len(records),
    )


# ---------------------------------------------------------------------------
# Loop steps
# ---------------------------------------------------------------------------


class LoopStep(_View):
    """One logical step of the orchestration loop.

    `index` is a position in the loop, not a time. Nothing in `RunRecord` carries a
    timestamp and nothing should: per-call timing would mean persisting `call_log`, which
    holds every system and user prompt and is precisely what the access-matrix tests scan
    (invariant 10).
    """

    index: int
    #: The `llm.Role` that made the call, or None for steps no model performed — world
    #: perception, and the President's action landing back in the world.
    role: str | None
    actor: str
    recipient: str
    #: perception | brief | query | formulate | select | consult | opine | decline |
    #: synthesise | decide
    kind: str
    label: str
    #: A path into the record the client dereferences, e.g. "opinions[5]". The payload is
    #: not duplicated here: one copy in the record means the event log and the panels
    #: cannot disagree about what was said.
    payload_ref: str
    #: The opening of what this step produced, for a caption drawn over the node or edge it
    #: belongs to. A truncation of the record's own text, never a paraphrase: a caption that
    #: summarised would be a second account of what was said, sitting beside the first.
    #: Empty where a step produced no text of its own — a consultation is the question being
    #: put, and the answer is the step after it.
    excerpt: str = ""
    question_id: str | None = None
    persona_id: str | None = None


#: How much of a payload a caption carries. Long enough to tell two deliberations apart at a
#: glance, short enough that the graph stays a graph rather than becoming the event log.
EXCERPT_CHARS = 180


def _clip(text: str, limit: int = EXCERPT_CHARS) -> str:
    """The opening of a passage, cut on a word boundary. Never a summary."""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: flat.rfind(" ", 0, limit)].rstrip(",;:.") + "…"


def loop_steps(record: RunRecord) -> list[LoopStep]:
    """The loop as an ordered sequence, derived from record structure alone.

    Deterministic: the same record always produces the same steps in the same order. Order
    within a question follows `routing[i].selected`, which is
    `matched_by_tag + chosen_by_advisor + topped_up`, and opinions are matched to
    consultations on `(question_id, persona_id)`.

    A consultation with no matching opinion still emits its `consult` step and no `opine`
    step. That happens when a replication failed part-way or a persona id was recorded but
    never answered, and inventing the missing half would hide it.
    """
    steps: list[LoopStep] = []
    questions = {q.question_id: q.text for q in record.questions}

    def add(**kwargs: Any) -> None:
        steps.append(LoopStep(index=len(steps), **kwargs))

    for i, event in enumerate(record.view):
        add(
            role=None,
            actor=WORLD,
            recipient="intelligence_officer",
            kind="perception",
            label=f"Collection registers {event.event_id}"
            + (" (degraded)" if event.degraded else ""),
            payload_ref=f"view[{i}]",
            excerpt=_clip(event.description),
        )

    add(
        role="intelligence_officer",
        actor="intelligence_officer",
        recipient="president",
        kind="brief",
        label=f"Intelligence brief, confidence {record.intel_brief.confidence}",
        payload_ref="intel_brief",
        excerpt=_clip(record.intel_brief.summary),
    )

    if record.presidential_query is not None:
        add(
            role="president_query",
            actor="president",
            recipient="advisor",
            kind="query",
            label="President puts a decontextualised question to the Advisor",
            payload_ref="presidential_query",
            excerpt=_clip(record.presidential_query.text),
        )

    for i, question in enumerate(record.questions):
        add(
            role="advisor_questions",
            actor="advisor",
            recipient="advisor",
            kind="formulate",
            label=f"Advisor formulates {question.question_id}",
            payload_ref=f"questions[{i}]",
            excerpt=_clip(question.text),
            question_id=question.question_id,
        )

    # Opinions are indexed by (question, persona) so a consultation can point at the answer
    # it produced without either side having to store the other.
    opinion_index = {
        (o.question_id, o.persona_id): i for i, o in enumerate(record.opinions)
    }

    for i, routing in enumerate(record.routing):
        add(
            role="advisor_selection",
            actor="advisor",
            recipient="advisor",
            kind="select",
            label=f"Advisor selects {len(routing.selected)} for {routing.question_id}",
            payload_ref=f"routing[{i}]",
            # The Advisor's stated reason for whom it picked. Empty under `tag` routing,
            # where the selection is mechanical and nobody reasoned.
            excerpt=_clip(routing.rationale),
            question_id=routing.question_id,
        )
        for persona_id in routing.selected:
            add(
                role="theorist",
                actor="advisor",
                recipient=persona_id,
                kind="consult",
                label=f"Advisor consults {persona_id} on {routing.question_id}",
                payload_ref=f"routing[{i}]",
                # The question being put, not the answer: the answer is the next step, and
                # showing it here would put the reply before the asking.
                excerpt=_clip(questions.get(routing.question_id, "")),
                question_id=routing.question_id,
                persona_id=persona_id,
            )
            key = (routing.question_id, persona_id)
            if key not in opinion_index:
                continue
            j = opinion_index[key]
            opinion = record.opinions[j]
            declined = opinion.out_of_record
            add(
                role="theorist",
                actor=persona_id,
                recipient="advisor",
                kind="decline" if declined else "opine",
                label=(
                    f"{opinion.persona_name} declines: outside their record"
                    if declined
                    else f"{opinion.persona_name} states a position "
                    f"({opinion.basis}, confidence {opinion.confidence:g})"
                ),
                payload_ref=f"opinions[{j}]",
                # A decline states no position, so the reasoning is what it actually said.
                excerpt=_clip(opinion.position or opinion.reasoning),
                question_id=routing.question_id,
                persona_id=persona_id,
            )

    if record.advisor_brief is not None:
        brief = record.advisor_brief
        add(
            role="advisor_synthesis",
            actor="advisor",
            recipient="president",
            kind="synthesise",
            label=(
                f"Advisor compresses {brief.n_opinions} opinions "
                f"({brief.synthesis_mode})"
            ),
            payload_ref="advisor_brief",
            excerpt=_clip(brief.summary),
        )

    add(
        role="president_decision",
        actor="president",
        recipient=WORLD,
        kind="decide",
        label=f"President selects {record.action.action.value} (rung {record.rung})",
        payload_ref="action",
        # Labelled elsewhere as the reason given, never the reason it happened: the
        # justification is recorded alongside the action and never fed the rung.
        excerpt=_clip(record.action.justification),
    )

    return steps


# ---------------------------------------------------------------------------
# Interaction graph
# ---------------------------------------------------------------------------


class GraphNode(_View):
    """One participant in a replication.

    `state` distinguishes four different things that all look like "not much happened":

    * `active` — produced a position.
    * `declined` — answered `out_of_record`. Declining is a substantive act and the escape
      hatch firing is the honest outcome, so it is not styled as absence.
    * `unconsulted` — on the panel, never asked. The unused population stays visible.
    * `excluded` — removed by intervention in a `loo_*` arm. The world operated as though
      they never existed, which is a different fact from nobody choosing them.
    """

    id: str
    label: str
    #: world | instrument | persona | phantom
    kind: str
    state: str
    n_opinions: int = 0
    n_declines: int = 0
    mean_confidence: float | None = None


class GraphEdge(_View):
    """One communication between two participants.

    Typed by `kind` so consultations, opinions, declines and the final decision can be
    styled apart. `weight` is the number of communications of that kind between the pair,
    for a graph where the Advisor talks to one persona three times.
    """

    source: str
    target: str
    #: perception | brief | query | consult | opine | decline | synthesise | decide |
    #: hallucinated
    kind: str
    #: The step at which this pair first communicated this way, so playback can reveal
    #: edges in loop order.
    step_index: int
    #: Every step this edge covers, ascending. The Advisor consults twelve personas one at a
    #: time; collapsing those into a single first index made playback reveal the edge once
    #: and then sit still, so a viewer stepping through could not tell one deliberation from
    #: the next. Each is its own moment, and this is what says which.
    step_indices: list[int] = Field(default_factory=list)
    weight: int = 1


class InteractionGraph(_View):
    """Who spoke to whom in one replication, with the unused population present."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    #: Ids the Advisor named that were not on the roster. Dropped by `agents.Advisor.select`
    #: and reported here: the rate is a finding about how reliably a model routes, and
    #: hiding it in a tooltip buries it.
    hallucinated_ids: list[str] = Field(default_factory=list)


def interaction_graph(record: RunRecord) -> InteractionGraph:
    """Nodes for the whole panel — not just the consulted part — and typed edges.

    Building nodes from `personas_consulted` would make an unconsulted persona
    indistinguishable from one who was never on the panel, which is exactly the distinction
    the graph exists to show.
    """
    steps = loop_steps(record)
    names = _persona_names(record)
    panel = panel_for(record)
    consulted = set(record.personas_consulted)
    excluded = list(record.config.get("excluded_personas") or [])

    by_persona: dict[str, list[Any]] = {}
    for opinion in record.opinions:
        by_persona.setdefault(opinion.persona_id, []).append(opinion)

    nodes: list[GraphNode] = [
        GraphNode(id=WORLD, label="World", kind="world", state="active")
    ]
    for role in INSTRUMENTS:
        active = any(s.actor == role or s.recipient == role for s in steps)
        nodes.append(
            GraphNode(
                id=role,
                label=role.replace("_", " ").title(),
                kind="instrument",
                state="active" if active else "unconsulted",
            )
        )

    for persona_id in panel:
        opinions = by_persona.get(persona_id, [])
        declines = sum(1 for o in opinions if o.out_of_record)
        stated = [o for o in opinions if not o.out_of_record]
        if persona_id not in consulted:
            state = "unconsulted"
        elif stated:
            state = "active"
        else:
            state = "declined"
        nodes.append(
            GraphNode(
                id=persona_id,
                label=names.get(persona_id, persona_id),
                kind="persona",
                state=state,
                n_opinions=len(stated),
                n_declines=declines,
                mean_confidence=(
                    round(statistics.fmean(o.confidence for o in stated), 3)
                    if stated
                    else None
                ),
            )
        )

    # An excluded persona is absent from the panel by construction — that is what exclusion
    # means — so it is added back here purely so the graph can show the intervention.
    for persona_id in excluded:
        nodes.append(
            GraphNode(id=persona_id, label=persona_id, kind="persona", state="excluded")
        )

    hallucinated = sorted({h for r in record.routing for h in r.hallucinated})
    if hallucinated:
        nodes.append(
            GraphNode(
                id=PHANTOM,
                label="off-roster ids",
                kind="phantom",
                state="declined",
            )
        )

    # One edge per (source, target, kind), carrying every step it covers. The pair is what
    # gets drawn; the step list is what lets playback reveal each deliberation separately
    # rather than lighting the whole edge at its first occurrence.
    tallies: dict[tuple[str, str, str], list[int]] = {}
    for step in steps:
        tallies.setdefault((step.actor, step.recipient, step.kind), []).append(step.index)

    edges = [
        GraphEdge(
            source=s,
            target=t,
            kind=k,
            step_index=indices[0],
            step_indices=indices,
            weight=len(indices),
        )
        for (s, t, k), indices in tallies.items()
    ]

    last_step = steps[-1].index if steps else 0
    edges += [
        GraphEdge(
            source="advisor",
            target=PHANTOM,
            kind="hallucinated",
            step_index=last_step,
            # Not a loop step: ids the Advisor named that were dropped never became a
            # communication with anyone. Revealed once the run has finished playing.
            step_indices=[last_step],
            weight=len(hallucinated),
        )
    ] if hallucinated else []

    edges.sort(key=lambda e: (e.step_index, e.source, e.target, e.kind))
    return InteractionGraph(nodes=nodes, edges=edges, hallucinated_ids=hallucinated)


# ---------------------------------------------------------------------------
# Engagement statistics
# ---------------------------------------------------------------------------


class PersonaEngagement(_View):
    """What one persona did across an arm. Descriptive only.

    **No influence language belongs in this model.** How often a persona was consulted says
    nothing about what its presence changed: routing correlates with question tags, which
    correlate with outcome. Attribution comes from the `loo_*` forced-exclusion arms and is
    a contrast between arms, not a column in this table.
    """

    persona_id: str
    name: str
    #: Replications in which this persona was on the panel at all. The denominator for
    #: everything else — a persona sampled into half the panels cannot be compared against
    #: one always present without it.
    in_panel_runs: int
    times_consulted: int
    matched_by_tag: int
    chosen_by_advisor: int
    topped_up: int
    n_opinions: int
    n_declines: int
    decline_rate: float
    mean_confidence: float | None
    n_citations: int
    #: Cited passage ids absent from the block this persona was shown, attributed by the
    #: `persona:source:digits` prefix (ADR 0003). Ids with no recognisable prefix cannot be
    #: attributed to anyone and are reported on the arm instead — see `EngagementSummary`.
    n_unsupported: int
    basis_counts: dict[str, int] = Field(default_factory=dict)


class EngagementSummary(_View):
    """Per-persona engagement across an arm, plus what could not be attributed."""

    arm: str
    n_records: int
    personas: list[PersonaEngagement]
    #: Unsupported citations whose id carried no known persona prefix. Reported rather than
    #: distributed: a hallucinated citation is a finding about the method, and spreading it
    #: across personas that may not have made it would be inventing data.
    unattributed_unsupported: int
    note: str = (
        "Descriptive engagement only. Consultation counts are not influence: routing "
        "correlates with question tags, which correlate with outcome. Causal attribution "
        "comes from the loo_* forced-exclusion arms."
    )


def engagement_stats(records: list[RunRecord]) -> EngagementSummary:
    """Per-persona descriptive statistics across one arm."""
    if not records:
        raise ValueError("engagement_stats needs at least one record")
    arms = {r.arm for r in records}
    if len(arms) != 1:
        raise ValueError(f"engagement_stats expects one arm, got {sorted(arms)}")

    names: dict[str, str] = {}
    in_panel: Counter[str] = Counter()
    consulted: Counter[str] = Counter()
    tagged: Counter[str] = Counter()
    chosen: Counter[str] = Counter()
    topped: Counter[str] = Counter()
    opinions: dict[str, list[Any]] = {}
    unsupported: Counter[str] = Counter()
    unattributed = 0

    known: set[str] = set()
    for record in records:
        panel = panel_for(record)
        known.update(panel)
        in_panel.update(panel)
        for routing in record.routing:
            consulted.update(routing.selected)
            tagged.update(routing.matched_by_tag)
            chosen.update(routing.chosen_by_advisor)
            topped.update(routing.topped_up)
        for opinion in record.opinions:
            names.setdefault(opinion.persona_id, opinion.persona_name)
            opinions.setdefault(opinion.persona_id, []).append(opinion)

    for record in records:
        for citation in record.unsupported_citations:
            # Passage ids are persona:source:digits, so a hallucinated id often still names
            # whose store it claimed to come from. One that does not is nobody's.
            prefix = citation.split(":", 1)[0]
            if prefix in known:
                unsupported[prefix] += 1
            else:
                unattributed += 1

    people: list[PersonaEngagement] = []
    for persona_id in sorted(known):
        mine = opinions.get(persona_id, [])
        declines = sum(1 for o in mine if o.out_of_record)
        stated = [o for o in mine if not o.out_of_record]
        people.append(
            PersonaEngagement(
                persona_id=persona_id,
                name=names.get(persona_id, persona_id),
                in_panel_runs=in_panel[persona_id],
                times_consulted=consulted[persona_id],
                matched_by_tag=tagged[persona_id],
                chosen_by_advisor=chosen[persona_id],
                topped_up=topped[persona_id],
                n_opinions=len(mine),
                n_declines=declines,
                decline_rate=round(declines / len(mine), 4) if mine else 0.0,
                mean_confidence=(
                    round(statistics.fmean(o.confidence for o in stated), 3)
                    if stated
                    else None
                ),
                n_citations=sum(len(o.citations) for o in mine),
                n_unsupported=unsupported[persona_id],
                basis_counts=dict(Counter(o.basis for o in mine)),
            )
        )

    return EngagementSummary(
        arm=records[0].arm,
        n_records=len(records),
        personas=people,
        unattributed_unsupported=unattributed,
    )


# ---------------------------------------------------------------------------
# Pipeline flow
# ---------------------------------------------------------------------------


class FlowNode(_View):
    id: str
    label: str
    stage: int
    count: int


class FlowLink(_View):
    source: str
    target: str
    count: int


class PipelineFlow(_View):
    """Replication counts flowing through the loop to each terminal rung.

    **This is not an escalation path.** Phase 1 produces exactly one `PresidentialAction`
    per replication and `RunRecord.rung` is a single terminal value; there is no sequence of
    rungs, because the loop is one event and one decision. Multi-step escalation arrives in
    phase 2, when Presidents signal to each other. What this shows is what varied *upstream*
    of each terminal rung, which is the honest version of the same affordance.

    The middle stage is the panel's basis mix rather than the synthesis mode the original
    spec suggested. `synthesis_mode` is set by config, so within one arm it is one value and
    the stage would carry no information. Basis mix varies per replication and is the ADR
    0004 diagnostic: whether stated positions rested on retrieved sources or on the belief
    store.
    """

    arm: str
    n_records: int
    nodes: list[FlowNode]
    links: list[FlowLink]
    label: str = "Pipeline flow to terminal rung"


def _confidence_band(raw: str) -> str:
    """Normalise the Intelligence Officer's stated confidence into a band.

    The prompt asks for a word and `IntelBrief.confidence` coerces whatever came back to a
    string, so a live model may have answered "0.7" or "moderate-to-high". Anything that
    does not reduce to one of the three bands is kept as `other` rather than forced, so an
    off-spec answer stays visible instead of being quietly binned.
    """
    text = raw.strip().lower()
    for band in ("low", "moderate", "medium", "high"):
        if band in text:
            return "moderate" if band == "medium" else band
    try:
        value = float(text)
    except ValueError:
        return "other"
    if value < 0.4:
        return "low"
    return "moderate" if value < 0.7 else "high"


def _basis_mix(record: RunRecord) -> str:
    """How this replication's panel answered: from sources, from belief, or not at all."""
    if not record.opinions:
        return "no panel"
    declined = sum(1 for o in record.opinions if o.out_of_record)
    if declined / len(record.opinions) >= 0.5:
        return "mostly declined"
    stated = [o for o in record.opinions if not o.out_of_record]
    sources = sum(1 for o in stated if o.basis == "sources")
    return "sources-led" if sources >= len(stated) / 2 else "belief-led"


def pipeline_flow(records: list[RunRecord]) -> PipelineFlow:
    """Replication counts from intel confidence, through basis mix, to terminal rung."""
    if not records:
        raise ValueError("pipeline_flow needs at least one record")
    arms = {r.arm for r in records}
    if len(arms) != 1:
        raise ValueError(f"pipeline_flow expects one arm, got {sorted(arms)}")

    first_links: Counter[tuple[str, str]] = Counter()
    second_links: Counter[tuple[str, str]] = Counter()
    stage0: Counter[str] = Counter()
    stage1: Counter[str] = Counter()
    stage2: Counter[str] = Counter()

    for record in records:
        band = f"conf:{_confidence_band(record.intel_brief.confidence)}"
        mix = f"basis:{_basis_mix(record)}"
        rung = f"rung:{record.rung}"
        stage0[band] += 1
        stage1[mix] += 1
        stage2[rung] += 1
        first_links[(band, mix)] += 1
        second_links[(mix, rung)] += 1

    def label_for(node_id: str) -> str:
        kind, value = node_id.split(":", 1)
        if kind == "conf":
            return f"intel confidence: {value}"
        if kind == "basis":
            return value
        nuclear = " (nuclear)" if int(value) >= NUCLEAR_THRESHOLD else ""
        return f"rung {value}{nuclear}"

    nodes = (
        [FlowNode(id=i, label=label_for(i), stage=0, count=c) for i, c in sorted(stage0.items())]
        + [FlowNode(id=i, label=label_for(i), stage=1, count=c) for i, c in sorted(stage1.items())]
        + [
            FlowNode(id=i, label=label_for(i), stage=2, count=c)
            for i, c in sorted(stage2.items(), key=lambda kv: int(kv[0].split(":")[1]))
        ]
    )
    links = [
        FlowLink(source=s, target=t, count=c)
        for (s, t), c in sorted({**first_links, **second_links}.items())
    ]

    return PipelineFlow(
        arm=records[0].arm, n_records=len(records), nodes=nodes, links=links
    )


# ---------------------------------------------------------------------------
# Per-agent detail, and the deterministic facts of one run
# ---------------------------------------------------------------------------


class AgentAnswer(_View):
    """One question put to one theorist, and what came back.

    `basis` and `declined` are kept apart because they answer different questions. A
    persona shown belief text that still declined is a different fact from one shown
    nothing at all, and collapsing them would hide which of the two happened.
    """

    question_id: str
    question: str
    #: chosen | topped_up — why this persona was asked at all.
    how_selected: str
    #: The Advisor's stated reason for the selection this answer belongs to. Empty under
    #: `tag` routing, where nobody reasoned.
    selection_rationale: str
    declined: bool
    #: sources | beliefs | none
    basis: str
    position: str
    reasoning: str
    citations: list[str] = Field(default_factory=list)
    confidence: float


class AgentDetail(_View):
    """What one participant did in one replication, and the record's account of why.

    Keyed on the ids `interaction_graph` emits, so a clicked node maps straight to a panel
    without a second lookup that could disagree with the graph.

    The "why" is only ever what the record holds. For a theorist that is its own reasoning,
    the basis it drew on, and the Advisor's rationale for consulting it. For the President
    it is the justification it gave — which `schema.PresidentialAction` documents as
    qualitative data that never fed the rung, so it is labelled as the reason stated rather
    than the reason the action occurred.
    """

    id: str
    label: str
    #: world | instrument | persona
    kind: str
    #: One line naming what this agent did, for the panel header.
    summary: str
    #: Populated for theorists.
    answers: list[AgentAnswer] = Field(default_factory=list)
    #: Free-form key/value detail, ordered for display. Used by the instrument roles, whose
    #: outputs differ too much from one another to share a schema worth the indirection.
    fields: list[tuple[str, str]] = Field(default_factory=list)
    #: Longer blocks shown under the fields: the brief, the query, the justification.
    passages: list[tuple[str, str]] = Field(default_factory=list)


def _selection_index(record: RunRecord) -> dict[tuple[str, str], tuple[str, str]]:
    """(question_id, persona_id) -> (how_selected, rationale), from the routing records."""
    index: dict[tuple[str, str], tuple[str, str]] = {}
    for routing in record.routing:
        chosen = set(routing.matched_by_tag) | set(routing.chosen_by_advisor)
        for persona_id in routing.selected:
            how = "chosen" if persona_id in chosen else "topped_up"
            index[(routing.question_id, persona_id)] = (how, routing.rationale)
    return index


def agent_details(record: RunRecord) -> list[AgentDetail]:
    """One entry per participant in this replication.

    Every node `interaction_graph` draws gets a detail, so no clickable node opens an empty
    panel. An excluded persona has neither, which is the intervention working: the world
    operated as though it never existed.
    """
    names = _persona_names(record)
    questions = {q.question_id: q.text for q in record.questions}
    selection = _selection_index(record)
    details: list[AgentDetail] = []

    detected, missed = len(record.detected_event_ids), len(record.missed_event_ids)
    degraded = sum(1 for event in record.view if event.degraded)
    details.append(
        AgentDetail(
            id=WORLD,
            label="World",
            kind="world",
            summary=f"{len(record.injected_event_ids)} event(s) injected by the host.",
            fields=[("Injected", ", ".join(record.injected_event_ids) or "none")],
        )
    )

    details.append(
        AgentDetail(
            id="intelligence_officer",
            label="Intelligence Officer",
            kind="instrument",
            summary=(
                f"Detected {detected} of {detected + missed} event(s), "
                f"{degraded} under degraded collection; assessed confidence "
                f"{record.intel_brief.confidence}."
            ),
            fields=[
                ("Detected", str(detected)),
                ("Missed", str(missed)),
                ("Degraded", str(degraded)),
                ("Stated confidence", record.intel_brief.confidence),
            ],
            passages=[
                ("Summary", record.intel_brief.summary),
                ("Assessment", record.intel_brief.assessed_activity),
                *[("Alternative", alt) for alt in record.intel_brief.alternative_explanations],
                *[("Collection gap", gap) for gap in record.intel_brief.collection_gaps],
            ],
        )
    )

    brief = record.advisor_brief
    if brief is not None or record.questions:
        rationales = [
            (f"Selection for {r.question_id}", r.rationale) for r in record.routing if r.rationale
        ]
        details.append(
            AgentDetail(
                id="advisor",
                label="Advisor",
                kind="instrument",
                summary=(
                    f"Wrote {len(record.questions)} question(s), consulted "
                    f"{len(record.personas_consulted)} persona(s), and reported "
                    f"{len(brief.consensus_points) if brief else 0} consensus point(s) and "
                    f"{len(brief.minority_positions) if brief else 0} minority position(s)."
                ),
                fields=[
                    ("Synthesis mode", brief.synthesis_mode if brief else "n/a"),
                    ("Opinions received", str(brief.n_opinions if brief else 0)),
                    ("Consensus points", str(len(brief.consensus_points) if brief else 0)),
                    ("Minority positions", str(len(brief.minority_positions) if brief else 0)),
                ],
                passages=[
                    *[("Question", text) for text in questions.values()],
                    *rationales,
                    *([("Brief", brief.summary)] if brief else []),
                    *[("Consensus", p) for p in (brief.consensus_points if brief else [])],
                    *[("Minority", p) for p in (brief.minority_positions if brief else [])],
                ],
            )
        )

    details.append(
        AgentDetail(
            id="president",
            label="President",
            kind="instrument",
            summary=(
                f"Selected {record.action.action.value} (rung {record.rung}) after "
                f"{'an advisory brief' if brief else 'no advisory input'}."
            ),
            fields=[
                ("Action", record.action.action.value),
                ("Rung", str(record.rung)),
                ("Nuclear", "yes" if record.action.is_nuclear else "no"),
            ],
            passages=[
                *(
                    [("Question to the Advisor", record.presidential_query.text)]
                    if record.presidential_query
                    else []
                ),
                # Labelled as the reason given, not the reason it happened. The action is
                # what gets scored; the justification is written alongside it and never
                # feeds the rung (schema.PresidentialAction).
                ("Reason given for the action", record.action.justification),
            ],
        )
    )

    by_persona: dict[str, list[AgentAnswer]] = {}
    for opinion in record.opinions:
        how, rationale = selection.get((opinion.question_id, opinion.persona_id), ("chosen", ""))
        by_persona.setdefault(opinion.persona_id, []).append(
            AgentAnswer(
                question_id=opinion.question_id,
                question=questions.get(opinion.question_id, ""),
                how_selected=how,
                selection_rationale=rationale,
                declined=opinion.out_of_record,
                basis=opinion.basis,
                position=opinion.position,
                reasoning=opinion.reasoning,
                citations=list(opinion.citations),
                confidence=opinion.confidence,
            )
        )

    # The phantom node is drawn whenever the Advisor named an id that was not on the
    # roster, so it needs a panel too — an empty one on a clickable node reads as a bug.
    # The rate is a finding about how reliably a model routes, not an incidental error.
    hallucinated = [pid for routing in record.routing for pid in routing.hallucinated]
    if hallucinated:
        details.append(
            AgentDetail(
                id=PHANTOM,
                label="Named but not on the roster",
                kind="world",
                summary=(
                    f"The Advisor named {len(hallucinated)} id(s) that were not on the "
                    "roster. Each was dropped and the panel topped up instead."
                ),
                fields=[
                    ("Times named", str(len(hallucinated))),
                    ("Distinct ids", str(len(set(hallucinated)))),
                ],
                passages=[("Named", pid) for pid in sorted(set(hallucinated))],
            )
        )

    for persona_id in panel_for(record):
        answers = by_persona.get(persona_id, [])
        declines = sum(1 for a in answers if a.declined)
        if not answers:
            summary = "On the panel; never consulted."
        else:
            bases = sorted({a.basis for a in answers if not a.declined})
            summary = (
                f"Answered {len(answers)} question(s), declined {declines}"
                + (f"; drew on {', '.join(bases)}." if bases else ".")
            )
        details.append(
            AgentDetail(
                id=persona_id,
                label=names.get(persona_id, persona_id),
                kind="persona",
                summary=summary,
                answers=answers,
                fields=[
                    ("Questions asked", str(len(answers))),
                    ("Declined", str(declines)),
                    (
                        "Citations",
                        str(sum(len(a.citations) for a in answers)),
                    ),
                ],
            )
        )
    return details


class RunFacts(_View):
    """The deterministic account of one replication. Every field is read, none inferred.

    This exists so the readable narrative beside it never has to carry a number. A model
    asked to summarise can misstate a count; these cannot, because they are the record.
    """

    action: str
    rung: int
    is_nuclear: bool
    panel_size: int
    personas_consulted: int
    n_opinions: int
    n_declines: int
    #: sources | beliefs | none, over stated positions and declines alike.
    basis_counts: dict[str, int]
    synthesis_mode: str
    n_consensus: int
    n_minority: int
    events_detected: int
    events_missed: int
    events_degraded: int
    intel_confidence: str
    n_citations: int
    n_unsupported_citations: int
    grounded: bool
    retrieval_mode: str


def run_facts(record: RunRecord) -> RunFacts:
    """Reduce one record to the facts a header can state without interpreting anything."""
    brief = record.advisor_brief
    return RunFacts(
        action=record.action.action.value,
        rung=record.rung,
        is_nuclear=record.action.is_nuclear,
        panel_size=record.panel_size,
        personas_consulted=len(record.personas_consulted),
        n_opinions=len(record.opinions),
        n_declines=sum(1 for o in record.opinions if o.out_of_record),
        basis_counts=dict(Counter(o.basis for o in record.opinions)),
        synthesis_mode=brief.synthesis_mode if brief else "none",
        n_consensus=len(brief.consensus_points) if brief else 0,
        n_minority=len(brief.minority_positions) if brief else 0,
        events_detected=len(record.detected_event_ids),
        events_missed=len(record.missed_event_ids),
        events_degraded=sum(1 for event in record.view if event.degraded),
        intel_confidence=record.intel_brief.confidence,
        n_citations=sum(len(o.citations) for o in record.opinions),
        n_unsupported_citations=len(record.unsupported_citations),
        grounded=record.grounded,
        retrieval_mode=record.retrieval_mode,
    )


# ---------------------------------------------------------------------------
# Provenance: what a decision actually rested on.
#
# Every link below comes from an id the record holds. None is inferred from wording. That
# distinction is the whole value of the diagram: a lexical-overlap link between a theorist's
# prose and an advisor's would look identical on screen and mean nothing, and there would be
# no way to tell the two apart afterwards.
# ---------------------------------------------------------------------------


#: How `CourseOfAction.supporting_opinions` names an opinion (ADR 0006).
def opinion_key(question_id: str, persona_id: str) -> str:
    return f"{question_id}:{persona_id}"


class ProvenanceNode(_View):
    """One thing in the chain from source text to decision."""

    id: str
    #: passage | opinion | coa | decision
    kind: str
    label: str
    #: Longer text, where there is any to show. Passage nodes carry none — their text lives
    #: in the corpus and is fetched on demand, because a record stores citation ids rather
    #: than the block a persona was shown.
    detail: str = ""
    #: True for the nodes on the path the President actually took.
    chosen: bool = False
    #: Set on opinion nodes that declined, so the chain shows where the panel had nothing to
    #: offer rather than dropping those nodes and implying it was never asked.
    declined: bool = False
    persona_id: str | None = None
    question_id: str | None = None


class ProvenanceLink(_View):
    source: str
    target: str
    #: cites | supports | selects
    kind: str
    chosen: bool = False


class ProvenanceFlow(_View):
    """Cited passages → theorist positions → proposed courses of action → the decision.

    **Complete only for records written under ADR 0006.** `CourseOfAction.supporting_opinions`
    is what links an option to the opinions it rests on; before that field existed there was
    nothing to draw the middle of this chain from, and inferring it by matching words would
    be fabricating the exact relationship the diagram claims to show. A record without
    courses of action therefore yields the passage→opinion half and says why the rest is
    missing, rather than rendering an empty stage.
    """

    nodes: list[ProvenanceNode]
    links: list[ProvenanceLink]
    #: present | absent — whether this record carries courses of action at all.
    coa_stage: str
    #: Stated when `coa_stage` is "absent", so the gap is explained on screen.
    coa_note: str = ""
    schema_version: str = ""


def provenance_flow(record: RunRecord) -> ProvenanceFlow:
    """The chain from cited source text to the action taken, from recorded ids only."""
    nodes: list[ProvenanceNode] = []
    links: list[ProvenanceLink] = []

    chosen_id = record.action.chosen_coa_id
    supported_by_chosen: set[str] = set()
    for coa in record.courses_of_action:
        if coa.coa_id == chosen_id:
            supported_by_chosen = set(coa.supporting_opinions)

    # Opinions first: they are the hinge. Each is keyed the way a course of action names it,
    # so the two halves of the chain join on an id rather than on a lookup that could differ.
    seen_passages: set[str] = set()
    for opinion in record.opinions:
        key = opinion_key(opinion.question_id, opinion.persona_id)
        on_path = key in supported_by_chosen
        nodes.append(
            ProvenanceNode(
                id=f"opinion:{key}",
                kind="opinion",
                label=opinion.persona_name,
                detail=opinion.position,
                chosen=on_path,
                declined=opinion.out_of_record,
                persona_id=opinion.persona_id,
                question_id=opinion.question_id,
            )
        )
        for citation in opinion.citations:
            if citation not in seen_passages:
                seen_passages.add(citation)
                nodes.append(
                    ProvenanceNode(
                        id=f"passage:{citation}",
                        kind="passage",
                        # The middle segment of a passage id says what kind of source it is
                        # (ADR 0003): wikipedia, abstract or belief.
                        label=citation.split(":")[1] if ":" in citation else citation,
                        persona_id=citation.split(":", 1)[0],
                    )
                )
            links.append(
                ProvenanceLink(
                    source=f"passage:{citation}",
                    target=f"opinion:{key}",
                    kind="cites",
                    chosen=on_path,
                )
            )

    # A passage node is only on the chosen path if something it fed is. Computed after the
    # links rather than during, because one passage can feed several opinions.
    on_path_passages = {link.source for link in links if link.chosen}
    nodes = [
        n.model_copy(update={"chosen": True})
        if n.kind == "passage" and n.id in on_path_passages
        else n
        for n in nodes
    ]

    decision_id = f"decision:{record.action.action.value}"
    for coa in record.courses_of_action:
        on_path = coa.coa_id == chosen_id
        nodes.append(
            ProvenanceNode(
                id=f"coa:{coa.coa_id}",
                kind="coa",
                label=coa.action.value,
                detail=coa.rationale,
                chosen=on_path,
            )
        )
        for key in coa.supporting_opinions:
            # Only draw a link to an opinion that exists. A course of action naming an
            # opinion the record does not hold is a routing failure of the same family as a
            # hallucinated citation; drawing an edge to nothing would hide it.
            if any(n.id == f"opinion:{key}" for n in nodes):
                links.append(
                    ProvenanceLink(
                        source=f"opinion:{key}",
                        target=f"coa:{coa.coa_id}",
                        kind="supports",
                        chosen=on_path,
                    )
                )
        links.append(
            ProvenanceLink(
                source=f"coa:{coa.coa_id}",
                target=decision_id,
                kind="selects",
                chosen=on_path,
            )
        )

    nodes.append(
        ProvenanceNode(
            id=decision_id,
            kind="decision",
            label=record.action.action.value,
            detail=record.action.justification,
            chosen=True,
        )
    )

    absent = not record.courses_of_action
    return ProvenanceFlow(
        nodes=nodes,
        links=links,
        coa_stage="absent" if absent else "present",
        coa_note=(
            "This replication holds no courses of action, so the chain stops at the "
            "opinions. Either it predates ADR 0006, which introduced them, or it is a "
            "control-arm run with no panel to ground an option in. The missing stage is "
            "not drawn rather than inferred: a link between an opinion and an option can "
            "only come from the id the Advisor recorded."
            if absent
            else ""
        ),
        schema_version=record.schema_version,
    )


# ---------------------------------------------------------------------------
# Course-of-action support. What the chosen option rested on — not influence.
# ---------------------------------------------------------------------------


class PersonaCoaSupport(_View):
    """How often one persona's opinions grounded a proposed and a chosen option."""

    persona_id: str
    name: str
    #: Replications in which this persona stated a position or declined.
    runs_answered: int
    #: Times any course of action cited one of this persona's opinions.
    cited_by_any_coa: int
    #: Times the course of action the President actually took cited one of them.
    cited_by_chosen_coa: int
    #: Replications in which the chosen option cited this persona at least once.
    runs_in_chosen: int
    #: `runs_in_chosen` over the replications where a choice among options was made.
    share_of_chosen: float


class CoaSupport(_View):
    """Per-persona grounding of the option the President took.

    **This is not influence and must never be labelled as it.** It says whose opinions the
    Advisor cited when it built the option that was chosen — a recorded fact about the
    document, not a measurement of what anyone changed. A persona could be cited in every
    chosen option and change nothing, or be cited in none and have shifted which options
    were proposed at all.

    Causal attribution comes from the `loo_*` forced-exclusion arms, where the persona is
    absent from the panel, every roster and every prompt, and the world is re-run without
    them. That is a contrast between arms and lives in the influence panel.
    """

    arm: str
    n_records: int
    #: Replications where courses of action were proposed and one was chosen.
    n_with_coas: int
    personas: list[PersonaCoaSupport]
    note: str = (
        "Whose opinions the chosen course of action cited. A recorded property of the "
        "document the Advisor wrote, not a measure of influence: causal attribution comes "
        "from the loo_* forced-exclusion arms."
    )


def coa_support(records: list[RunRecord]) -> CoaSupport:
    """Per-persona counts of grounding a proposed and a chosen course of action."""
    if not records:
        raise ValueError("coa_support needs at least one record")
    arms = {r.arm for r in records}
    if len(arms) != 1:
        raise ValueError(f"coa_support expects one arm, got {sorted(arms)}")

    names: dict[str, str] = {}
    answered: Counter[str] = Counter()
    any_coa: Counter[str] = Counter()
    chosen_coa: Counter[str] = Counter()
    runs_in_chosen: Counter[str] = Counter()
    n_with_coas = 0

    for record in records:
        for opinion in record.opinions:
            names.setdefault(opinion.persona_id, opinion.persona_name)
        answered.update({o.persona_id for o in record.opinions})

        if not record.courses_of_action:
            continue
        n_with_coas += 1

        in_chosen_this_run: set[str] = set()
        for coa in record.courses_of_action:
            is_chosen = coa.coa_id == record.action.chosen_coa_id
            for key in coa.supporting_opinions:
                persona_id = key.split(":", 1)[-1]
                any_coa[persona_id] += 1
                if is_chosen:
                    chosen_coa[persona_id] += 1
                    in_chosen_this_run.add(persona_id)
        runs_in_chosen.update(in_chosen_this_run)

    people = [
        PersonaCoaSupport(
            persona_id=persona_id,
            name=names.get(persona_id, persona_id),
            runs_answered=answered[persona_id],
            cited_by_any_coa=any_coa[persona_id],
            cited_by_chosen_coa=chosen_coa[persona_id],
            runs_in_chosen=runs_in_chosen[persona_id],
            share_of_chosen=(
                round(runs_in_chosen[persona_id] / n_with_coas, 4) if n_with_coas else 0.0
            ),
        )
        for persona_id in sorted(set(names) | set(any_coa))
    ]
    people.sort(key=lambda p: (-p.runs_in_chosen, -p.cited_by_any_coa, p.persona_id))

    return CoaSupport(
        arm=records[0].arm,
        n_records=len(records),
        n_with_coas=n_with_coas,
        personas=people,
    )


# ---------------------------------------------------------------------------
# Session-level facts. The numbers a landing page states, none of them interpreted.
# ---------------------------------------------------------------------------


class ActionCount(_View):
    """One action, how often it was proposed, and how often it was taken."""

    action: str
    rung: int
    is_nuclear: bool
    proposed: int
    chosen: int


class SessionFacts(_View):
    """The deterministic account of a session, for a header to state without interpreting.

    Exists for the same reason `RunFacts` does: the generated prose beside it never has to
    carry a number it could get wrong. Every field is read or arithmetic over what was read.

    `d_mean_rung` and `d_p_nuclear` are `None` when the control arm was not run. That is the
    honest state — absolute rates are not findings, so with no control there is no
    interpretable quantity here at all, and a zero would read as "no difference" rather than
    as "no comparison".
    """

    arm: str
    n: int
    mean_rung: float
    median_rung: float
    p_nuclear: float
    modal_action: str
    modal_action_share: float
    #: None when `escalation_prior` is absent from the session.
    d_mean_rung: float | None = None
    d_p_nuclear: float | None = None
    control_arm: str | None = None

    declared_panel_size: int = 0
    mean_run_coverage: float = 0.0
    out_of_record_rate: float = 0.0
    beliefs_share: float = 0.0

    #: Every action proposed or taken across the sweep, commonest first.
    actions: list[ActionCount] = Field(default_factory=list)
    #: Replications in which the Advisor proposed courses of action.
    n_with_coas: int = 0


def session_facts(
    records: list[RunRecord],
    summary: Any,
    delta: Any | None = None,
) -> SessionFacts:
    """Reduce one arm to the numbers a landing page may state.

    `summary` is a `metrics.ArmSummary` and `delta` a `metrics.Delta`; both are taken as
    arguments rather than recomputed, so this cannot disagree with the report. Typed loosely
    to keep `views` free of a `metrics` import it needs for nothing else.
    """
    if not records:
        raise ValueError("session_facts needs at least one record")

    proposed: Counter[str] = Counter()
    chosen: Counter[str] = Counter()
    n_with_coas = 0
    for record in records:
        chosen[record.action.action.value] += 1
        if record.courses_of_action:
            n_with_coas += 1
            proposed.update(coa.action.value for coa in record.courses_of_action)

    modal_action, modal_count = chosen.most_common(1)[0]
    actions = [
        ActionCount(
            action=action,
            rung=rung_for(action),
            is_nuclear=rung_for(action) >= NUCLEAR_THRESHOLD,
            proposed=proposed.get(action, 0),
            chosen=chosen.get(action, 0),
        )
        for action in sorted(set(proposed) | set(chosen), key=lambda a: -chosen.get(a, 0))
    ]

    return SessionFacts(
        arm=summary.arm,
        n=summary.n,
        mean_rung=summary.mean_rung,
        median_rung=summary.median_rung,
        p_nuclear=summary.p_nuclear,
        modal_action=modal_action,
        modal_action_share=round(modal_count / len(records), 4),
        d_mean_rung=delta.d_mean_rung if delta else None,
        d_p_nuclear=delta.d_p_nuclear if delta else None,
        control_arm=delta.control if delta else None,
        declared_panel_size=summary.declared_panel_size,
        mean_run_coverage=summary.mean_run_coverage,
        out_of_record_rate=summary.out_of_record_rate,
        beliefs_share=summary.beliefs_share,
        actions=actions,
        n_with_coas=n_with_coas,
    )
