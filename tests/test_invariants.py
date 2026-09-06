"""The project's integrity guarantees, written as the invariant each one protects.

Never edit a test here to make a change pass. If an invariant genuinely needs to change,
say so and change the test on its own, deliberately — not alongside the code that it
would otherwise have caught.
"""

from __future__ import annotations

import ast
import inspect
import json
import random

import pytest
from pydantic import ValidationError

from artsoc import personas as personas_module
from artsoc.llm import (
    MOCK_PREFIX,
    NO_RECORD_MARKER,
    DiskCache,
    LLMClient,
    MockBackend,
    Role,
    get_backend,
    role_marker,
)
from artsoc.personas import (
    Persona,
    Registry,
    build_persona_prompt,
    load_registry,
    panel_coverage,
    route,
    synthetic_panel,
)
from artsoc.schema import (
    NUCLEAR_ACTIONS,
    NUCLEAR_THRESHOLD,
    RUNG,
    TAG_SET,
    ActionType,
    AnalyticalQuestion,
    PerceivedEvent,
    PresidentialAction,
    WorldEvent,
    rung_for,
)
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


def test_there_is_no_live_backend_in_phase_one() -> None:
    """No network, no API key, no provider dependency until the loop is pinned down."""
    assert get_backend("mock").name == "mock"
    with pytest.raises(NotImplementedError):
        get_backend("api")
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
    for persona in load_registry():
        for method in ("m1", "m2", "m3"):
            prompt = build_persona_prompt(persona, method).lower()
            for token in forbidden:
                assert token not in prompt, f"{method} prompt leaked {token!r}"


def test_m2_without_a_record_signals_the_escape_hatch() -> None:
    """Empty retrieval must make out_of_record available, not silently invent a record."""
    persona = load_registry()[0]
    assert NO_RECORD_MARKER in build_persona_prompt(persona, "m2", record_block="")
    assert NO_RECORD_MARKER not in build_persona_prompt(
        persona, "m2", record_block="[brodie:ch1:1] MOCK: placeholder passage"
    )


def test_m1_offers_no_escape_hatch_and_no_record() -> None:
    """M1 is the name-only baseline; 'out of record' has no meaning without a record."""
    prompt = build_persona_prompt(load_registry()[0], "m1")
    assert "out_of_record" not in prompt
    assert NO_RECORD_MARKER not in prompt


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
