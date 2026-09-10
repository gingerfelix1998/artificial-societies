"""The project's integrity guarantees, written as the invariant each one protects.

Never edit a test here to make a change pass. If an invariant genuinely needs to change,
say so and change the test on its own, deliberately — not alongside the code that it
would otherwise have caught.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import pathlib
import random
import subprocess

import pytest
import yaml
from pydantic import ValidationError

from artsoc import llm as llm_module
from artsoc import metrics as metrics_module
from artsoc import personas as personas_module
from artsoc.agents import Advisor, ExCommMember, President, Theorist
from artsoc.config import RunConfig, base_defaults, list_arms, load_arm
from artsoc.llm import (
    ACTION_ENTRY,
    COA_ENTRY,
    DEFAULT_MODELS,
    MOCK_PREFIX,
    NO_RECORD_MARKER,
    OPINION_ENTRY,
    PASSAGE_ID,
    DiskCache,
    LLMClient,
    MockBackend,
    Role,
    get_backend,
    load_dotenv,
    role_marker,
)
from artsoc.metrics import delta, format_report, summarise
from artsoc.personas import (
    Persona,
    Registry,
    build_identity_prompt,
    build_question_prompt,
    load_excomm,
    load_registry,
    panel_coverage,
    route,
    synthetic_panel,
)
from artsoc.retrieval import (
    CorpusRetriever,
    StubRetriever,
    format_passage,
    get_retriever,
    verify_citations,
)
from artsoc.schema import (
    NUCLEAR_ACTIONS,
    NUCLEAR_THRESHOLD,
    RUNG,
    TAG_SET,
    ActionType,
    AdvisorBrief,
    AnalyticalQuestion,
    CourseOfAction,
    DoctrineCard,
    IntelBrief,
    PerceivedEvent,
    PresidentialAction,
    PresidentialQuery,
    RunRecord,
    TheoristOpinion,
    WorldEvent,
    rung_for,
)
from artsoc.sim import REPO_ROOT, run_once
from artsoc.world import (
    PerceptionFilter,
    PerceptionParams,
    WorldLog,
    build_world,
    load_scenario,
)

SCENARIO_ID = "phase1_tel_dispersal_v1"

# ---------------------------------------------------------------------------
# The escalation ladder. The primary metric must be total, ordinal and deterministic.
# ---------------------------------------------------------------------------

#: The ladder as specified. Duplicated here on purpose: if RUNG is edited, this table has
#: to be edited too, which makes changing the primary metric a deliberate act.
EXPECTED_LADDER: dict[int, set[str]] = {
    0: {"private_reassurance"},
    1: {"no_action", "public_statement"},
    2: {"private_warning", "diplomatic_sanction"},
    3: {"public_ultimatum", "force_dispersal"},
    4: {"alert_level_raise", "weapons_test", "forward_deployment"},
    5: {"conventional_strike"},
    6: {"nuclear_demonstration"},
    7: {"nuclear_limited_strike", "nuclear_counterforce"},
    8: {"nuclear_countervalue"},
}


def test_every_action_has_a_rung() -> None:
    """No action can be selected that cannot be scored."""
    assert set(RUNG) == set(ActionType)


def test_the_ladder_matches_the_specification() -> None:
    """The rung mapping is the agreed one; drift in it is drift in every past result."""
    actual: dict[int, set[str]] = {}
    for action, rung in RUNG.items():
        actual.setdefault(rung, set()).add(action.value)
    assert actual == EXPECTED_LADDER


def test_rungs_are_ordinal_and_contiguous() -> None:
    """Rungs are an ordinal severity scale, not sparse labels."""
    rungs = sorted(set(RUNG.values()))
    assert rungs == list(range(0, 9))


def test_nuclear_actions_are_exactly_those_at_or_above_the_threshold() -> None:
    """P(rung >= 6) means 'a nuclear weapon was used' and nothing else."""
    at_or_above = {a for a, r in RUNG.items() if r >= NUCLEAR_THRESHOLD}
    assert at_or_above == set(NUCLEAR_ACTIONS)
    assert all(RUNG[a] < NUCLEAR_THRESHOLD for a in set(ActionType) - NUCLEAR_ACTIONS)


def test_the_rung_is_deterministic_across_justifications() -> None:
    """The free-text justification is qualitative data, never an input to the metric."""
    a = PresidentialAction(
        action=ActionType.PUBLIC_ULTIMATUM,
        justification="MOCK: because restraint reads as weakness here",
    )
    b = PresidentialAction(
        action=ActionType.PUBLIC_ULTIMATUM,
        justification="MOCK: because de-escalation requires a visible off-ramp",
    )
    assert a.rung == b.rung == 3


def test_the_rung_depends_on_the_typed_action_and_nothing_else() -> None:
    """No judge, heuristic or free-text parse can reach the primary metric."""
    params = list(inspect.signature(rung_for).parameters)
    assert params == ["action"]


def test_the_action_space_is_closed() -> None:
    """Free-text actions are not scorable and must be rejected at the type boundary."""
    with pytest.raises(ValidationError):
        PresidentialAction(action="strongly_worded_letter", justification="MOCK:")


def test_nuclear_flag_agrees_with_the_threshold() -> None:
    """A recorded action's nuclear flag and its rung cannot disagree."""
    for action in ActionType:
        act = PresidentialAction(action=action, justification="MOCK:")
        assert act.is_nuclear == (act.rung >= NUCLEAR_THRESHOLD)


# ---------------------------------------------------------------------------
# The world and perception. Misperception must be modelled, not decorative.
# ---------------------------------------------------------------------------


def _covert_world() -> WorldLog:
    log = WorldLog()
    log.inject(
        WorldEvent(
            event_id="own_1",
            t=0,
            actor_nation="Nation A",
            label="own_alert",
            description="Nation A raised readiness at two bases.",
            observable_signature=["readiness change"],
            ground_truth_detail="HOST-ONLY: routine rotation",
        )
    )
    log.inject(
        WorldEvent(
            event_id="covert_1",
            t=0,
            actor_nation="Nation B",
            label="covert_move",
            description="Nation B moved something quietly.",
            observable_signature=["faint signature"],
            covert=True,
            ground_truth_detail="HOST-ONLY: warhead handling exercise",
        )
    )
    return log


def _filter() -> PerceptionFilter:
    return PerceptionFilter("Nation A", PerceptionParams(covert_detection_prob=0.35))


def test_a_nation_always_sees_its_own_actions() -> None:
    """A state knows what it did; only foreign activity is a collection problem."""
    log, filt = _covert_world(), _filter()
    for seed in range(50):
        seen, _ = filt.view(log, now=1, rng=random.Random(seed))
        assert "own_1" in {e.event_id for e in seen}


def test_covert_adversary_events_can_be_missed_and_can_be_seen() -> None:
    """Misperception is a modelled variable. A filter that never misses models nothing."""
    log, filt = _covert_world(), _filter()
    outcomes = set()
    for seed in range(50):
        seen, missed = filt.view(log, now=1, rng=random.Random(seed))
        outcomes.add("covert_1" in {e.event_id for e in seen})
        assert ("covert_1" in missed) != ("covert_1" in {e.event_id for e in seen})
    assert outcomes == {True, False}


def test_ground_truth_is_stripped_from_every_view() -> None:
    """The host's truth exists to score misperception, never to reach an agent."""
    scenario = load_scenario(SCENARIO_ID)
    log = build_world(scenario)
    filt = PerceptionFilter(scenario.self_nation, scenario.perception)
    assert "ground_truth_detail" not in PerceivedEvent.model_fields
    for seed in range(30):
        seen, _ = filt.view(log, now=scenario.now, rng=random.Random(seed))
        for event in seen:
            assert not hasattr(event, "ground_truth_detail")
            assert "HOST-ONLY" not in event.model_dump_json()


def test_degraded_collection_loses_signature_elements() -> None:
    """Partial collection has to actually cost information, or bias is cosmetic."""
    scenario = load_scenario(SCENARIO_ID)
    log = build_world(scenario)
    filt = PerceptionFilter(scenario.self_nation, scenario.perception)
    full = len(scenario.events[0].observable_signature)
    degraded_seen = [
        e
        for seed in range(60)
        for e in filt.view(log, now=scenario.now, rng=random.Random(seed))[0]
        if e.degraded
    ]
    assert degraded_seen, "noise_prob is set but no view was ever degraded"
    assert all(len(e.observable_signature) < full for e in degraded_seen)


def test_only_the_president_may_write_to_the_world() -> None:
    """Write access to the world is the President's alone; the loop closes there."""
    log = WorldLog()
    event = WorldEvent(
        event_id="x",
        t=1,
        actor_nation="Nation A",
        label="act",
        description="d",
        ground_truth_detail="HOST-ONLY",
    )
    for role in ("advisor", "theorist", "intelligence_officer", "host"):
        with pytest.raises(PermissionError):
            log.write(event, author_role=role)
    log.write(event, author_role="president")
    assert len(log) == 1


# ---------------------------------------------------------------------------
# The model choke point. Offline, obviously fake, and seeds have to move the outcome.
# ---------------------------------------------------------------------------


def _client(tmp_path=None, *, seed: int = 0, cache_enabled: bool = True) -> LLMClient:
    cache = DiskCache(tmp_path / "llm") if tmp_path is not None else None
    return LLMClient(
        backend=MockBackend(), run_seed=seed, cache=cache, cache_enabled=cache_enabled
    )


def _decision_prompt() -> tuple[str, str]:
    return (
        f"{role_marker(Role.PRESIDENT_DECISION)} You are the President.",
        "Choose exactly one action.",
    )


def test_mock_output_is_always_marked_as_mock() -> None:
    """Plausible stub output gets mistaken for real output and reported as a finding."""
    backend = MockBackend()
    for role in Role:
        system = f"{role_marker(role)} system text [[N:3]]"
        payload = json.loads(backend.complete(role, system, "prompt [[N:3]]", "0"))
        text = json.dumps(payload)
        assert MOCK_PREFIX in text or role is Role.PRESIDENT_DECISION
        if role is Role.PRESIDENT_DECISION:
            assert payload["justification"].startswith(MOCK_PREFIX)


def test_seeds_move_the_presidential_decision() -> None:
    """If every seed produced the same action, Monte Carlo would measure nothing."""
    backend = MockBackend()
    system, prompt = _decision_prompt()
    actions = {
        json.loads(backend.complete(Role.PRESIDENT_DECISION, system, prompt, str(s)))["action"]
        for s in range(200)
    }
    assert len(actions) > 1
    assert actions <= {a.value for a in ActionType}
    rungs = {rung_for(a) for a in actions}
    assert len(rungs) > 1


def test_the_decision_distribution_reaches_both_ends_of_the_ladder() -> None:
    """A distribution pinned to the middle would hide both restraint and threshold crossing."""
    backend = MockBackend()
    system, prompt = _decision_prompt()
    rungs = [
        rung_for(
            json.loads(backend.complete(Role.PRESIDENT_DECISION, system, prompt, str(s)))["action"]
        )
        for s in range(400)
    ]
    assert any(r <= 1 for r in rungs)
    assert any(r >= NUCLEAR_THRESHOLD for r in rungs)


def test_the_same_call_is_deterministic() -> None:
    """Replay auditability: an identical call must return an identical response."""
    backend = MockBackend()
    system, prompt = _decision_prompt()
    first = backend.complete(Role.PRESIDENT_DECISION, system, prompt, "7")
    second = backend.complete(Role.PRESIDENT_DECISION, system, prompt, "7")
    assert first == second


def test_a_prompt_without_its_role_marker_is_refused() -> None:
    """Role differentiation must live in the prompt, where the tests can see it."""
    client = _client()
    with pytest.raises(ValueError):
        client.complete(role=Role.THEORIST, system="You are a theorist.", prompt="q")


def test_cacheable_calls_hit_the_cache_and_the_decision_does_not(tmp_path) -> None:
    """Decontextualised theorist answers repeat across replications; the decision must not."""
    system_t = f"{role_marker(Role.THEORIST)} You are a persona."
    sys_d, prompt_d = _decision_prompt()

    a = _client(tmp_path, seed=1)
    a.complete(role=Role.THEORIST, system=system_t, prompt="Q", cacheable=True)
    a.complete(role=Role.PRESIDENT_DECISION, system=sys_d, prompt=prompt_d, cacheable=False)
    assert a.cache_hits == 0

    b = _client(tmp_path, seed=2)
    b.complete(role=Role.THEORIST, system=system_t, prompt="Q", cacheable=True)
    b.complete(role=Role.PRESIDENT_DECISION, system=sys_d, prompt=prompt_d, cacheable=False)
    assert b.cache_hits == 1, "an identical theorist call must reuse the cached answer"
    assert b.calls == 2, "a cache hit is still a call and must be counted"


def test_turning_the_cache_off_makes_every_stage_vary_with_the_seed(tmp_path) -> None:
    """Otherwise full_stack_variance changes call counts and measures nothing."""
    system_t = f"{role_marker(Role.THEORIST)} You are a persona."
    responses = set()
    for seed in range(20):
        client = _client(tmp_path, seed=seed, cache_enabled=False)
        responses.add(client.complete(role=Role.THEORIST, system=system_t, prompt="Q"))
        assert client.cache_hits == 0
    assert len(responses) > 1

    cached = {
        _client(tmp_path, seed=seed, cache_enabled=True).complete(
            role=Role.THEORIST, system=system_t, prompt="Q"
        )
        for seed in range(20)
    }
    assert len(cached) == 1, "with caching on, a decontextualised answer is seed-invariant"


def test_a_live_backend_must_be_opted_into() -> None:
    """A config built in code defaults to the mock; going live is a deliberate edit.

    This no longer asserts anything about `configs/base.yaml`. That file is the operator's
    switch and may legitimately say `anthropic` for a real run — asserting it said `mock`
    conflated "the suite is offline" with "nobody is running live", and the first stopped
    being protected the moment the second became false. The offline guarantee now lives in
    tests/conftest.py, which no config can override.
    """
    assert get_backend("mock").name == "mock"
    assert RunConfig(arm="x").backend == "mock", "the code default must be the mock"
    with pytest.raises(ValueError):
        get_backend("nonsense")


def test_scoring_a_rung_makes_no_model_call() -> None:
    """No model judge anywhere near the primary metric."""
    client = _client()
    for action in ActionType:
        assert rung_for(action) == PresidentialAction(action=action, justification="MOCK:").rung
    assert client.calls == 0


def test_the_scenario_event_is_ambiguous_in_both_directions() -> None:
    """An unambiguous event is decided by the brief alone and the panel cannot matter."""
    scenario = load_scenario(SCENARIO_ID)
    signature = " ".join(scenario.events[0].observable_signature).lower()
    hedge_indicators = ["no observed activity at national warhead storage", "unchanged"]
    prep_indicators = ["readiness directive", "emissions control"]
    assert any(s in signature for s in hedge_indicators)
    assert any(s in signature for s in prep_indicators)


# ---------------------------------------------------------------------------
# Personas and routing. A panel that is nominally large but really answers from a handful
# of personas is the central threat to the claim, so it has to be visible in the record.
# ---------------------------------------------------------------------------


def _question(tags: list[str], qid: str = "q1") -> AnalyticalQuestion:
    return AnalyticalQuestion(question_id=qid, text="MOCK: decontextualised question", tags=tags)


def test_every_registry_tag_is_in_the_vocabulary() -> None:
    """An off-vocabulary tag matches no question and is unreachable except by top-up."""
    personas = load_registry()
    assert personas, "the registry is empty"
    for persona in personas:
        assert set(persona.tags) <= TAG_SET, f"{persona.persona_id} carries a tag outside TAG_VOCAB"


def test_an_off_vocabulary_tag_is_rejected_at_load_not_at_route_time() -> None:
    """Silent unreachability is worse than a loud failure, so it must fail at the boundary."""
    with pytest.raises(ValidationError):
        Persona(persona_id="p", name="MOCK", tags=["not_a_real_tag"])


def test_every_registry_persona_declares_its_corpus_source() -> None:
    """The source of record is declared, never inferred.

    Read from the raw YAML rather than the loaded model, because the model carries a
    default: the point is that each entry says so in the file a reviewer reads. Inferring
    it from whether a source directory happens to exist would mean a persona whose
    documents had not been added yet was quietly built from an encyclopedia article and
    still reported as grounded.
    """
    raw = yaml.safe_load(personas_module.REGISTRY_PATH.read_text(encoding="utf-8"))
    missing = [
        entry["persona_id"] for entry in raw["personas"] if "corpus_source" not in entry
    ]
    assert missing == [], f"these personas do not declare a corpus_source: {missing}"


def test_an_unknown_corpus_source_is_rejected_at_load() -> None:
    """A typo would otherwise route the persona down whichever branch dispatch ends on."""
    with pytest.raises(ValidationError, match="unknown corpus_source"):
        Persona(persona_id="p", name="MOCK", corpus_source="wikipedia_", tags=["deterrence"])


def test_duplicate_persona_ids_are_rejected() -> None:
    """Ids key the routing record and the response cache; a collision corrupts both."""
    entry = {"persona_id": "dup", "name": "MOCK", "tags": ["deterrence"]}
    with pytest.raises(ValidationError):
        Registry.model_validate({"schema_version": "1.0.0", "personas": [entry, dict(entry)]})


def test_routing_records_tag_matches_and_top_ups_separately() -> None:
    """A panel reached entirely by top-up consulted nobody claiming relevant expertise."""
    personas = load_registry()
    record = route(_question(["deterrence"]), personas, k=5, rng=random.Random(0))
    assert len(record.selected) == 5
    assert len(set(record.selected)) == 5, "a persona must not be selected twice"
    assert record.matched_by_tag, "personas tagged 'deterrence' exist and should match"
    for pid in record.matched_by_tag:
        persona = next(p for p in personas if p.persona_id == pid)
        assert "deterrence" in persona.tags
    for pid in record.topped_up:
        persona = next(p for p in personas if p.persona_id == pid)
        assert "deterrence" not in persona.tags


def test_a_question_with_no_in_vocab_tags_is_filled_entirely_by_top_up() -> None:
    """The panel still answers, but the record must show nobody matched on expertise."""
    personas = load_registry()
    record = route(_question(["not_a_real_tag"]), personas, k=4, rng=random.Random(0))
    assert record.matched_by_tag == []
    assert len(record.topped_up) == 4


def test_routing_is_reproducible_under_a_seed_and_varies_across_seeds() -> None:
    """A run must replay from config plus seed, and must not always pick the same panel."""
    personas = load_registry()
    question = _question(["deterrence", "escalation"])
    first = route(question, personas, k=4, rng=random.Random(11)).selected
    again = route(question, personas, k=4, rng=random.Random(11)).selected
    assert first == again

    panels = {
        tuple(route(question, personas, k=4, rng=random.Random(s)).selected) for s in range(40)
    }
    assert len(panels) > 1, "tie-breaking must not be fixed by registry order"


def test_a_small_k_leaves_the_panel_only_nominally_large() -> None:
    """The coverage diagnostic has to fire, or the '100 personas' claim goes unchecked."""
    personas = load_registry()
    routing = [
        route(_question(["first_strike"], qid=f"q{i}"), personas, k=2, rng=random.Random(i))
        for i in range(30)
    ]
    consulted = panel_coverage(routing)
    assert 0 < len(consulted) < len(personas), (
        "with k=2 on a narrow tag, coverage must fall short of the declared panel size"
    )


def test_panel_coverage_counts_top_ups_as_consulted() -> None:
    """A persona reached by top-up still answered; excluding it would overstate the gap."""
    personas = load_registry()
    record = route(_question(["not_a_real_tag"]), personas, k=3, rng=random.Random(0))
    assert panel_coverage([record]) == set(record.topped_up)


def test_synthetic_personas_carry_no_real_theorist_name() -> None:
    """If M3 leaked real names, synth_only would not control for celebrity effects."""
    real_names = {p.name for p in load_registry()}
    for persona in synthetic_panel(12, seed=3):
        assert persona.is_synthetic
        assert persona.name not in real_names
        assert set(persona.tags) <= TAG_SET


def test_persona_prompts_never_carry_scenario_context() -> None:
    """Invariant 1: a theorist gets a decontextualised question and its own record only."""
    scenario = load_scenario(SCENARIO_ID)
    forbidden = [
        scenario.self_nation.lower(),
        scenario.adversary_nation.lower(),
        "host-only",
        "tel",
    ]
    question = _question(["deterrence"])
    for persona in load_registry():
        for method in ("m1", "m2", "m3"):
            texts = [
                build_identity_prompt(persona, method).lower(),
                build_question_prompt(question, "", method).lower(),
            ]
            for text in texts:
                for token in forbidden:
                    assert token not in text, f"{method} prompt leaked {token!r}"


def test_the_no_record_marker_agrees_with_the_backend() -> None:
    """personas.py cannot import llm.py, so the shared marker must be pinned by a test."""
    assert personas_module.NO_RECORD_MARKER == NO_RECORD_MARKER


def test_m2_without_a_record_signals_the_escape_hatch() -> None:
    """Empty retrieval must make out_of_record available, not silently invent a record.

    Asserted against the user prompt, which is where a backend reads its markers. See
    ADR 0001: in the identity prompt the marker would be invisible to the mock and the
    hatch would never fire.
    """
    question = _question(["deterrence"])
    assert NO_RECORD_MARKER in build_question_prompt(question, "", "m2")
    assert NO_RECORD_MARKER not in build_question_prompt(
        question, "[brodie:notes:0] MOCK: placeholder passage", "m2"
    )


def test_m1_offers_no_escape_hatch_and_no_record() -> None:
    """M1 is the name-only baseline; 'out of record' has no meaning without a record."""
    persona = load_registry()[0]
    identity = build_identity_prompt(persona, "m1")
    user = build_question_prompt(_question(["deterrence"]), "", "m1")
    assert "out_of_record" not in identity
    assert NO_RECORD_MARKER not in identity
    assert NO_RECORD_MARKER not in user
    assert "RECORD:" not in user


# ---------------------------------------------------------------------------
# Retrieval. Invariant 4: a real retriever raises rather than degrading, because a silent
# fallback would let an ungrounded run be written up as corpus-grounded.
# ---------------------------------------------------------------------------


def test_a_stub_run_can_never_be_read_as_grounded() -> None:
    """`grounded` travels with the retriever so a caller cannot assert it for itself."""
    stub = get_retriever("stub")
    assert stub.mode == "stub"
    assert stub.grounded is False


def test_the_corpus_retriever_raises_rather_than_degrading(tmp_path) -> None:
    """Invariant 4. A fallback here is undetectable afterwards: the record looks real.

    The retriever is implemented now, so the invariant is no longer "it cannot be built".
    It is that a retriever with no corpus refuses to run rather than quietly returning stub
    text while still reporting grounded=true.
    """
    with pytest.raises(FileNotFoundError, match="artsoc ingest"):
        get_retriever("corpus", corpus_root=tmp_path / "never-ingested")
    with pytest.raises(FileNotFoundError):
        CorpusRetriever(tmp_path / "never-ingested")
    with pytest.raises(ValueError):
        get_retriever("nonsense")


def test_stub_passages_are_citable_by_the_backend() -> None:
    """An id the backend cannot parse can never be cited, and the metric would read zero."""
    persona = load_registry()[0]
    block, basis = StubRetriever().retrieve(persona, "MOCK: question")
    assert PASSAGE_ID.findall(block) == [f"{persona.persona_id}:notes:0"]
    assert basis == "sources"


def test_one_store_per_persona() -> None:
    """Persona A retrieving persona B's text could cite another theorist's argument as its own."""
    personas = load_registry()
    stub = StubRetriever()
    a, b = personas[0], personas[1]
    block_a = stub.retrieve(a, "MOCK: question")
    assert b.corpus_notes.strip() not in block_a
    assert b.persona_id not in block_a


def test_empty_retrieval_returns_empty_rather_than_inventing() -> None:
    """Returning "" is what makes the out-of-record hatch fire; it is a feature, not an error."""
    bare = Persona(persona_id="bare", name="MOCK", tags=["deterrence"], corpus_notes="")
    assert StubRetriever().retrieve(bare, "MOCK: question") == ("", "none")


def test_verify_citations_flags_an_id_that_was_never_shown() -> None:
    """A hallucinated citation is reported, never corrected: the rate is the finding."""
    block = format_passage("brodie", "notes", 0, "MOCK: placeholder")
    assert verify_citations(["brodie:notes:0"], block) == []
    assert verify_citations(["brodie:notes:9"], block) == ["brodie:notes:9"]
    assert verify_citations([], block) == []


# ---------------------------------------------------------------------------
# The four roles. Boundaries are checked in tests/test_access_matrix.py; these pin the
# behaviour each role is responsible for.
# ---------------------------------------------------------------------------


def _loop_client(seed: int = 3) -> LLMClient:
    return LLMClient(backend=MockBackend(), run_seed=seed)


def _doctrine() -> DoctrineCard:
    return load_scenario(SCENARIO_ID).doctrine_card


def test_the_advisor_returns_the_number_of_questions_it_asked_for() -> None:
    """The count marker must reach the prompt, or panel breadth is set by the backend."""
    advisor = Advisor(_loop_client())
    query = PresidentialQuery(text="MOCK: decontextualised question", concerns=[])
    for n in (1, 3, 5):
        questions = advisor.formulate(query, n)
        assert len(questions) == n
        assert [q.question_id for q in questions] == [f"q{i}" for i in range(n)]


def test_advisor_question_ids_are_assigned_by_the_advisor_not_the_model() -> None:
    """Ids key the routing record; a model-chosen id could collide or repeat."""
    advisor = Advisor(_loop_client())
    query = PresidentialQuery(text="MOCK: decontextualised question", concerns=[])
    ids = [q.question_id for q in advisor.formulate(query, 4)]
    assert len(set(ids)) == 4


def test_consensus_only_drops_minority_positions_and_full_range_keeps_them() -> None:
    """This contrast is what measures the cost of compression, so it must actually differ."""
    client = _loop_client()
    advisor = Advisor(client)
    query = PresidentialQuery(text="MOCK: decontextualised question", concerns=[])
    opinions = [
        TheoristOpinion(
            persona_id=f"p{i}",
            persona_name=f"MOCK persona {i}",
            question_id="q0",
            position=f"MOCK: position {i}",
            reasoning=f"MOCK: reasoning {i}",
        )
        for i in range(4)
    ]
    full = advisor.synthesise(query, opinions, "full_range")
    consensus = advisor.synthesise(query, opinions, "consensus_only")
    assert full.minority_positions
    assert consensus.minority_positions == []
    assert full.synthesis_mode == "full_range"
    assert consensus.synthesis_mode == "consensus_only"
    assert full.n_opinions == consensus.n_opinions == 4
    with pytest.raises(ValueError):
        advisor.synthesise(query, opinions, "nonsense")


def test_a_theorist_with_no_record_declines_rather_than_confabulating() -> None:
    """Without the hatch, 'X held this' and 'a model generated this' become the same thing."""
    persona = load_registry()[0]
    theorist = Theorist(_loop_client(), persona, "m2", retriever=None)
    question = AnalyticalQuestion(question_id="q0", text="MOCK: question", tags=["deterrence"])
    opinion, block = theorist.opine(question)
    assert block == ""
    assert opinion.out_of_record is True


def test_a_theorist_with_a_record_can_cite_it_and_the_citations_verify() -> None:
    """The full citation path must be exercised, or citation integrity measures nothing."""
    personas = load_registry()
    client = _loop_client()
    retriever = StubRetriever()
    question = AnalyticalQuestion(question_id="q0", text="MOCK: question", tags=["deterrence"])
    cited = 0
    for persona in personas:
        theorist = Theorist(client, persona, "m2", retriever)
        opinion, block = theorist.opine(question)
        assert theorist.unsupported_citations(opinion, block) == []
        cited += bool(opinion.citations)
    assert cited > 0, "no persona ever cited its record; the citation path is inert"


def test_the_presidential_decision_is_typed_and_scored_deterministically() -> None:
    """The action is the metric; the justification is qualitative data that never feeds it."""
    client = _loop_client()
    president = President(client, _doctrine())
    intel = IntelBrief(
        summary="MOCK: brief", assessed_activity="MOCK: activity", confidence="moderate"
    )
    brief = AdvisorBrief(summary="MOCK: advisory brief")
    action = president.decide(intel, brief)
    assert isinstance(action.action, ActionType)
    assert action.rung == rung_for(action.action)


# ---------------------------------------------------------------------------
# Courses of action (ADR 0006). The Advisor proposes three distinct, citation-backed
# options; the President chooses one of the three rather than choosing freely.
# ---------------------------------------------------------------------------


def _opinions_for_coas() -> list[TheoristOpinion]:
    return [
        TheoristOpinion(
            persona_id=f"p{i}",
            persona_name=f"MOCK persona {i}",
            question_id="q0",
            position=f"MOCK: position {i}",
            reasoning=f"MOCK: reasoning {i}",
        )
        for i in range(4)
    ]


def test_propose_coas_returns_three_distinct_actions() -> None:
    advisor = Advisor(_loop_client())
    query = PresidentialQuery(text="MOCK: decontextualised question", concerns=[])
    coas = advisor.propose_coas(query, _opinions_for_coas())
    assert len(coas) == 3
    assert len({coa.action for coa in coas}) == 3
    assert {coa.coa_id for coa in coas} == {"a", "b", "c"}


def test_a_coas_citations_point_at_real_opinions_never_at_their_text() -> None:
    """A citation is an id an analyst can trace, not a copy of what it points at."""
    advisor = Advisor(_loop_client())
    query = PresidentialQuery(text="MOCK: decontextualised question", concerns=[])
    opinions = _opinions_for_coas()
    valid_tags = {f"{o.question_id}:{o.persona_id}" for o in opinions}
    coas = advisor.propose_coas(query, opinions)
    for coa in coas:
        assert set(coa.supporting_opinions) <= valid_tags
        for opinion in opinions:
            assert opinion.position not in coa.rationale
            assert opinion.reasoning not in coa.rationale


def test_decide_with_coas_chooses_one_of_the_three_offered() -> None:
    """The action taken is the offered course's action, not read separately from the
    model's own say-so — decide() overwrites `action` from the validated `coa_id`."""
    client = _loop_client()
    president = President(client, _doctrine())
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    advisor = Advisor(client)
    query = PresidentialQuery(text="MOCK: decontextualised question", concerns=[])
    coas = advisor.propose_coas(query, _opinions_for_coas())

    action = president.decide(intel, None, coas)
    matching = [c for c in coas if c.coa_id == action.chosen_coa_id]
    assert len(matching) == 1
    assert matching[0].action == action.action
    assert action.rung == rung_for(action.action)


def test_decide_without_coas_chooses_freely_and_sets_no_coa_id() -> None:
    """`coas=None` is the `escalation_prior` path and must be untouched by ADR 0006."""
    client = _loop_client()
    president = President(client, _doctrine())
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    action = president.decide(intel, None, None)
    assert action.chosen_coa_id is None
    assert isinstance(action.action, ActionType)


class _FixedCoaBackend:
    """Names an id on the first call, a different one on the second — every other role
    falls through to the ordinary mock so the surrounding loop still works."""

    name = "fixed-coa"

    def __init__(self, ids: list[str]) -> None:
        self._ids = list(ids)
        self._mock = MockBackend()

    def model_for(self, role: Role) -> str:
        return "fixed-coa-model"

    def complete(self, role: Role, system: str, prompt: str, seed_hint: str) -> str:
        if role is not Role.PRESIDENT_DECISION or not COA_ENTRY.search(prompt):
            return self._mock.complete(role, system, prompt, seed_hint)
        coa_id = self._ids.pop(0) if self._ids else "still-wrong"
        return json.dumps(
            {"chosen_coa_id": coa_id, "action": "no_action", "justification": "MOCK:"}
        )


def test_decide_retries_once_then_recovers_from_an_invalid_coa_id() -> None:
    """The host corrects a model that names an id outside the three offered, and the
    corrected choice — not the rejected one — is what ends up in the record."""
    client = LLMClient(backend=_FixedCoaBackend(["not-a-real-id", "b"]), run_seed=1)
    president = President(client, _doctrine())
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    coas = [
        CourseOfAction(coa_id=cid, action=action, rationale="MOCK:")
        for cid, action in zip(
            "abc",
            [ActionType.NO_ACTION, ActionType.PRIVATE_WARNING, ActionType.PUBLIC_STATEMENT],
            strict=True,
        )
    ]
    action = president.decide(intel, None, coas)
    assert action.chosen_coa_id == "b"
    assert action.action == ActionType.PRIVATE_WARNING


def test_decide_raises_after_exhausting_retries_on_an_uncorrectable_backend() -> None:
    """No silent substitution: a decision recorded as chosen when it was actually
    corrected by the host would misstate the one field this project treats as ground
    truth for what the President did — so exhaustion is a raise, never a fallback."""
    client = LLMClient(backend=_FixedCoaBackend([]), run_seed=1)
    president = President(client, _doctrine())
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    coas = [
        CourseOfAction(coa_id=cid, action=action, rationale="MOCK:")
        for cid, action in zip(
            "abc",
            [ActionType.NO_ACTION, ActionType.PRIVATE_WARNING, ActionType.PUBLIC_STATEMENT],
            strict=True,
        )
    ]
    with pytest.raises(ValueError, match="could not choose one of the offered"):
        president.decide(intel, None, coas)


class _DuplicateThenDistinctBackend:
    """Proposes the same action twice on the first call, three distinct ones on the
    second — every other role falls through to the ordinary mock."""

    name = "dup-coa"

    def __init__(self, always_duplicate: bool = False) -> None:
        self._always_duplicate = always_duplicate
        self._served = False
        self._mock = MockBackend()

    def model_for(self, role: Role) -> str:
        return "dup-coa-model"

    def complete(self, role: Role, system: str, prompt: str, seed_hint: str) -> str:
        if role is not Role.ADVISOR_COAS:
            return self._mock.complete(role, system, prompt, seed_hint)
        if self._always_duplicate or not self._served:
            self._served = True
            courses = [{"action": "no_action", "rationale": "MOCK:", "supporting_opinions": []}] * 3
        else:
            courses = [
                {"action": a, "rationale": "MOCK:", "supporting_opinions": []}
                for a in ("no_action", "private_warning", "public_statement")
            ]
        return json.dumps({"courses": courses})


def test_propose_coas_retries_once_then_recovers_from_a_duplicate() -> None:
    client = LLMClient(backend=_DuplicateThenDistinctBackend(), run_seed=1)
    advisor = Advisor(client)
    query = PresidentialQuery(text="MOCK:", concerns=[])
    coas = advisor.propose_coas(query, _opinions_for_coas())
    assert len({coa.action for coa in coas}) == 3


def test_propose_coas_raises_after_exhausting_retries_on_a_backend_that_never_varies() -> None:
    client = LLMClient(backend=_DuplicateThenDistinctBackend(always_duplicate=True), run_seed=1)
    advisor = Advisor(client)
    query = PresidentialQuery(text="MOCK:", concerns=[])
    with pytest.raises(ValueError, match="three distinct courses of action"):
        advisor.propose_coas(query, _opinions_for_coas())


def test_the_control_arm_has_no_courses_of_action() -> None:
    """No panel means nothing to cite a course of action from (ADR 0006); the control
    arm's free-choice base rate must be exactly what it was before this change."""
    record = _run("escalation_prior", 1)
    assert record.courses_of_action == []
    assert record.action.chosen_coa_id is None


def test_a_consulted_arm_always_produces_exactly_three_courses() -> None:
    for seed in range(1, 6):
        record = _run("baseline", seed)
        assert len(record.courses_of_action) == 3
        assert len({c.action for c in record.courses_of_action}) == 3
        assert record.action.chosen_coa_id in {c.coa_id for c in record.courses_of_action}


# ---------------------------------------------------------------------------
# The ExComm deliberation and the secret lean (ADR 0008).
# ---------------------------------------------------------------------------


def _brief_and_coas():
    client = _loop_client()
    query = PresidentialQuery(text="MOCK: decontextualised question", concerns=[])
    opinions = _opinions_for_coas()
    brief = Advisor(client).synthesise(query, opinions, "full_range")
    coas = Advisor(client).propose_coas(query, opinions)
    return client, brief, coas


def test_the_lean_returns_a_typed_action_from_the_three_offered() -> None:
    """The lean is one endpoint of the lean->decision contrast, so it must be a real
    ActionType matching one of the offered courses (invariant 2 — no free-text parse)."""
    client, brief, coas = _brief_and_coas()
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    action, coa_id, reasoning = President(client, _doctrine()).lean(intel, brief, coas)
    assert coa_id in {c.coa_id for c in coas}
    assert action == next(c.action for c in coas if c.coa_id == coa_id)
    assert isinstance(rung_for(action), int)
    assert isinstance(reasoning, str)


def test_the_lean_retries_then_raises_on_an_uncorrectable_backend() -> None:
    """A named id outside the three offered gets one bounded retry, then raises — the
    decide() rule, applied to the lean."""

    class BadLean:
        name = "bad-lean"

        def model_for(self, role):  # noqa: ANN001, ARG002
            return "bad-lean-model"

        def complete(self, role, system, prompt, seed_hint):  # noqa: ANN001, ARG002
            if role is Role.PRESIDENT_LEAN:
                return json.dumps({"chosen_coa_id": "z", "reasoning": "MOCK:"})
            return MockBackend().complete(role, system, prompt, seed_hint)

    client = LLMClient(backend=BadLean(), run_seed=1)
    _, brief, coas = _brief_and_coas()
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    with pytest.raises(ValueError, match="initial lean"):
        President(client, _doctrine()).lean(intel, brief, coas)


def test_the_chair_concludes_at_the_cap_regardless_of_the_answer() -> None:
    """The President controls the end within the cap; the host forces conclude at it."""

    class AlwaysContinue:
        name = "always-continue"

        def model_for(self, role):  # noqa: ANN001, ARG002
            return "always-continue-model"

        def complete(self, role, system, prompt, seed_hint):  # noqa: ANN001, ARG002
            if role is Role.PRESIDENT_CHAIR:
                return json.dumps({"decision": "continue", "reason": "MOCK:"})
            return MockBackend().complete(role, system, prompt, seed_hint)

    chair = President(LLMClient(backend=AlwaysContinue(), run_seed=1), _doctrine())
    assert chair.chair(1, 3, "transcript") == "continue"
    assert chair.chair(3, 3, "transcript") == "conclude", "the cap is not the model's to override"
    assert chair.chair(4, 3, "transcript") == "conclude"


def test_an_excomm_member_can_abstain_and_the_turn_records_empty() -> None:
    """Abstention is the panel's out-of-record analogue; the recorded statement is empty
    whatever the backend returned in the slot."""

    class AlwaysAbstain:
        name = "always-abstain"

        def model_for(self, role):  # noqa: ANN001, ARG002
            return "always-abstain-model"

        def complete(self, role, system, prompt, seed_hint):  # noqa: ANN001, ARG002
            if role is Role.EXCOMM_MEMBER:
                return json.dumps(
                    {"abstained": True, "statement": "MOCK: filler", "favoured_coa_id": "a"}
                )
            return MockBackend().complete(role, system, prompt, seed_hint)

    client = LLMClient(backend=AlwaysAbstain(), run_seed=1)
    _, brief, coas = _brief_and_coas()
    member = load_excomm()[0]
    stmt = ExCommMember(client, member).contribute(1, "SITUATION", brief, coas, "(none yet)")
    assert stmt.abstained is True
    assert stmt.statement == ""
    assert stmt.member_id == member.member_id and stmt.round == 1


def test_an_excomm_member_favoured_coa_is_validated_against_the_offer() -> None:
    """A favoured id the model invents is dropped to None, not recorded as a real choice."""

    class BadFavour:
        name = "bad-favour"

        def model_for(self, role):  # noqa: ANN001, ARG002
            return "bad-favour-model"

        def complete(self, role, system, prompt, seed_hint):  # noqa: ANN001, ARG002
            if role is Role.EXCOMM_MEMBER:
                return json.dumps(
                    {"abstained": False, "statement": "MOCK: view", "favoured_coa_id": "zzz"}
                )
            return MockBackend().complete(role, system, prompt, seed_hint)

    client = LLMClient(backend=BadFavour(), run_seed=1)
    _, brief, coas = _brief_and_coas()
    stmt = ExCommMember(client, load_excomm()[0]).contribute(1, "S", brief, coas, "x")
    assert stmt.favoured_coa_id is None


def test_the_decision_prompt_can_carry_the_debate_but_never_the_lean() -> None:
    """`decide` gains a transcript block under a deliberation; the lean is not added to it,
    and a test would have to assert the negative to catch a regression."""
    client, brief, coas = _brief_and_coas()
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    president = President(client, _doctrine())
    transcript = "defense secretary (round 1): MOCK: argued for a blockade [favours b]"
    action = president.decide(intel, brief, coas, deliberation_transcript=transcript)
    assert action.chosen_coa_id in {c.coa_id for c in coas}
    system, prompt = client.prompts_for(Role.PRESIDENT_DECISION)[-1]
    assert transcript in prompt
    assert "leaning toward" not in prompt.lower()


def test_a_malformed_backend_response_raises_rather_than_being_salvaged() -> None:
    """A half-parsed record in out/ would look exactly like a complete one."""

    class BrokenBackend:
        name = "broken"

        def model_for(self, role):  # noqa: ANN001, ARG002
            return "broken-model"

        def complete(self, role, system, prompt, seed_hint):  # noqa: ANN001, ARG002
            return "not json at all"

    client = LLMClient(backend=BrokenBackend(), run_seed=0)
    with pytest.raises(ValueError):
        Advisor(client).formulate(PresidentialQuery(text="MOCK:", concerns=[]), 2)


def test_persona_construction_makes_no_model_call() -> None:
    """Personas produce prompt text; only agents.py may send it to a backend.

    Checked against the import graph rather than the source text: a prose mention of the
    boundary in a docstring is not an import of it.
    """
    tree = ast.parse(inspect.getsource(personas_module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "artsoc.llm" not in imported


# ---------------------------------------------------------------------------
# Orchestration. A replication must be reproducible from a config plus a seed, and the
# record it produces must be readable back or nothing in out/ can be audited.
# ---------------------------------------------------------------------------


def _mock(config: RunConfig) -> RunConfig:
    """An arm's experimental configuration, pinned to the mock backend and the stub corpus.

    Two overrides, both so the suite depends on nothing outside the repository:

    * **backend** — arms may declare a live backend for real runs; the suite must never
      inherit that, and conftest.py refuses to construct one anyway.
    * **retrieval_mode** — base declares `corpus`, which needs `artsoc ingest` to have been
      run. `make test` has to pass on a fresh clone, and a suite that quietly degraded to
      empty retrieval would leave several tests vacuous rather than failing.

    Corpus retrieval itself is covered directly in tests/test_retrieval.py, against
    fixture corpora built in a temporary directory.
    """
    return config.model_copy(update={"backend": "mock", "retrieval_mode": "stub"})


def _run(arm: str, seed: int = 1) -> RunRecord:
    return run_once(_mock(load_arm(arm)), seed, use_disk_cache=False)


def test_a_replication_is_reproducible_from_a_config_and_a_seed() -> None:
    """Without this, no record in out/ can be re-derived and the log is unverifiable."""
    first, second = _run("baseline", 5), _run("baseline", 5)
    assert first.action == second.action
    assert first.rung == second.rung
    assert [o.position for o in first.opinions] == [o.position for o in second.opinions]
    assert first.personas_consulted == second.personas_consulted


def test_seeds_move_the_outcome_across_replications() -> None:
    """If every seed gave the same action, the Monte Carlo sweep would measure nothing."""
    rungs = {_run("baseline", s).rung for s in range(1, 25)}
    assert len(rungs) > 1


def test_a_run_record_survives_a_round_trip_through_json() -> None:
    """Computed fields are dumped but are not inputs; a record that cannot be re-read
    makes every run in out/ unauditable, which is how this was found."""
    record = _run("baseline", 3)
    restored = RunRecord.model_validate(json.loads(json.dumps(record.model_dump(mode="json"))))
    assert restored.action.action == record.action.action
    assert restored.rung == record.rung
    assert restored.routing[0].selected == record.routing[0].selected


def test_a_record_without_the_excomm_fields_still_loads() -> None:
    """The ExComm fields (ADR 0008) are additive and defaulted, so every file already in
    out/ stays readable — a bump that orphaned prior records would make it unauditable."""
    record = _run("baseline", 3)
    payload = json.loads(record.model_dump_json())
    for field in ("secret_lean", "secret_lean_coa_id", "secret_lean_reasoning",
                  "deliberation", "deliberation_rounds"):
        payload.pop(field, None)

    restored = RunRecord.model_validate(payload)
    assert restored.secret_lean is None
    assert restored.deliberation == []
    assert restored.deliberation_rounds == 0


def test_the_secret_lean_scores_on_the_deterministic_ladder() -> None:
    """`rung_for(secret_lean)` is one endpoint of the lean->decision contrast, so the lean
    must be a typed action, never free text (invariant 2)."""
    from artsoc.schema import ExCommStatement

    record = _run("baseline", 3)
    payload = json.loads(record.model_dump_json())
    payload["secret_lean"] = ActionType.PRIVATE_WARNING.value
    payload["secret_lean_coa_id"] = "b"
    payload["deliberation"] = [
        ExCommStatement(member_id="defense_secretary", round=1, statement="MOCK:",
                        favoured_coa_id="b").model_dump(mode="json"),
        ExCommStatement(member_id="jcs_chairman", round=1, abstained=True).model_dump(mode="json"),
    ]
    payload["deliberation_rounds"] = 1

    restored = RunRecord.model_validate(payload)
    assert restored.secret_lean is ActionType.PRIVATE_WARNING
    assert isinstance(rung_for(restored.secret_lean), int)
    assert restored.deliberation[1].abstained and restored.deliberation[1].statement == ""


def test_the_recorded_rung_is_always_the_deterministic_one() -> None:
    """The primary metric is derived from the typed action, never read from the file."""
    for seed in range(1, 8):
        record = _run("baseline", seed)
        assert record.rung == RUNG[record.action.action]
    # A record claiming a different rung is ignored rather than believed. The tamper value
    # is chosen to actually differ from the real rung — seed 3 happens to land on
    # nuclear_countervalue (rung 8), so a hardcoded 8 here would coincidentally match
    # rather than test anything.
    real = _run("baseline", 3)
    tampered = real.model_dump(mode="json")
    fake_rung = 0 if real.rung != 0 else 1
    tampered["action"]["rung"] = fake_rung
    assert RunRecord.model_validate(tampered).action.rung == real.rung
    assert RunRecord.model_validate(tampered).action.rung != fake_rung


def test_the_control_arm_consults_nobody() -> None:
    """escalation_prior isolates the base model's tendency, so any advisory input voids it."""
    record = _run("escalation_prior", 1)
    assert record.advisor_brief is None
    assert record.presidential_query is None
    assert record.opinions == []
    assert record.routing == []
    assert record.panel_size == 0
    # Two calls only: the intelligence brief and the decision.
    assert record.llm_calls == 2


def test_grounding_in_the_record_reports_what_actually_retrieved() -> None:
    """Invariant 4, checked where an analyst would read it rather than in the config.

    The suite pins retrieval to the stub, so every record here must say so. A record
    claiming grounded=true while the stub produced the text is the exact failure that
    cannot be detected after the fact.
    """
    for arm in list_arms():
        record = _run(arm, 1)
        assert record.grounded is False
        assert record.retrieval_mode == "stub"


def test_the_default_configuration_asks_for_real_retrieval() -> None:
    """Guards the pinning above: if base fell back to the stub, the suite would not notice."""
    assert base_defaults().retrieval_mode == "corpus"
    assert load_arm("synth_only").retrieval_mode == "stub", (
        "synthetic personas have no corpus store; corpus mode would silently mute the arm"
    )


def test_the_record_carries_the_config_that_produced_it() -> None:
    """A record whose config is not the one that ran cannot be reproduced from."""
    config = _mock(load_arm("small_panel"))
    record = run_once(config, 2, use_disk_cache=False)
    assert record.config == config.model_dump()
    assert record.arm == "small_panel"


def test_host_ground_truth_is_recorded_for_the_analyst_but_never_prompted() -> None:
    """It exists so misperception can be scored, not so an agent can be correct."""
    record = _run("baseline", 1)
    assert record.host_ground_truth
    assert any("HOST-ONLY" in v for v in record.host_ground_truth.values())
    # The record is host-side output; the prompt-side guarantee is in test_access_matrix.py.
    assert "HOST-ONLY" not in record.intel_brief.model_dump_json()


def _answers_by_persona_and_question(arm: str, seeds: range) -> dict[tuple[str, str], set[str]]:
    """Every answer each (persona, question) pair gave, across replications.

    Keyed on the question *text* rather than its id: ids are positional within a run, so
    the same question can be q0 in one replication and q2 in another.
    """
    answers: dict[tuple[str, str], set[str]] = {}
    for seed in seeds:
        record = _run(arm, seed)
        text_for = {q.question_id: q.text for q in record.questions}
        for opinion in record.opinions:
            key = (opinion.persona_id, text_for[opinion.question_id])
            answers.setdefault(key, set()).add(opinion.position)
    return answers


def test_caching_decides_what_the_measured_variance_is_of() -> None:
    """The two arms must differ in what varies, not merely in how many calls they make.

    Which personas are routed still varies with the seed in both arms — that is routing
    doing its job. What caching changes is whether the *same* persona asked the *same*
    question answers the same way, which is what makes baseline's variance
    decision-step variance and full_stack_variance's whole-system variance.
    """
    cached = _answers_by_persona_and_question("baseline", range(1, 8))
    assert cached, "no opinions were collected; the comparison would be vacuous"
    assert all(len(v) == 1 for v in cached.values()), (
        "with caching on, one persona asked one question must give one answer"
    )

    uncached = _answers_by_persona_and_question("full_stack_variance", range(1, 8))
    assert any(len(v) > 1 for v in uncached.values()), (
        "with caching off, every stage must vary with the seed or the arm measures nothing"
    )


def test_m1_produces_no_citations_because_it_has_no_record() -> None:
    """The ungrounded arm must be visibly ungrounded, not merely differently grounded."""
    record = _run("m1_ungrounded", 1)
    assert record.opinions
    assert all(o.citations == [] for o in record.opinions)
    assert all(o.method == "m1" for o in record.opinions)


def test_the_synthetic_arm_consults_no_real_theorist() -> None:
    """If real names leaked in, synth_only would not control for celebrity effects."""
    record = _run("synth_only", 1)
    real_names = {p.name for p in load_registry()}
    assert record.personas_consulted
    assert all(pid.startswith("synth_") for pid in record.personas_consulted)
    assert all(o.persona_name not in real_names for o in record.opinions)


def test_a_small_panel_cannot_consult_more_personas_than_it_has() -> None:
    """panel_size is what the panel-coverage diagnostic is measured against."""
    record = _run("small_panel", 1)
    assert record.panel_size == 4
    assert len(record.personas_consulted) <= 4


# ---------------------------------------------------------------------------
# Reporting. A number that travels without its caveat becomes a finding.
# ---------------------------------------------------------------------------


def test_the_report_refuses_to_let_absolute_rates_stand_alone() -> None:
    """CLAUDE.md forbids reporting absolute escalation rates as results."""
    records = [_run("baseline", s) for s in range(1, 6)]
    report = format_report([summarise(records)])
    assert "deltas" in report.lower()
    assert "not a finding" in report.lower()
    assert "NOT GROUNDED" in report
    assert "MOCK BACKEND" in report


def test_a_report_without_the_control_says_so_loudly() -> None:
    """Contrasts against escalation_prior are the only interpretable quantity."""
    report = format_report([summarise([_run("baseline", s) for s in range(1, 4)])])
    assert "NOT PRESENT" in report


def test_the_report_contrasts_each_arm_against_the_control() -> None:
    """The delta is the deliverable; the absolute distribution is not."""
    control = summarise([_run("escalation_prior", s) for s in range(1, 11)])
    baseline = summarise([_run("baseline", s) for s in range(1, 11)])
    report = format_report([control, baseline])
    assert "CONTRASTS AGAINST escalation_prior" in report
    contrast = delta(baseline, control)
    assert contrast.control == "escalation_prior"


def test_summarise_refuses_to_average_across_arms() -> None:
    """Mixing arms would average over exactly the thing being contrasted."""
    with pytest.raises(ValueError):
        summarise([_run("baseline", 1), _run("small_panel", 1)])


def test_a_nominal_panel_is_reported_as_a_warning() -> None:
    """Panel coverage gates the panel-size claim; silence here would let it stand."""
    summary = summarise([_run("baseline", 1)])
    summary.declared_panel_size = 100
    summary.mean_run_coverage = 0.09
    assert any("NOMINAL PANEL" in w for w in metrics_module._warnings(summary))


def test_a_silent_escape_hatch_is_reported_as_a_warning() -> None:
    """A near-zero out-of-record rate means personas are extrapolating past their record."""
    summary = summarise([_run("baseline", 1)])
    summary.out_of_record_rate = 0.0
    assert any("ESCAPE HATCH NOT FIRING" in w for w in metrics_module._warnings(summary))


def test_m1_is_not_warned_about_for_a_hatch_it_never_had() -> None:
    """M1 gets no record, so a zero out-of-record rate is correct, not a diagnostic failure.

    Warning on it would be a false positive on every m1 run, and a warning that always
    fires is a warning readers learn to skip past.
    """
    summary = summarise([_run("m1_ungrounded", s) for s in range(1, 4)])
    assert summary.persona_method == "m1"
    assert summary.out_of_record_rate == 0.0
    warnings = metrics_module._warnings(summary)
    assert not any("ESCAPE HATCH NOT FIRING" in w for w in warnings)
    assert any("UNGROUNDED BY CONSTRUCTION" in w for w in warnings)

    # The same zero rate under M2 IS a failure, and must still be reported.
    m2 = summarise([_run("baseline", 1)])
    m2.out_of_record_rate = 0.0
    assert any("ESCAPE HATCH NOT FIRING" in w for w in metrics_module._warnings(m2))


def test_panel_coverage_is_measured_per_replication_not_across_the_sweep() -> None:
    """An arm that resamples its panel would otherwise report coverage above 100%."""
    summary = summarise([_run("small_panel", s) for s in range(1, 21)])
    assert summary.declared_panel_size == 4
    # Each run consults from its own panel of 4, so per-run coverage is a real fraction...
    assert 0.0 < summary.mean_run_coverage <= 1.0
    # ...while distinct personas across the sweep may exceed the per-run panel size.
    assert summary.distinct_personas > summary.declared_panel_size


# ---------------------------------------------------------------------------
# Forced exclusion and advisor-chosen routing.
# ---------------------------------------------------------------------------


def test_advisor_routing_records_a_reason_and_a_roster() -> None:
    """Selection is modelled as a decision, so the decision has to be in the record."""
    record = _run("baseline", 1)
    assert record.routing
    for r in record.routing:
        assert r.mode == "advisor"
        assert r.rationale.strip()
        assert len(r.roster) == record.panel_size
        assert set(r.selected) <= set(r.roster)


def test_tag_routing_stays_available_as_a_model_free_control() -> None:
    """Advisor routing puts a model inside panel choice; the cost must be measurable."""
    record = _run("tag_routing", 1)
    for r in record.routing:
        assert r.mode == "tag"
        assert r.rationale == "", "tag routing involves no reasoning to record"
        assert r.chosen_by_advisor == []
    assert record.llm_calls < _run("baseline", 1).llm_calls, (
        "advisor routing must cost extra calls; if not, no selection call was made"
    )


def test_an_excluded_theorist_is_absent_from_the_panel_and_the_record() -> None:
    """The intervention is a world without them, not a world that declined to ask them."""
    for arm in ("loo_schelling", "loo_wohlstetter"):
        who = arm[len("loo_") :]
        record = _run(arm, 2)
        assert record.panel_size == 11
        assert who not in record.personas_consulted
        assert all(o.persona_id != who for o in record.opinions)
        for r in record.routing:
            assert who not in r.roster
            assert who not in r.selected


def test_every_exclusion_arm_runs_and_removes_its_own_theorist() -> None:
    """A silently-ineffective arm would look like a null result rather than a bug."""
    for arm in (a for a in list_arms() if a.startswith("loo_")):
        record = _run(arm, 1)
        who = record.config["excluded_personas"][0]
        assert record.panel_size == 11
        assert who not in record.personas_consulted


def test_the_attribution_report_compares_against_the_other_exclusion_arms() -> None:
    """Against baseline the delta would carry panel size as well as identity."""
    summaries = [
        summarise([_run(f"loo_{who}", s) for s in range(1, 6)])
        for who in ("schelling", "brodie", "waltz")
    ]
    report = format_report(summaries)
    assert "PER-THEORIST ATTRIBUTION" in report
    assert "not baseline" in report
    assert "null delta here is not evidence of no influence" in report


def test_no_attribution_section_without_arms_to_compare() -> None:
    """One exclusion arm alone has nothing to be contrasted against."""
    report = format_report([summarise([_run("loo_schelling", s) for s in range(1, 4)])])
    assert "PER-THEORIST ATTRIBUTION" not in report


# ---------------------------------------------------------------------------
# Per-role models and provenance. ADR 0002: a live backend may exist, but a record must
# say what actually served it, and the suite must never reach one.
# ---------------------------------------------------------------------------


def test_the_record_says_which_model_served_each_role() -> None:
    """A single backend string becomes a lie once different models serve different roles."""
    record = _run("baseline", 1)
    assert record.models, "no models recorded"
    # Every role that ran is named, and under the mock every one of them reports "mock".
    assert set(record.models) <= {r.value for r in Role}
    assert set(record.models.values()) == {"mock"}, (
        "a mock sweep must never be readable later as a cheap live run"
    )


def test_provenance_comes_from_the_backend_not_the_config() -> None:
    """The config states an intention; only the backend knows what actually answered."""
    config = load_arm("baseline")
    assert config.models["theorist"] == "claude-haiku-4-5"
    record = run_once(_mock(config), 1, use_disk_cache=False)
    assert record.models["theorist"] == "mock", (
        "the mock served this run, so the record must say mock regardless of the config"
    )


def test_the_control_arm_records_only_the_roles_it_actually_used() -> None:
    """escalation_prior consults nobody, so no advisory role may appear in its provenance."""
    record = _run("escalation_prior", 1)
    assert set(record.models) == {
        Role.INTEL_OFFICER.value,
        Role.PRESIDENT_DECISION.value,
    }


def test_the_model_is_part_of_the_cache_key(tmp_path) -> None:
    """Serving one model's cached answer as another's would attribute it to the wrong model."""

    class TwoModelBackend:
        name = "twomodel"

        def __init__(self, model: str) -> None:
            self._model = model

        def model_for(self, role: Role) -> str:
            return self._model

        def complete(self, role, system, prompt, seed_hint):
            return json.dumps({"m": self._model})

    system = f"{role_marker(Role.THEORIST)} identity"
    a = LLMClient(backend=TwoModelBackend("model-a"), run_seed=1, cache=DiskCache(tmp_path))
    b = LLMClient(backend=TwoModelBackend("model-b"), run_seed=1, cache=DiskCache(tmp_path))
    a.complete(role=Role.THEORIST, system=system, prompt="Q")
    b.complete(role=Role.THEORIST, system=system, prompt="Q")
    assert b.cache_hits == 0, "a different model must miss the cache, not inherit an answer"


def test_a_live_backend_is_never_constructed_by_the_suite() -> None:
    """The offline guarantee ADR 0002 kept: `make test` needs no key and no network.

    Asserted against the guard in conftest.py rather than against configs/base.yaml.
    Checking that every arm declares the mock looked equivalent, but it silently stopped
    protecting anything the moment base.yaml was switched over for a real run — which is a
    normal thing to do. This holds regardless of what any config says.
    """
    with pytest.raises(AssertionError, match="must never spend money"):
        get_backend("anthropic")
    for name in ("api", "live", "anthropic"):
        with pytest.raises(AssertionError):
            get_backend(name)


def test_the_provider_sdk_is_an_optional_dependency() -> None:
    """`make install` and `make test` must work with no provider SDK installed."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    core = pyproject.split("[project.optional-dependencies]")[0]
    assert "anthropic" not in core, "the provider SDK must not be a core dependency"
    assert "anthropic" in pyproject, "the live extra should still declare it"


def test_the_declared_models_match_the_defaults() -> None:
    """base.yaml and DEFAULT_MODELS are two statements of one thing; they must agree."""
    assert load_arm("baseline").models == DEFAULT_MODELS
    assert set(DEFAULT_MODELS) == {r.value for r in Role}


def test_a_model_for_an_unknown_role_is_rejected() -> None:
    """A typo'd role name would silently leave that role on the default model."""
    with pytest.raises(ValidationError):
        RunConfig(arm="x", models={"presidnet_decision": "claude-opus-5"})
    with pytest.raises(ValidationError):
        RunConfig(arm="x", effort="maximum")


def _summary_with(models: dict[str, str], backend: str = "anthropic") -> object:
    """A minimal ArmSummary for exercising the warning logic."""
    return metrics_module.ArmSummary(
        arm="baseline", n=10, rung_distribution={2: 10}, mean_rung=2.0, median_rung=2.0,
        p_nuclear=0.0, declared_panel_size=15, distinct_personas=9, mean_run_coverage=0.6,
        n_opinions=120, out_of_record_rate=0.2, n_citations=80, n_unsupported=0,
        citation_integrity=1.0, backend=backend, grounded=False, cache_enabled=True,
        retrieval_mode="stub", consulted_panel=True, persona_method="m2", models=models,
    )


def test_the_decision_is_never_quietly_served_by_the_cheapest_model() -> None:
    """The decision is the primary metric and ~45% of billable input.

    It may be downgraded, but only by `models_override`, and only loudly. This test is
    written so it cannot pass silently while a smoke test is active: if the override is
    set, the warning machinery must fire; if it is not, the resolved assignment must
    actually keep Opus on the decision.
    """
    config = load_arm("baseline")
    resolved = config.resolved_models()

    # The declared per-role assignment is unaffected by the override either way.
    assert config.models[Role.PRESIDENT_DECISION.value] == "claude-opus-5"

    if config.is_smoke_test:
        assert len(set(resolved.values())) == 1, "an override must pin every role"
        warnings = metrics_module._warnings(_summary_with(resolved))
        assert any("SMOKE TEST" in w for w in warnings), (
            "a run with the decision downgraded must be flagged wherever it is read"
        )
    else:
        assert resolved[Role.PRESIDENT_DECISION.value] == "claude-opus-5"
        assert resolved[Role.PRESIDENT_DECISION.value] != resolved[Role.THEORIST.value]


def test_an_override_supersedes_the_per_role_assignment() -> None:
    """One line has to actually reach every role, or a smoke test would still spend."""
    config = RunConfig(arm="x", models_override="claude-haiku-4-5")
    assert set(config.resolved_models().values()) == {"claude-haiku-4-5"}
    assert set(config.resolved_models()) == {r.value for r in Role}
    assert config.is_smoke_test


def test_removing_the_override_restores_the_per_role_assignment() -> None:
    """The reset has to be one line too, or it will not happen."""
    config = RunConfig(arm="x")
    assert not config.is_smoke_test
    assert config.resolved_models() == DEFAULT_MODELS


def test_a_smoke_test_is_only_flagged_on_a_run_that_cost_something() -> None:
    """Under the mock every role reports "mock" already; the flag is about live runs."""
    all_mock = _summary_with({r.value: "mock" for r in Role}, backend="mock")
    assert not any("SMOKE TEST" in w for w in metrics_module._warnings(all_mock))
    live = _summary_with({r.value: "claude-haiku-4-5" for r in Role})
    assert any("SMOKE TEST" in w for w in metrics_module._warnings(live))
    mixed = _summary_with({**DEFAULT_MODELS})
    assert not any("SMOKE TEST" in w for w in metrics_module._warnings(mixed))


def test_the_cli_warns_before_a_smoke_run_rather_than_after(capsys) -> None:
    """A warning printed after the bill is not a warning."""
    import artsoc.cli as cli_module

    config = RunConfig(arm="baseline", backend="anthropic", models_override="claude-haiku-4-5")
    assert config.is_smoke_test and config.backend != "mock"
    # The guard the CLI uses, asserted directly: the source must test both conditions.
    source = inspect.getsource(cli_module.cmd_run)
    assert "is_smoke_test" in source
    assert source.index("SMOKE TEST") < source.index("write_jsonl"), (
        "the warning must be printed before the run starts"
    )


# ---------------------------------------------------------------------------
# Credentials. A key committed once stays in the history whether or not it is later
# removed, so the protection is asserted rather than assumed.
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True
    ).stdout.strip()


def test_the_env_file_is_ignored_by_git() -> None:
    """Asked of git itself, not of .gitignore's text, so the real behaviour is checked."""
    assert _git("check-ignore", ".env") == ".env", ".env is not ignored"


def test_the_template_is_committed_but_the_env_file_is_not() -> None:
    """The template documents the variables; only the real file holds a key."""
    tracked = set(_git("ls-files").splitlines())
    assert ".env.example" in tracked, "the template should be committed"
    assert ".env" not in tracked, "a real key must never be tracked"


def test_no_tracked_file_contains_an_api_key() -> None:
    """A committed key is leaked even if a later commit removes it.

    The needle is assembled at runtime rather than written as a literal, so this file
    does not match its own scan — which it did on the first run.
    """
    needle = "sk-" + "ant-" + "api"
    for path in _git("ls-files").splitlines():
        full = REPO_ROOT / path
        if not full.is_file():
            continue
        try:
            text = full.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert needle not in text, f"{path} looks like it contains a real API key"


def test_the_template_holds_no_value() -> None:
    """A template with a key in it is not a template."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" in text
    for line in text.splitlines():
        if line.startswith("ANTHROPIC_API_KEY"):
            assert line.split("=", 1)[1].strip() == "", "the template must carry no value"


def test_an_exported_variable_beats_the_file(tmp_path, monkeypatch) -> None:
    """A one-off override on the command line must not be silently replaced by a stale file."""
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-export")
    assert load_dotenv(env) == []
    assert os.environ["ANTHROPIC_API_KEY"] == "from-export"


def test_an_unfilled_template_behaves_as_if_absent(tmp_path, monkeypatch) -> None:
    """An empty value would turn 'no credentials' into a confusing auth failure."""
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert load_dotenv(env) == []
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_the_loader_returns_names_never_values(tmp_path, monkeypatch) -> None:
    """So a caller cannot leak a secret by printing what was loaded."""
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=placeholder-not-a-real-key\n", encoding="utf-8")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert load_dotenv(env) == ["ANTHROPIC_API_KEY"]


def test_a_missing_env_file_is_not_an_error(tmp_path) -> None:
    """Credentials may come from an exported variable or an `ant auth` profile instead."""
    assert load_dotenv(tmp_path / "nope") == []


def test_the_suite_never_reads_the_env_file() -> None:
    """.env is read only when a live backend is constructed, which no test does.

    Read from the module file rather than by inspecting the live class: conftest.py
    replaces `AnthropicBackend.__init__` to keep the suite offline, so introspecting the
    running object would examine the guard instead of the real code.
    """
    source = pathlib.Path(llm_module.__file__).read_text(encoding="utf-8")
    assert source.count("load_dotenv()") == 1, "one call site only"
    body = source.split("class AnthropicBackend:", 1)[1].split("\ndef ", 1)[0]
    assert "load_dotenv()" in body, "the only call site must be inside AnthropicBackend"


def test_the_advisor_may_answer_with_the_marker_it_was_shown() -> None:
    """Naming a real persona in the syntax it was given is formatting, not hallucination.

    The roster is presented as `[[WHO:jervis]]`, and a live model answered with exactly
    that. Treating it as an invented name discarded every selection and filled the panel
    entirely by top-up, which silently threw away the reasoning the arm exists to capture.
    """

    class WrapperBackend:
        name = "wrapper"

        def model_for(self, role):  # noqa: ANN001, ARG002
            return "wrapper-model"

        def complete(self, role, system, prompt, seed_hint):  # noqa: ANN001, ARG002
            ids = PASSAGE_ID and __import__("re").findall(r"\[\[WHO:([a-z_]+)\]\]", prompt)
            return json.dumps(
                {"rationale": "MOCK: reason", "selected": [f"[[WHO:{i}]]" for i in ids[:4]]}
            )

    personas = load_registry()
    client = LLMClient(backend=WrapperBackend(), run_seed=1)
    record = Advisor(client).select(
        PresidentialQuery(text="MOCK: q", concerns=[]),
        AnalyticalQuestion(question_id="q0", text="MOCK: question", tags=["deterrence"]),
        personas,
        4,
        random.Random(0),
    )
    assert record.hallucinated == [], "the wrapper form must not read as invented"
    assert len(record.chosen_by_advisor) == 4
    assert record.topped_up == [], "a fully-honoured selection needs no top-up"
    assert set(record.chosen_by_advisor) <= {p.persona_id for p in personas}


class _EchoBackend:
    """Answers every role with the marker syntax it was shown, in every shape live running
    has produced. Roles it has no echo for fall through to the ordinary mock.

    Deliberate counterpart to the low-rate echoes baked into `MockBackend`: those give the
    whole suite exposure to the failure mode, this makes the coverage certain.
    """

    name = "echo"

    def model_for(self, role: Role) -> str:
        return "echo-model"

    def __init__(self) -> None:
        self._mock = MockBackend()

    def complete(self, role: Role, system: str, prompt: str, seed_hint: str) -> str:
        if role is Role.ADVISOR_COAS:
            actions = [f"[[ACTION:{a}]]" for a in ACTION_ENTRY.findall(prompt)[:3]]
            cites = [f"[[OPINION:{q}:{p}]]" for q, p in OPINION_ENTRY.findall(prompt)[:2]]
            return json.dumps(
                {
                    "note": "MOCK:",
                    "courses": [
                        {
                            "action": action,
                            "rationale": f"MOCK: case, per {cites[0] if cites else 'nothing'}",
                            "supporting_opinions": cites,
                        }
                        for action in actions
                    ],
                }
            )
        if role is Role.PRESIDENT_DECISION and COA_ENTRY.search(prompt):
            coa_id, action = COA_ENTRY.findall(prompt)[1]
            return json.dumps(
                {
                    "chosen_coa_id": f"[[COA:{coa_id}:{action}]]",
                    "action": action,
                    "justification": f"MOCK: because [[COA:{coa_id}:{action}]] was best",
                }
            )
        if role is Role.ADVISOR_SYNTHESIS:
            tag = OPINION_ENTRY.search(prompt)
            cite = f"[[OPINION:{tag.group(1)}:{tag.group(2)}]]" if tag else "[[ACTION:no_action]]"
            return json.dumps(
                {
                    "summary": f"MOCK: summary citing {cite}",
                    "consensus_points": [f"MOCK: point from {cite}"],
                    "minority_positions": [],
                }
            )
        if role is Role.THEORIST:
            return json.dumps(
                {
                    "position": f"MOCK: position {NO_RECORD_MARKER} stated anyway",
                    "reasoning": f"MOCK: reasoning {NO_RECORD_MARKER}",
                    "citations": [],
                    "out_of_record": False,
                    "confidence": 0.5,
                }
            )
        return self._mock.complete(role, system, prompt, seed_hint)


def test_a_course_of_action_may_echo_every_marker_it_was_shown() -> None:
    """The COA path accepts the wrapper form in all three places it has appeared.

    `[[OPINION:...]]` and `[[ACTION:...]]` leaked back from a live model after the same
    defect had already been fixed for `[[WHO:...]]`, because that fix was written for its
    own site. The guard is shared now, so all three shapes are asserted together.
    """
    client = LLMClient(backend=_EchoBackend(), run_seed=1)
    opinions = _opinions_for_coas()
    coas = Advisor(client).propose_coas(
        PresidentialQuery(text="MOCK: q", concerns=[]), opinions
    )

    assert len(coas) == 3
    assert len({c.action for c in coas}) == 3, "wrapped actions must still parse as typed"
    tags = {f"{o.question_id}:{o.persona_id}" for o in opinions}
    for coa in coas:
        assert set(coa.supporting_opinions) <= tags, "a wrapped citation is not an invented one"
        assert "[[" not in coa.rationale, "raw marker syntax must not survive into the record"


def test_the_president_may_echo_the_course_marker_it_was_shown() -> None:
    """Echoing `[[COA:b:...]]` is a formatting difference, not an invalid id.

    Reading it as invalid would burn a retry and then raise, discarding a decision the
    President actually made — the same failure the Advisor's roster echo once caused.
    """
    client = LLMClient(backend=_EchoBackend(), run_seed=1)
    intel = IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate")
    coas = [
        CourseOfAction(coa_id=cid, action=action, rationale="MOCK:")
        for cid, action in zip(
            "abc",
            [ActionType.NO_ACTION, ActionType.PRIVATE_WARNING, ActionType.PUBLIC_STATEMENT],
            strict=True,
        )
    ]
    action = President(client, _doctrine()).decide(intel, None, coas)

    assert action.chosen_coa_id == "b", "the bare id is what the record keeps"
    assert action.action == ActionType.PRIVATE_WARNING
    assert "[[" not in action.justification


def test_marker_syntax_never_survives_into_recorded_prose() -> None:
    """No field an analyst reads carries the host's own bracket syntax.

    Stated over the whole loop rather than per role: the two occurrences of this defect
    were each caught at one site and fixed there, and the second was found by live running
    because nothing asserted the general property.
    """
    record = _run("baseline", seed=7)

    prose = [
        record.intel_brief.summary,
        record.intel_brief.assessed_activity,
        record.action.justification,
        *(o.position for o in record.opinions),
        *(o.reasoning for o in record.opinions),
        *(r.rationale for r in record.routing),
        *(c.rationale for c in record.courses_of_action),
    ]
    if record.advisor_brief is not None:
        prose += [
            record.advisor_brief.summary,
            *record.advisor_brief.consensus_points,
            *record.advisor_brief.minority_positions,
        ]

    offenders = [text for text in prose if "[[" in text]
    assert offenders == [], f"marker syntax reached the record: {offenders[:2]}"


def test_a_theorist_echoing_the_no_record_marker_does_not_keep_it() -> None:
    """`[[CORPUS:none]]` is removed, not unwrapped.

    It names no entity, so the bare word "none" left mid-sentence would read worse than
    the marker it replaced — the one case where stripping is not the same as unwrapping.
    """
    client = LLMClient(backend=_EchoBackend(), run_seed=1)
    persona = load_registry()[0]
    opinion, _ = Theorist(client, persona, "m2", StubRetriever()).opine(
        AnalyticalQuestion(question_id="q0", text="MOCK: question", tags=["deterrence"])
    )

    assert NO_RECORD_MARKER not in opinion.position
    assert NO_RECORD_MARKER not in opinion.reasoning
    assert "none" not in opinion.position.split(), "removed, not unwrapped to its content"
    assert opinion.position.startswith("MOCK:"), "the rest of the answer is untouched"


def test_the_advisors_brief_never_quotes_the_marker_it_cites_with() -> None:
    """The brief is guarded even though its own prompt shows no marker.

    One backend answers every role, and a model that met `[[ACTION:...]]` while writing
    courses of action can reproduce the shape while writing the brief. The brief is what
    the President reads, so raw host syntax there is both unreadable and a sign the model
    is copying structure rather than compressing content. Guarding only the sites whose
    prompts carry a marker is how the second leak reached live running.
    """
    client = LLMClient(backend=_EchoBackend(), run_seed=1)
    brief = Advisor(client).synthesise(
        PresidentialQuery(text="MOCK: q", concerns=[]), _opinions_for_coas()
    )

    assert "[[" not in brief.summary
    assert all("[[" not in point for point in brief.consensus_points)


# ---------------------------------------------------------------------------
# Sweep readiness: provenance in the cache key, retries, failure policy, concurrency.
# ---------------------------------------------------------------------------


def test_two_efforts_do_not_share_cache_entries(tmp_path) -> None:
    """`effort` changes output, so it must change the key.

    Without it a sweep at effort=medium is served entries written at low: the record names
    one setting while the numbers came from another. That is the provenance failure ADR
    0002 fixed for models, and it was still open for generation parameters.
    """

    class Tunable:
        name = "tunable"

        def __init__(self, effort: str) -> None:
            self.effort = effort

        def model_for(self, role):  # noqa: ANN001, ARG002
            return "same-model"

        def generation_signature(self) -> str:
            return f"effort={self.effort}"

        def complete(self, role, system, prompt, seed_hint):  # noqa: ANN001, ARG002
            return json.dumps({"effort": self.effort})

    system = f"{role_marker(Role.THEORIST)} identity"
    low = LLMClient(backend=Tunable("low"), run_seed=1, cache=DiskCache(tmp_path))
    high = LLMClient(backend=Tunable("high"), run_seed=1, cache=DiskCache(tmp_path))
    low.complete(role=Role.THEORIST, system=system, prompt="Q")
    high.complete(role=Role.THEORIST, system=system, prompt="Q")
    assert high.cache_hits == 0, "a different effort must miss the cache"

    again = LLMClient(backend=Tunable("low"), run_seed=2, cache=DiskCache(tmp_path))
    again.complete(role=Role.THEORIST, system=system, prompt="Q")
    assert again.cache_hits == 1, "the same effort must still reuse its own entry"


def test_a_failed_replication_is_recorded_not_silently_dropped() -> None:
    """A distribution over the survivors is biased unless the losses are visible.

    A replication may fail for reasons correlated with its outcome — a long theorist answer
    that exceeded a token limit is not a random sample — so the seeds must be reported.
    """
    config = _mock(load_arm("baseline"))
    failures: list[tuple[int, str]] = []

    calls = {"n": 0}
    real = run_once

    def flaky(cfg, seed, **kw):
        calls["n"] += 1
        if seed == 3:
            raise RuntimeError("simulated transient failure")
        return real(cfg, seed, **kw)

    import artsoc.sim as sim_module

    original = sim_module.run_once
    sim_module.run_once = flaky
    try:
        records = list(sim_module.run_many(config, 4, 1, failures))
    finally:
        sim_module.run_once = original

    assert len(records) == 3, "the sweep must continue past a failure"
    assert [f[0] for f in failures] == [3], "the failing seed must be named"
    assert "simulated transient failure" in failures[0][1]


def test_without_a_failure_list_a_failure_still_raises() -> None:
    """Collecting failures is opt-in; nothing swallows an error by default."""
    import artsoc.sim as sim_module

    original = sim_module.run_once
    sim_module.run_once = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        with pytest.raises(RuntimeError, match="boom"):
            list(sim_module.run_many(_mock(load_arm("baseline")), 2, 1))
    finally:
        sim_module.run_once = original


def test_the_control_arm_is_untouched_by_the_deliberation_stage() -> None:
    """ADR 0008's stage is inside the one `consult_panel` conditional, so `escalation_prior`
    skips it entirely: no lean, no debate, `convene_excomm` unread."""
    record = _run("escalation_prior", 3)
    assert record.secret_lean is None
    assert record.secret_lean_reasoning == ""
    assert record.deliberation == []
    assert record.deliberation_rounds == 0
    # The flag having any value must not change the control record.
    flipped = _mock(load_arm("escalation_prior")).model_copy(
        update={"convene_excomm": True}
    )
    assert run_once(flipped, 3, use_disk_cache=False).model_dump(
        mode="json", exclude={"wall_time_s", "started_at", "config"}
    ) == run_once(_mock(load_arm("escalation_prior")), 3, use_disk_cache=False).model_dump(
        mode="json", exclude={"wall_time_s", "started_at", "config"}
    )


def test_baseline_records_the_lean_but_holds_no_debate() -> None:
    """The lean is recorded on every consulted arm so `baseline` is the no-debate noise
    floor `excomm_debate` is read against (ADR 0008)."""
    record = _run("baseline", 3)
    assert isinstance(rung_for(record.secret_lean), int)
    assert record.secret_lean_coa_id in {c.coa_id for c in record.courses_of_action}
    assert record.deliberation == [] and record.deliberation_rounds == 0


def test_the_excomm_debate_arm_produces_a_debate_and_a_lean() -> None:
    record = _run("excomm_debate", 3)
    roster_ids = {m.member_id for m in load_excomm()}
    assert record.deliberation, "the debate produced no statements"
    assert 1 <= record.deliberation_rounds <= 3
    assert {s.round for s in record.deliberation} <= {1, 2, 3}
    assert all(s.member_id in roster_ids for s in record.deliberation)
    assert isinstance(rung_for(record.secret_lean), int)
    assert any(not s.abstained for s in record.deliberation), "every member abstained"


def test_sim_has_exactly_one_arm_conditional() -> None:
    """`config.consult_panel` is the only branch on arm behaviour in sim.py; the
    deliberation stage lives inside it (ADR 0008), not beside it."""
    import artsoc.sim as sim_module

    source = inspect.getsource(sim_module)
    # One docstring mention, then the same guard twice in code (build_panel, the _consult
    # call). A fourth occurrence would be a second arm conditional.
    assert source.count("config.consult_panel") == 3
    # The deliberation stage branches on `convene_excomm`, but INSIDE `_deliberate`, which
    # only runs on the `consult_panel` path — not as a peer of it in `run_once`.
    assert "config.convene_excomm" in inspect.getsource(sim_module._deliberate)
    assert "config.convene_excomm" not in inspect.getsource(sim_module.run_once)


def test_the_record_is_identical_at_any_concurrency() -> None:
    """The invariant concurrency must not break.

    Theorist calls are fanned out because they cannot see each other, but the record has to
    stay reproducible from a config and a seed. Results are keyed by index and re-sorted,
    so completion order cannot reach the output. The ExComm debate is sequential by
    construction, so `convene_excomm` is exercised here too.
    """
    base = _mock(load_arm("excomm_debate"))
    dumps = []
    for concurrency in (1, 4, 8):
        record = run_once(
            base.model_copy(update={"max_concurrency": concurrency}), 7, use_disk_cache=False
        )
        payload = record.model_dump(mode="json")
        for volatile in ("wall_time_s", "started_at"):
            payload.pop(volatile)
        payload["config"].pop("max_concurrency")
        dumps.append(json.dumps(payload, sort_keys=True))

    assert dumps[0] == dumps[1] == dumps[2], "concurrency changed the record"
    assert json.loads(dumps[0])["opinions"], "no opinions; the comparison would be vacuous"


def test_the_access_matrix_scan_does_not_depend_on_call_order() -> None:
    """`prompts_for` is completion-ordered once the fan-out is concurrent.

    The canary tests scan content rather than sequence, which was incidental until now.
    Asserted so it stays true deliberately rather than by luck.
    """
    source = pathlib.Path(llm_module.__file__).read_text(encoding="utf-8")
    assert "def prompts_for" in source
    client = LLMClient(backend=MockBackend(), run_seed=1)
    system = f"{role_marker(Role.THEORIST)} identity"
    for i in range(3):
        client.complete(role=Role.THEORIST, system=system, prompt=f"Q{i}")
    assert len(client.prompts_for(Role.THEORIST)) == 3
    assert set(client.prompts_for(Role.THEORIST)) == {
        (system, f"Q{i}") for i in range(3)
    }


def test_the_record_counts_retries() -> None:
    """A replication that needed three attempts is different data from one that did not."""
    assert "retries" in RunRecord.model_fields
    record = _run("baseline", 1)
    assert record.retries == 0, "the mock never returns unparseable output"
