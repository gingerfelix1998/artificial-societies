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

import pytest

from artsoc.config import RunConfig, load_arm
from artsoc.llm import MOCK_PREFIX, LLMClient, MockBackend
from artsoc.narrative import INSTRUCTION, build_prompt, summarise_run
from artsoc.schema import RunRecord
from artsoc.sim import run_once
from artsoc.views import (
    PHANTOM,
    WORLD,
    agent_details,
    engagement_stats,
    interaction_graph,
    loop_steps,
    panel_for,
    pipeline_flow,
    representative_run,
    run_facts,
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


def test_a_declining_persona_is_not_styled_as_an_absent_one(
    baseline_records: list[RunRecord],
) -> None:
    """The escape hatch firing is the honest outcome, not a gap in the data."""
    states = {
        n.state
        for record in baseline_records
        for n in interaction_graph(record).nodes
        if n.kind == "persona"
    }
    assert {"active", "declined", "unconsulted"} <= states


def test_an_excluded_persona_is_shown_as_excluded_not_merely_unchosen() -> None:
    """Removed by intervention is a different fact from nobody picking them."""
    graph = interaction_graph(_run("loo_jervis", 3))
    jervis = next(n for n in graph.nodes if n.id == "jervis")
    assert jervis.state == "excluded"


def test_graph_edges_are_deterministic(baseline_record: RunRecord) -> None:
    assert interaction_graph(baseline_record) == interaction_graph(baseline_record)


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
