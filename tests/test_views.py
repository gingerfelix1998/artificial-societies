"""Derived views: the derivations a client consumes, tested where pytest can reach them.

These exist so the selection rule for the representative run, the loop-step ordering and
the graph construction are not reimplemented untested in TypeScript. Every test here runs
against the mock backend and the stub retriever, so the suite stays offline and free.

Two properties matter more than the rest and are checked repeatedly: the views are
**deterministic** (a client that re-fetches must get the same picture), and the
**unconsulted population stays visible** (a persona nobody asked must be distinguishable
from one who was never there).
"""

from __future__ import annotations

import json
from collections import Counter

import pytest

from artsoc.config import RunConfig, load_arm
from artsoc.llm import MOCK_PREFIX, LLMClient, MockBackend
from artsoc.narrative import INSTRUCTION, build_prompt, summarise_run
from artsoc.schema import (
    ActionType,
    IntelBrief,
    PresidentialAction,
    RoutingRecord,
    RunRecord,
    TheoristOpinion,
)
from artsoc.sim import run_once
from artsoc.views import (
    EXCERPT_CHARS,
    PHANTOM,
    WORLD,
    LoopStep,
    agent_details,
    coa_support,
    engagement_stats,
    interaction_graph,
    loop_steps,
    panel_for,
    pipeline_flow,
    provenance_flow,
    representative_run,
    run_facts,
    session_facts,
)


def _mock(config: RunConfig) -> RunConfig:
    """Pin an arm to the mock backend and the stub corpus.

    Same two overrides as tests/test_invariants.py and for the same reasons: arms may
    declare a live backend for real runs and the suite must never inherit one, and base
    declares `corpus` retrieval which needs `artsoc ingest` to have been run.
    """
    return config.model_copy(update={"backend": "mock", "retrieval_mode": "stub"})


def _run(arm: str, seed: int = 1) -> RunRecord:
    return run_once(_mock(load_arm(arm)), seed, use_disk_cache=False)


def _sweep(arm: str, n: int = 6) -> list[RunRecord]:
    return [_run(arm, seed) for seed in range(1, n + 1)]


@pytest.fixture(scope="module")
def baseline_records() -> list[RunRecord]:
    return _sweep("baseline", 8)


@pytest.fixture(scope="module")
def baseline_record(baseline_records: list[RunRecord]) -> RunRecord:
    return baseline_records[0]


# ---------------------------------------------------------------------------
# Panel recovery. The unused population is the point: a persona nobody consulted must be
# distinguishable from one who was never on the panel.
# ---------------------------------------------------------------------------


def test_the_panel_includes_personas_who_were_never_consulted(
    baseline_record: RunRecord,
) -> None:
    """Otherwise 'nobody asked them' and 'they were not there' render identically."""
    panel = panel_for(baseline_record)
    consulted = set(baseline_record.personas_consulted)
    assert consulted <= set(panel)
    assert len(panel) == baseline_record.panel_size
    assert set(panel) - consulted, "this fixture is only useful if someone went unconsulted"


def test_the_panel_comes_from_the_roster_the_advisor_was_actually_shown(
    baseline_record: RunRecord,
) -> None:
    """Recorded fact beats replay: the roster is what the run did, not what it would do."""
    roster = {p for r in baseline_record.routing for p in r.roster}
    assert roster
    assert panel_for(baseline_record) == sorted(roster)


def test_an_excluded_theorist_is_absent_from_the_recovered_panel() -> None:
    """Exclusion means the world operated as though they never existed."""
    record = _run("loo_jervis", 3)
    assert "jervis" not in panel_for(record)
    assert "jervis" not in record.personas_consulted


def test_the_control_arm_recovers_an_empty_panel() -> None:
    """It builds no panel at all; inventing one would imply an apparatus it did not have."""
    assert panel_for(_run("escalation_prior", 1)) == []


def test_panel_recovery_survives_a_round_trip_through_json(
    baseline_record: RunRecord,
) -> None:
    """The API serialises records; a view that only works pre-serialisation is useless."""
    restored = RunRecord.model_validate(
        json.loads(json.dumps(baseline_record.model_dump(mode="json")))
    )
    assert panel_for(restored) == panel_for(baseline_record)


# ---------------------------------------------------------------------------
# Representative run. A record selected by an unexplained rule is read as typical when it
# is not, so the rule is stated and the record must be a real one.
# ---------------------------------------------------------------------------


def test_the_representative_run_is_a_record_from_the_input(
    baseline_records: list[RunRecord],
) -> None:
    """There is no average of a justification, so an actual record must be selected."""
    chosen = representative_run(baseline_records)
    assert any(r.run_id == chosen.record.run_id for r in baseline_records)


def test_the_representative_run_sits_at_the_median_rung(
    baseline_records: list[RunRecord],
) -> None:
    rungs = sorted(r.rung for r in baseline_records)
    chosen = representative_run(baseline_records)
    assert chosen.median_rung == pytest.approx(
        (rungs[len(rungs) // 2] + rungs[(len(rungs) - 1) // 2]) / 2
    )


def test_the_representative_run_is_deterministic(
    baseline_records: list[RunRecord],
) -> None:
    """A client that re-fetches must be shown the same transcript."""
    first = representative_run(baseline_records)
    second = representative_run(list(reversed(baseline_records)))
    assert first.record.run_id == second.record.run_id


def test_the_selection_note_says_it_is_not_a_result(
    baseline_records: list[RunRecord],
) -> None:
    """One replication is an anecdote. The UI renders this string verbatim."""
    note = representative_run(baseline_records).selection_note
    assert "not a result" in note.lower()
    assert "anecdote" in note.lower()


def test_representative_run_refuses_to_mix_arms(
    baseline_records: list[RunRecord],
) -> None:
    """A record typical of two arms at once is typical of neither."""
    mixed = [*baseline_records[:2], _run("small_panel", 1)]
    with pytest.raises(ValueError, match="one arm"):
        representative_run(mixed)


def test_representative_run_needs_a_record() -> None:
    with pytest.raises(ValueError):
        representative_run([])


# ---------------------------------------------------------------------------
# Loop steps. Logical, not wall-clock: nothing in RunRecord carries a timestamp and
# nothing should, because per-call timing would mean persisting the prompts.
# ---------------------------------------------------------------------------


def test_loop_steps_are_indexed_contiguously_from_zero(baseline_record: RunRecord) -> None:
    steps = loop_steps(baseline_record)
    assert [s.index for s in steps] == list(range(len(steps)))


def test_loop_steps_run_from_the_world_to_the_decision(baseline_record: RunRecord) -> None:
    """The loop starts with collection and ends with the President writing to the world."""
    steps = loop_steps(baseline_record)
    assert steps[0].actor == WORLD
    assert steps[0].kind == "perception"
    assert steps[-1].kind == "decide"
    assert steps[-1].recipient == WORLD


def test_loop_steps_are_deterministic(baseline_record: RunRecord) -> None:
    assert loop_steps(baseline_record) == loop_steps(baseline_record)


def test_every_consultation_is_followed_by_its_own_opinion(
    baseline_record: RunRecord,
) -> None:
    """Opinions match consultations on (question, persona); order follows routing.selected."""
    steps = loop_steps(baseline_record)
    consults = [s for s in steps if s.kind == "consult"]
    answers = [s for s in steps if s.kind in {"opine", "decline"}]
    assert len(consults) == len(answers) == len(baseline_record.opinions)
    for consult, answer in zip(consults, answers, strict=True):
        assert consult.index < answer.index
        assert (consult.question_id, consult.persona_id) == (
            answer.question_id,
            answer.persona_id,
        )


def test_the_order_within_a_question_follows_the_routing_record(
    baseline_record: RunRecord,
) -> None:
    """matched_by_tag, then chosen_by_advisor, then topped_up — the record's own order."""
    steps = loop_steps(baseline_record)
    for routing in baseline_record.routing:
        consulted = [
            s.persona_id
            for s in steps
            if s.kind == "consult" and s.question_id == routing.question_id
        ]
        assert consulted == list(routing.selected)


def test_a_declining_persona_gets_its_own_step_kind(baseline_record: RunRecord) -> None:
    """Declining is a substantive act, not the absence of one."""
    steps = loop_steps(baseline_record)
    for step in steps:
        if step.kind != "decline":
            continue
        opinion = _deref(baseline_record, step.payload_ref)
        assert opinion.out_of_record is True


def test_every_payload_ref_resolves_against_the_record(baseline_record: RunRecord) -> None:
    """The client dereferences rather than the server duplicating payloads."""
    for step in loop_steps(baseline_record):
        assert _deref(baseline_record, step.payload_ref) is not None


def test_the_control_arm_produces_a_loop_with_no_advisory_steps() -> None:
    """No advisor, no panel, no brief — and the steps must show that rather than fake it."""
    steps = loop_steps(_run("escalation_prior", 1))
    kinds = {s.kind for s in steps}
    assert kinds == {"perception", "brief", "decide"}
    assert not any(s.actor == "advisor" or s.recipient == "advisor" for s in steps)


def _deref(record: RunRecord, ref: str):
    """Resolve a `payload_ref` the way the client will, e.g. `opinions[5]`."""
    if "[" not in ref:
        return getattr(record, ref)
    field, rest = ref.split("[", 1)
    return getattr(record, field)[int(rest.rstrip("]"))]


# ---------------------------------------------------------------------------
# Interaction graph. Four states that all look like "not much happened" must stay apart.
# ---------------------------------------------------------------------------


def test_the_graph_carries_the_whole_panel_not_only_the_consulted(
    baseline_record: RunRecord,
) -> None:
    graph = interaction_graph(baseline_record)
    personas = {n.id for n in graph.nodes if n.kind == "persona"}
    assert personas == set(panel_for(baseline_record))
    assert any(n.state == "unconsulted" for n in graph.nodes if n.kind == "persona")


def test_a_declining_persona_is_not_styled_as_an_absent_one() -> None:
    """The escape hatch firing is the honest outcome, not a gap in the data.

    Hand-built rather than swept from `baseline_records`: whether any given mock replay
    happens to land one persona's *every* opinion on the decline branch is a rare compound
    event (out-of-record is itself a ~15% roll, and it has to hit every opinion a
    single-slot persona got), and it is not this test's job to prove the mock's dice are
    fair. It only needs to prove `interaction_graph` styles that state correctly when it
    occurs, so it constructs the occurrence directly.
    """
    record = RunRecord(
        run_id="fixture-declined-state",
        arm="baseline",
        seed=1,
        started_at="2026-01-01T00:00:00Z",
        wall_time_s=0.0,
        config={},
        backend="mock",
        cache_enabled=True,
        retrieval_mode="stub",
        grounded=False,
        scenario_id="fixture",
        intel_brief=IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate"),
        routing=[
            RoutingRecord(
                question_id="q0",
                k_requested=2,
                mode="advisor",
                chosen_by_advisor=["brodie", "schelling"],
                roster=["brodie", "schelling", "kahn"],
            )
        ],
        opinions=[
            TheoristOpinion(
                persona_id="brodie",
                persona_name="Bernard Brodie",
                question_id="q0",
                position="MOCK: out of record",
                reasoning="MOCK: declined",
                out_of_record=True,
            ),
            TheoristOpinion(
                persona_id="schelling",
                persona_name="Thomas Schelling",
                question_id="q0",
                position="MOCK: a stated position",
                reasoning="MOCK: reasoning",
                out_of_record=False,
            ),
        ],
        personas_consulted=["brodie", "schelling"],
        action=PresidentialAction(action=ActionType.NO_ACTION, justification="MOCK:"),
        rung=0,
    )
    by_id = {n.id: n.state for n in interaction_graph(record).nodes if n.kind == "persona"}
    assert by_id["brodie"] == "declined"
    assert by_id["schelling"] == "active"
    assert by_id["kahn"] == "unconsulted"


def test_an_excluded_persona_is_shown_as_excluded_not_merely_unchosen() -> None:
    """Removed by intervention is a different fact from nobody picking them."""
    graph = interaction_graph(_run("loo_jervis", 3))
    jervis = next(n for n in graph.nodes if n.id == "jervis")
    assert jervis.state == "excluded"


def test_graph_edges_are_deterministic(baseline_record: RunRecord) -> None:
    assert interaction_graph(baseline_record) == interaction_graph(baseline_record)


def test_the_excomm_appears_in_the_graph_anonymously(baseline_record: RunRecord) -> None:
    """ADR 0008/0010. Nodes and edges for every member who spoke, labelled by the
    anonymous institutional seat — never a real name, which this module has no way to
    look up and must not need to."""
    from artsoc.personas import load_excomm

    record = _run("excomm_debate", 3)
    seats = {m.member_id: m.role_title for m in load_excomm()}

    graph = interaction_graph(record)
    excomm_nodes = [n for n in graph.nodes if n.kind == "excomm_member"]
    spoken_members = {s.member_id for s in record.deliberation}
    assert {n.id for n in excomm_nodes} == spoken_members
    for node in excomm_nodes:
        # `label` is the seat's institutional title from the (name-free) registry —
        # views.py has no roster-key access at all, so there is no real name it could
        # leak even by accident.
        assert node.label == seats[node.id]
        assert node.state in {"active", "declined"}

    excomm_edges = [e for e in graph.edges if e.kind == "deliberate"]
    assert {e.target for e in excomm_edges} == spoken_members
    assert all(e.source == "president" for e in excomm_edges)

    # No committee convened on baseline — nothing here is a persona/instrument mislabel.
    assert not [n for n in interaction_graph(baseline_record).nodes if n.kind == "excomm_member"]


def test_excomm_agent_details_carry_one_passage_per_round() -> None:
    record = _run("excomm_debate", 3)
    details = agent_details(record)
    by_member: dict[str, list] = {}
    for statement in record.deliberation:
        by_member.setdefault(statement.member_id, []).append(statement)

    for member_id, statements in by_member.items():
        detail = next(d for d in details if d.id == member_id)
        assert detail.kind == "excomm_member"
        assert len(detail.passages) == len(statements)
        rounds_shown = {label for label, _ in detail.passages}
        assert rounds_shown == {f"Round {s.round}" for s in statements}


def test_excomm_details_are_absent_when_no_committee_convened(baseline_record: RunRecord) -> None:
    assert not [d for d in agent_details(baseline_record) if d.kind == "excomm_member"]


def test_every_edge_endpoint_is_a_node(baseline_record: RunRecord) -> None:
    """A dangling edge renders as a node the record never contained."""
    graph = interaction_graph(baseline_record)
    ids = {n.id for n in graph.nodes}
    for edge in graph.edges:
        assert edge.source in ids and edge.target in ids


def test_the_graph_and_the_steps_agree_on_what_happened(
    baseline_record: RunRecord,
) -> None:
    """Both drive the same playback cursor, so a disagreement is visible on screen."""
    steps = loop_steps(baseline_record)
    graph = interaction_graph(baseline_record)
    from_steps = {(s.actor, s.recipient, s.kind) for s in steps}
    from_edges = {
        (e.source, e.target, e.kind) for e in graph.edges if e.kind != "hallucinated"
    }
    assert from_steps == from_edges
    assert sum(e.weight for e in graph.edges if e.kind != "hallucinated") == len(steps)


def test_off_roster_ids_are_surfaced_rather_than_buried() -> None:
    """The hallucination rate is a finding about how reliably a model routes."""
    record = _run("baseline", 1)
    hallucinated = sorted({h for r in record.routing for h in r.hallucinated})
    graph = interaction_graph(record)
    assert graph.hallucinated_ids == hallucinated
    if hallucinated:
        assert any(n.id == PHANTOM for n in graph.nodes)
        assert any(e.kind == "hallucinated" for e in graph.edges)
    else:
        assert not any(n.id == PHANTOM for n in graph.nodes)


# ---------------------------------------------------------------------------
# Engagement. Descriptive only: consultation counts are not influence.
# ---------------------------------------------------------------------------


def test_engagement_covers_the_panel_not_only_the_speakers(
    baseline_records: list[RunRecord],
) -> None:
    summary = engagement_stats(baseline_records)
    covered = {p.persona_id for p in summary.personas}
    panel = {p for r in baseline_records for p in panel_for(r)}
    assert covered == panel


def test_engagement_separates_why_each_persona_was_selected(
    baseline_records: list[RunRecord],
) -> None:
    """A panel reached by top-up consulted nobody anyone judged relevant."""
    summary = engagement_stats(baseline_records)
    for person in summary.personas:
        assert (
            person.matched_by_tag + person.chosen_by_advisor + person.topped_up
            == person.times_consulted
        )


def test_engagement_states_that_it_is_not_influence(
    baseline_records: list[RunRecord],
) -> None:
    """Routing correlates with question tags, which correlate with outcome."""
    note = engagement_stats(baseline_records).note.lower()
    assert "not influence" in note
    assert "loo_" in note


def test_engagement_is_deterministic(baseline_records: list[RunRecord]) -> None:
    assert engagement_stats(baseline_records) == engagement_stats(baseline_records)


def test_an_unattributable_hallucinated_citation_is_not_pinned_on_anyone() -> None:
    """Passage ids are persona:source:digits; an id with no known prefix is nobody's."""
    records = _sweep("baseline", 3)
    doctored = records[0].model_copy(
        update={"unsupported_citations": ["nobody:wikipedia:1", "not_an_id"]}
    )
    summary = engagement_stats([doctored, *records[1:]])
    assert summary.unattributed_unsupported >= 2
    assert not any(p.persona_id == "nobody" for p in summary.personas)


def test_a_hallucinated_citation_is_attributed_by_its_persona_prefix(
    baseline_records: list[RunRecord],
) -> None:
    who = panel_for(baseline_records[0])[0]
    doctored = baseline_records[0].model_copy(
        update={"unsupported_citations": [f"{who}:wikipedia:999"]}
    )
    summary = engagement_stats([doctored, *baseline_records[1:]])
    assert next(p for p in summary.personas if p.persona_id == who).n_unsupported >= 1


def test_engagement_refuses_to_mix_arms(baseline_records: list[RunRecord]) -> None:
    with pytest.raises(ValueError, match="one arm"):
        engagement_stats([baseline_records[0], _run("small_panel", 1)])


# ---------------------------------------------------------------------------
# Pipeline flow. Not an escalation path: phase 1 has one decision and one terminal rung.
# ---------------------------------------------------------------------------


def test_pipeline_flow_is_labelled_as_flow_not_as_a_path(
    baseline_records: list[RunRecord],
) -> None:
    """There is no sequence of rungs in phase 1; calling it a path would invent one."""
    flow = pipeline_flow(baseline_records)
    assert flow.label == "Pipeline flow to terminal rung"
    assert "path" not in flow.label.lower()
    assert "trajectory" not in flow.label.lower()


def test_every_replication_is_counted_once_in_each_stage(
    baseline_records: list[RunRecord],
) -> None:
    """A Sankey that loses replications between stages is showing a different sweep."""
    flow = pipeline_flow(baseline_records)
    for stage in (0, 1, 2):
        assert sum(n.count for n in flow.nodes if n.stage == stage) == len(baseline_records)


def test_every_flow_link_connects_declared_nodes(
    baseline_records: list[RunRecord],
) -> None:
    flow = pipeline_flow(baseline_records)
    ids = {n.id for n in flow.nodes}
    for link in flow.links:
        assert link.source in ids and link.target in ids


def test_the_control_arm_flows_through_no_panel() -> None:
    """It consults nobody, and the middle stage must say so rather than being empty."""
    flow = pipeline_flow(_sweep("escalation_prior", 4))
    middle = [n for n in flow.nodes if n.stage == 1]
    assert [n.label for n in middle] == ["no panel"]


def test_pipeline_flow_is_deterministic(baseline_records: list[RunRecord]) -> None:
    assert pipeline_flow(baseline_records) == pipeline_flow(baseline_records)


# ---------------------------------------------------------------------------
# The module must stay a pure derivation layer.
# ---------------------------------------------------------------------------


def test_views_make_no_model_call(baseline_records: list[RunRecord]) -> None:
    """A view that could call a model would put a second, untested surface inside the
    access matrix. Every derivation is a projection of a record that already exists."""
    import artsoc.llm as llm_module

    calls: list[object] = []
    original = llm_module.LLMClient.complete
    llm_module.LLMClient.complete = lambda *a, **k: calls.append(a)  # type: ignore[assignment]
    try:
        record = baseline_records[0]
        loop_steps(record)
        interaction_graph(record)
        engagement_stats(baseline_records)
        pipeline_flow(baseline_records)
        representative_run(baseline_records)
    finally:
        llm_module.LLMClient.complete = original  # type: ignore[assignment]
    assert calls == []


def test_no_view_carries_a_prompt(baseline_records: list[RunRecord]) -> None:
    """Invariant 10: prompts do not leave the process. Views are serialised to a browser,
    so a role marker appearing in one would be a second surface for context to cross."""
    record = baseline_records[0]
    blobs = [
        loop_steps(record),
        [interaction_graph(record)],
        [engagement_stats(baseline_records)],
        [pipeline_flow(baseline_records)],
    ]
    for group in blobs:
        for item in group:
            assert "[[ROLE:" not in item.model_dump_json()


# ---------------------------------------------------------------------------
# Agent detail. Every node the graph draws must open onto something.
# ---------------------------------------------------------------------------


def test_every_graph_node_has_a_detail_panel(baseline_record: RunRecord) -> None:
    """A clickable node with no panel reads as a bug, and the phantom node is clickable.

    Checked over several seeds because the hallucination node only appears when the Advisor
    names an off-roster id, and a single seed may not produce one.
    """
    for seed in range(1, 6):
        record = _run("baseline", seed)
        nodes = {node.id for node in interaction_graph(record).nodes}
        details = {detail.id for detail in agent_details(record)}
        assert nodes <= details, f"seed {seed}: nodes with no detail {nodes - details}"


def test_a_theorist_panel_says_why_it_was_consulted(baseline_record: RunRecord) -> None:
    """The record holds a real answer to "why this persona" and it was unsurfaced.

    Under advisor routing that is the Advisor's stated rationale; a persona reached by
    top-up is one nobody judged relevant, which is a different fact and stays distinct.
    """
    personas = [d for d in agent_details(baseline_record) if d.kind == "persona" and d.answers]
    assert personas, "no persona answered; the assertion would be vacuous"
    for detail in personas:
        for answer in detail.answers:
            assert answer.how_selected in {"chosen", "topped_up"}
            assert answer.question, "the question text must travel with the answer"


def test_a_declining_theorist_shows_its_basis_and_no_citations(
    baseline_record: RunRecord,
) -> None:
    """Declining is a substantive act; the panel must show what it was shown."""
    declines = [
        answer
        for detail in agent_details(baseline_record)
        for answer in detail.answers
        if answer.declined
    ]
    assert declines, "no persona declined; the escape hatch is not firing"
    for answer in declines:
        assert answer.basis in {"sources", "beliefs", "none"}
        assert answer.citations == [], "a declining persona cites nothing"


def test_an_excluded_persona_has_no_detail_at_all() -> None:
    """The intervention is a world without them, not a world that declined to ask them."""
    record = _run("loo_schelling", 1)
    details = {detail.id for detail in agent_details(record)}
    assert "schelling" not in details
    assert len(details) > 1, "the rest of the panel must still be present"


def test_the_president_panel_calls_the_justification_a_stated_reason(
    baseline_record: RunRecord,
) -> None:
    """`schema.PresidentialAction` documents the justification as never feeding the rung.

    A panel labelling it "why the action happened" would assert a causal claim the design
    declines to make, so the label is asserted rather than left to whoever edits it next.
    """
    president = next(d for d in agent_details(baseline_record) if d.id == "president")
    labels = [label for label, _ in president.passages]
    assert any("reason given" in label.lower() for label in labels)
    assert not any("because" in label.lower() for label in labels)


def test_run_facts_are_read_from_the_record_not_inferred(baseline_record: RunRecord) -> None:
    """The facts line carries every number so the narrative beside it carries none."""
    facts = run_facts(baseline_record)
    assert facts.action == baseline_record.action.action.value
    assert facts.rung == baseline_record.rung
    assert facts.panel_size == baseline_record.panel_size
    assert facts.personas_consulted == len(baseline_record.personas_consulted)
    assert facts.n_opinions == len(baseline_record.opinions)
    assert facts.n_declines == sum(1 for o in baseline_record.opinions if o.out_of_record)
    assert sum(facts.basis_counts.values()) == len(baseline_record.opinions)
    assert facts.grounded is baseline_record.grounded


def test_agent_details_are_deterministic(baseline_record: RunRecord) -> None:
    """A client that re-fetches must get the same panels, as with every other view."""
    first = [d.model_dump() for d in agent_details(baseline_record)]
    assert first == [d.model_dump() for d in agent_details(baseline_record)]


# ---------------------------------------------------------------------------
# The narrative. Interpretation, and it must not know things no agent knew.
# ---------------------------------------------------------------------------


def test_the_narrative_prompt_carries_no_ground_truth(baseline_record: RunRecord) -> None:
    """Scanned the way tests/test_access_matrix.py scans role prompts.

    A leak here reaches no agent — the run is over — but it would put the host's stipulated
    truth into a summary a reader takes as the simulation's own account of what happened.
    """
    prompt = build_prompt(baseline_record)
    assert baseline_record.host_ground_truth, "the record must have ground truth to leak"
    for phrase in ("HOST-ONLY", "survivability hedge", "host_ground_truth"):
        assert phrase.lower() not in prompt.lower(), f"the narrative prompt leaked {phrase!r}"


def test_the_narrative_is_three_sentences_and_obviously_mock(
    baseline_record: RunRecord,
) -> None:
    """Mock output must never be mistaken for a real summary of a real run."""
    client = LLMClient(backend=MockBackend(), run_seed=0)
    narrative = summarise_run(baseline_record, client, "baseline")
    assert narrative.run_id == baseline_record.run_id
    assert narrative.arm == "baseline"
    assert len(narrative.sentences) == 3
    assert all(MOCK_PREFIX in sentence for sentence in narrative.sentences)
    assert narrative.model == "mock"
    assert "not a finding" in narrative.caveat.lower()


def test_the_narrative_instruction_forbids_causal_language() -> None:
    """The constraint is in the prompt, not only in the docstring that explains it."""
    assert "gave as its reason" in INSTRUCTION
    assert "because" in INSTRUCTION, "the prohibition names the word it forbids"
    assert "did not determine it" in INSTRUCTION


# ---------------------------------------------------------------------------
# Provenance. Every link comes from a recorded id. A link inferred from wording would look
# identical on screen and mean nothing, and nothing downstream could tell the two apart.
# ---------------------------------------------------------------------------


def test_the_chain_runs_from_cited_passages_to_the_action_taken(
    baseline_record: RunRecord,
) -> None:
    flow = provenance_flow(baseline_record)
    kinds = {n.kind for n in flow.nodes}
    assert {"opinion", "coa", "decision"} <= kinds
    assert flow.coa_stage == "present"

    decision = [n for n in flow.nodes if n.kind == "decision"]
    assert len(decision) == 1
    assert decision[0].label == baseline_record.action.action.value


def test_every_link_joins_two_declared_nodes(baseline_record: RunRecord) -> None:
    """A dangling edge draws a relationship between something and nothing."""
    flow = provenance_flow(baseline_record)
    ids = {n.id for n in flow.nodes}
    for link in flow.links:
        assert link.source in ids and link.target in ids


def test_a_supporting_link_exists_only_where_the_advisor_recorded_one(
    baseline_record: RunRecord,
) -> None:
    """`CourseOfAction.supporting_opinions` is the only source for this stage (ADR 0006)."""
    recorded = {
        (coa.coa_id, key)
        for coa in baseline_record.courses_of_action
        for key in coa.supporting_opinions
    }
    drawn = {
        (link.target.removeprefix("coa:"), link.source.removeprefix("opinion:"))
        for link in provenance_flow(baseline_record).links
        if link.kind == "supports"
    }
    assert drawn <= recorded, "a supporting link was drawn that the record does not hold"


def test_the_chosen_path_is_the_one_the_president_took(
    baseline_record: RunRecord,
) -> None:
    flow = provenance_flow(baseline_record)
    chosen_coas = [n for n in flow.nodes if n.kind == "coa" and n.chosen]
    assert len(chosen_coas) == 1
    assert chosen_coas[0].id == f"coa:{baseline_record.action.chosen_coa_id}"

    # An opinion is on the path exactly when the chosen option cited it.
    chosen = next(
        c
        for c in baseline_record.courses_of_action
        if c.coa_id == baseline_record.action.chosen_coa_id
    )
    on_path = {
        n.id.removeprefix("opinion:") for n in flow.nodes if n.kind == "opinion" and n.chosen
    }
    assert on_path <= set(chosen.supporting_opinions)


def test_a_passage_is_on_the_path_only_through_an_opinion_that_is(
    baseline_records: list[RunRecord],
) -> None:
    """Provenance is transitive through recorded links, never asserted directly."""
    for record in baseline_records:
        flow = provenance_flow(record)
        opinions_on_path = {n.id for n in flow.nodes if n.kind == "opinion" and n.chosen}
        for node in flow.nodes:
            if node.kind != "passage" or not node.chosen:
                continue
            feeds = {
                link.target
                for link in flow.links
                if link.kind == "cites" and link.source == node.id
            }
            assert feeds & opinions_on_path, f"{node.id} is on the path via nothing"


def test_a_declining_opinion_stays_in_the_chain(baseline_records: list[RunRecord]) -> None:
    """Dropping declines would show a panel that was never asked rather than one that was
    asked and had nothing in its record to offer."""
    declined = [
        n
        for record in baseline_records
        for n in provenance_flow(record).nodes
        if n.kind == "opinion" and n.declined
    ]
    assert declined, "this fixture is only useful if someone declined"


def test_a_record_without_courses_of_action_says_so_rather_than_drawing_nothing() -> None:
    """The control arm has no panel to ground an option in, and records written before ADR
    0006 have no such field. Either way the stage is absent, not empty."""
    flow = provenance_flow(_run("escalation_prior", 1))
    assert flow.coa_stage == "absent"
    assert "ADR 0006" in flow.coa_note
    assert not [n for n in flow.nodes if n.kind == "coa"]
    assert [n for n in flow.nodes if n.kind == "decision"]


def test_provenance_is_deterministic(baseline_record: RunRecord) -> None:
    assert provenance_flow(baseline_record) == provenance_flow(baseline_record)


# ---------------------------------------------------------------------------
# Course-of-action support. A recorded property of the Advisor's document — not influence.
# ---------------------------------------------------------------------------


def test_coa_support_counts_only_what_the_chosen_option_cited(
    baseline_records: list[RunRecord],
) -> None:
    support = coa_support(baseline_records)
    expected: Counter[str] = Counter()
    for record in baseline_records:
        chosen = [
            c for c in record.courses_of_action if c.coa_id == record.action.chosen_coa_id
        ]
        if not chosen:
            continue
        expected.update({k.split(":", 1)[-1] for k in chosen[0].supporting_opinions})

    for person in support.personas:
        assert person.runs_in_chosen == expected[person.persona_id]


def test_coa_support_refuses_to_call_itself_influence(
    baseline_records: list[RunRecord],
) -> None:
    """Whose opinions an option cited is a fact about the document, not a measure of what
    anyone changed. Causal attribution comes from the loo_* arms."""
    note = coa_support(baseline_records).note.lower()
    assert "not a measure of influence" in note
    assert "loo_" in note
    dumped = coa_support(baseline_records).model_dump()
    assert not any("influence" in key for key in dumped)


def test_coa_support_is_empty_but_valid_for_an_arm_with_no_options() -> None:
    """The control arm proposes none, so every count is zero and none is missing."""
    support = coa_support(_sweep("escalation_prior", 3))
    assert support.n_with_coas == 0
    assert all(p.runs_in_chosen == 0 and p.share_of_chosen == 0.0 for p in support.personas)


def test_coa_support_is_deterministic(baseline_records: list[RunRecord]) -> None:
    assert coa_support(baseline_records) == coa_support(baseline_records)


def test_coa_support_refuses_to_mix_arms(baseline_records: list[RunRecord]) -> None:
    with pytest.raises(ValueError, match="one arm"):
        coa_support([baseline_records[0], _run("small_panel", 1)])


# ---------------------------------------------------------------------------
# Session facts. The numbers a landing page states, so the prose beside it states none.
# ---------------------------------------------------------------------------


def test_session_facts_reports_the_delta_only_when_a_control_was_run(
    baseline_records: list[RunRecord],
) -> None:
    """Absolute rates are not findings. With no control there is no interpretable quantity,
    and a zero would read as 'no difference' rather than as 'no comparison'."""
    from artsoc.metrics import delta, summarise

    arm = summarise(baseline_records)
    control = summarise(_sweep("escalation_prior", 6))

    assert session_facts(baseline_records, arm).d_mean_rung is None
    assert session_facts(baseline_records, arm).control_arm is None

    with_control = session_facts(baseline_records, arm, delta(arm, control))
    assert with_control.d_mean_rung == round(arm.mean_rung - control.mean_rung, 3)
    assert with_control.control_arm == "escalation_prior"


def test_session_facts_never_disagrees_with_the_arm_summary(
    baseline_records: list[RunRecord],
) -> None:
    """It takes the summary rather than recomputing, so the landing page and the report
    cannot state different numbers for the same sweep."""
    from artsoc.metrics import summarise

    arm = summarise(baseline_records)
    facts = session_facts(baseline_records, arm)
    assert (facts.mean_rung, facts.p_nuclear, facts.n) == (arm.mean_rung, arm.p_nuclear, arm.n)


def test_session_facts_separates_actions_proposed_from_actions_taken(
    baseline_records: list[RunRecord],
) -> None:
    """Three options are offered and one is taken, so the two counts differ and conflating
    them would overstate what the President did."""
    from artsoc.metrics import summarise

    facts = session_facts(baseline_records, summarise(baseline_records))
    assert sum(a.chosen for a in facts.actions) == len(baseline_records)
    assert sum(a.proposed for a in facts.actions) > sum(a.chosen for a in facts.actions)
    for action in facts.actions:
        assert action.is_nuclear == (action.rung >= 6)


# ---------------------------------------------------------------------------
# Step excerpts, and the per-step edges that let playback distinguish one deliberation
# from the next.
# ---------------------------------------------------------------------------


def test_every_edge_names_every_step_it_covers(baseline_record: RunRecord) -> None:
    """The Advisor consults twelve personas one at a time. Collapsing those to a single
    first index made playback light the edge once and then sit still, so a viewer stepping
    through could not tell one consultation from the next."""
    steps = loop_steps(baseline_record)
    graph = interaction_graph(baseline_record)

    covered = sorted(
        index
        for edge in graph.edges
        if edge.kind != "hallucinated"
        for index in edge.step_indices
    )
    assert covered == list(range(len(steps))), "every step belongs to exactly one edge"


def test_an_edges_step_indices_agree_with_its_weight(baseline_record: RunRecord) -> None:
    for edge in interaction_graph(baseline_record).edges:
        assert edge.weight == len(edge.step_indices)
        assert edge.step_index == edge.step_indices[0]
        assert edge.step_indices == sorted(edge.step_indices)


def test_each_step_index_maps_back_to_the_pair_that_made_it(
    baseline_record: RunRecord,
) -> None:
    steps = {s.index: s for s in loop_steps(baseline_record)}
    for edge in interaction_graph(baseline_record).edges:
        if edge.kind == "hallucinated":
            continue
        for index in edge.step_indices:
            step = steps[index]
            assert (step.actor, step.recipient, step.kind) == (
                edge.source,
                edge.target,
                edge.kind,
            )


def test_every_step_that_produced_text_carries_an_excerpt(
    baseline_record: RunRecord,
) -> None:
    for step in loop_steps(baseline_record):
        if step.kind == "select" and not baseline_record.routing[0].rationale:
            continue  # tag routing states no reason, because nobody reasoned
        assert step.excerpt, f"step {step.index} ({step.kind}) has no excerpt"


def test_an_excerpt_is_a_truncation_of_the_record_never_a_paraphrase(
    baseline_record: RunRecord,
) -> None:
    """A caption that summarised would be a second account of what was said, sitting beside
    the first and free to disagree with it."""
    for step in loop_steps(baseline_record):
        if not step.excerpt:
            continue
        source = " ".join(_source_text(baseline_record, step).split())
        opening = step.excerpt.rstrip("…")
        assert source.startswith(opening), f"step {step.index} was not a prefix of its source"


def test_an_excerpt_is_bounded_and_cut_on_a_word(baseline_record: RunRecord) -> None:
    for step in loop_steps(baseline_record):
        assert len(step.excerpt) <= EXCERPT_CHARS + 1
        assert "\n" not in step.excerpt
        if step.excerpt.endswith("…"):
            assert not step.excerpt.rstrip("…").endswith(" ")


def test_a_consultation_shows_the_question_not_the_answer(
    baseline_record: RunRecord,
) -> None:
    """The answer is the step after it. Showing it on the consultation would put the reply
    before the asking."""
    questions = {q.question_id: q.text for q in baseline_record.questions}
    for step in loop_steps(baseline_record):
        if step.kind != "consult":
            continue
        expected = " ".join(questions[step.question_id or ""].split())
        assert expected.startswith(step.excerpt.rstrip("…"))


def test_a_declining_step_still_says_what_the_persona_said(
    baseline_records: list[RunRecord],
) -> None:
    """A decline states no position, so the excerpt falls back to the reasoning. An empty
    caption would render the escape hatch firing as nothing having happened."""
    declines = [
        step
        for record in baseline_records
        for step in loop_steps(record)
        if step.kind == "decline"
    ]
    assert declines, "this fixture is only useful if someone declined"
    assert all(step.excerpt for step in declines)


def test_excerpts_carry_no_prompt(baseline_records: list[RunRecord]) -> None:
    """Invariant 10. These are drawn onto a graph in a browser, which is a new surface."""
    for record in baseline_records:
        for step in loop_steps(record):
            assert "[[ROLE:" not in step.excerpt
            assert "[[WHO:" not in step.excerpt


def _source_text(record: RunRecord, step: LoopStep) -> str:
    """The record field an excerpt is taken from, resolved the way `loop_steps` does."""
    target = _deref(record, step.payload_ref)
    if step.kind == "perception":
        return target.description
    if step.kind == "brief":
        return target.summary
    if step.kind in {"query", "formulate"}:
        return target.text
    if step.kind == "select":
        return target.rationale
    if step.kind == "consult":
        question = next(
            q for q in record.questions if q.question_id == step.question_id
        )
        return question.text
    if step.kind in {"opine", "decline"}:
        return target.position or target.reasoning
    if step.kind == "synthesise":
        return target.summary
    return target.justification
