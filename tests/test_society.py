"""The citizen audience: schema, the committed sampling frame, and the sampler (ADR 0009).

The audience is a second, structurally different population from both the theorist panel
and the ExComm (ADR 0008): it reads the decision after it is made and reacts to it. Nothing
it produces returns to the President — see `tests/test_access_matrix.py` for the boundary
tests proving that. This file covers what is testable without a backend: the types, the
committed frame, and the sampler.
"""

from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import artsoc.society as society_module
from artsoc.agents import BoundaryViolation, CitizenPanelist
from artsoc.llm import DiskCache, LLMClient, MockBackend, Role
from artsoc.schema import (
    ActionType,
    AudienceRecord,
    Citizen,
    CitizenFailure,
    CitizenResponse,
    IntelBrief,
    PresidentialAction,
    PublicEvent,
    PublicStatement,
    RunRecord,
    public_statement_from,
)
from artsoc.society import Frame, load_frame, sample_citizens


def _minimal_record() -> RunRecord:
    """A minimal, structurally-empty record — only what the schema requires. The
    `_record_with_basis` precedent in `test_markdown_corpus.py`."""
    return RunRecord(
        run_id="fixture-1",
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
        intel_brief=IntelBrief(
            summary="MOCK:", assessed_activity="MOCK:", confidence="moderate"
        ),
        action=PresidentialAction(action=ActionType.NO_ACTION, justification="MOCK:"),
        rung=0,
    )

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _citizen(**overrides) -> dict:
    base = {
        "citizen_id": "c001",
        "region": "northeast",
        "urbanicity": "urban",
        "age_band": "30_44",
        "sex": "f",
        "education": "college",
        "party_id": "independent",
        "weight": 1.0,
    }
    return {**base, **overrides}


def test_public_statement_cannot_carry_a_rung_or_a_coa_id() -> None:
    """It is impossible to construct one carrying them, not merely unpopulated."""
    with pytest.raises(ValidationError):
        PublicStatement(action=ActionType.NO_ACTION, justification="x", chosen_coa_id="a")
    with pytest.raises(ValidationError):
        PublicStatement(action=ActionType.NO_ACTION, justification="x", rung=3)
    with pytest.raises(ValidationError):
        PublicStatement(action=ActionType.NO_ACTION, justification="x", is_nuclear=False)


def test_public_event_has_no_ground_truth_or_collection_fields() -> None:
    """A distinct type from `PerceivedEvent`, so a caller cannot hand the audience the
    state's collection picture by passing the wrong list."""
    fields = PublicEvent.model_fields
    assert "ground_truth_detail" not in fields
    assert "confidence" not in fields
    assert "degraded" not in fields
    assert "source_note" not in fields
    assert "observable_signature" not in fields


def test_public_statement_from_drops_the_coa_id_and_the_computed_fields() -> None:
    action = PresidentialAction(
        action=ActionType.PUBLIC_STATEMENT, justification="a reason", chosen_coa_id="coa-2"
    )
    statement = public_statement_from(action)
    assert statement.action == action.action
    assert statement.justification == action.justification
    assert "chosen_coa_id" not in PublicStatement.model_fields
    assert "rung" not in PublicStatement.model_fields
    assert "is_nuclear" not in PublicStatement.model_fields


def test_citizen_carries_stratum_attributes_and_a_weight_only() -> None:
    citizen = Citizen(**_citizen())
    assert citizen.weight == 1.0
    with pytest.raises(ValidationError):
        Citizen(**_citizen(name="Pat Smith"))
    with pytest.raises(ValidationError):
        Citizen(**_citizen(prominence=0.5))


def test_citizen_response_defaults_to_not_refused() -> None:
    response = CitizenResponse(
        citizen_id="c001",
        approval="approve",
        primary_concern="national_security",
        rationale="MOCK: placeholder",
    )
    assert response.refused is False


def test_citizen_response_rejects_an_unknown_approval_value() -> None:
    with pytest.raises(ValidationError):
        CitizenResponse(
            citizen_id="c001",
            approval="somewhat_approve",
            primary_concern="national_security",
        )


def test_citizen_failure_is_a_reason_not_a_crash() -> None:
    failure = CitizenFailure(citizen_id="c001", reason="timeout")
    assert failure.reason == "timeout"


def test_audience_record_defaults_are_empty_not_missing() -> None:
    """A record with zero citizens sampled (e.g. a misconfigured `audience_size`) should
    still be constructible and legible, not raise for missing fields."""
    record = AudienceRecord(frame="us_1962", sample_seed=1)
    assert record.citizens == []
    assert record.responses == []
    assert record.weighted_approval == {}


def test_a_pre_1_4_0_record_with_no_audience_field_round_trips() -> None:
    """`audience` defaults to `None`, so an existing `out/*.jsonl` line written before ADR
    0009 still loads."""
    payload = _minimal_record().model_dump(mode="json")
    payload.pop("audience", None)
    restored = RunRecord.model_validate(payload)
    assert restored.audience is None


# ---------------------------------------------------------------------------
# society.py: no artsoc.llm import
# ---------------------------------------------------------------------------


def test_society_imports_nothing_from_artsoc_llm() -> None:
    """Same rule as `personas.py`: sampling produces prompt text and stratum data, and
    only `agents.py` sends anything anywhere. Checked against the actual import
    statements, not the prose, since the module's own docstring names `artsoc.llm` while
    explaining the rule."""
    tree = ast.parse(Path(society_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith("artsoc.llm") or name == "artsoc.llm" for name in imported)


# ---------------------------------------------------------------------------
# The committed frame
# ---------------------------------------------------------------------------


def test_the_committed_frame_loads_and_every_dimension_sums_to_one() -> None:
    frame = load_frame("us_1962")
    assert set(frame.dimensions) == {
        "region",
        "urbanicity",
        "age_band",
        "sex",
        "education",
        "party_id",
    }
    for name, categories in frame.dimensions.items():
        assert abs(sum(categories.values()) - 1.0) < 1e-6, name


def test_the_committed_frame_carries_a_held_out_validation_dimension() -> None:
    frame = load_frame("us_1962")
    assert "party_id" in frame.validation_dimensions
    # Held out from construction: a different year's wave, not the construction figure.
    assert frame.validation_dimensions["party_id"] != frame.dimensions["party_id"]


def test_load_frame_raises_on_a_missing_frame(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no sampling frame"):
        load_frame("does_not_exist", root=tmp_path)


def test_load_frame_raises_when_a_dimension_has_no_matching_citizen_field(
    tmp_path: Path,
) -> None:
    """A `Citizen` field with no marginal is not a persona attribute, and a marginal with
    no `Citizen` field is dead data — both directions must fail loudly."""
    frame_dir = tmp_path / "broken"
    frame_dir.mkdir()
    (frame_dir / "strata.yaml").write_text(
        yaml.dump(
            {
                "dimensions": {
                    "region": {"categories": {"north": 0.5, "south": 0.5}},
                    "favourite_colour": {"categories": {"blue": 1.0}},
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="drifted"):
        load_frame("broken", root=tmp_path)


def test_load_frame_raises_when_a_dimension_does_not_sum_to_one(tmp_path: Path) -> None:
    frame_dir = tmp_path / "unbalanced"
    frame_dir.mkdir()
    dims = {
        "region": {"categories": {"a": 0.4, "b": 0.4}},
        "urbanicity": {"categories": {"urban": 0.7, "rural": 0.3}},
        "age_band": {"categories": {"young": 0.5, "old": 0.5}},
        "sex": {"categories": {"female": 0.5, "male": 0.5}},
        "education": {"categories": {"some": 1.0}},
        "party_id": {"categories": {"a": 1.0}},
    }
    (frame_dir / "strata.yaml").write_text(
        yaml.dump({"dimensions": dims}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="sums to"):
        load_frame("unbalanced", root=tmp_path)


# ---------------------------------------------------------------------------
# The sampler
# ---------------------------------------------------------------------------


def test_sample_citizens_is_deterministic_given_the_same_rng_seed() -> None:
    frame = load_frame("us_1962")
    first = sample_citizens(frame, 70, random.Random(11))
    second = sample_citizens(frame, 70, random.Random(11))
    assert [c.model_dump() for c in first.citizens] == [c.model_dump() for c in second.citizens]


def test_sample_citizens_returns_exactly_n_citizens_with_unique_ids() -> None:
    frame = load_frame("us_1962")
    sample = sample_citizens(frame, 70, random.Random(3))
    assert len(sample.citizens) == 70
    ids = {c.citizen_id for c in sample.citizens}
    assert len(ids) == 70


def test_weights_are_positive_and_sum_to_n() -> None:
    frame = load_frame("us_1962")
    sample = sample_citizens(frame, 70, random.Random(5))
    weights = [c.weight for c in sample.citizens]
    assert all(w > 0 for w in weights)
    assert abs(sum(weights) - 70) < 1e-6


@pytest.mark.parametrize(
    "dimension", ["region", "urbanicity", "age_band", "sex", "education", "party_id"]
)
def test_the_weighted_distribution_recovers_the_target_marginal(dimension: str) -> None:
    """Raking is what the sampler is for: the raw draw is noisy at n=70, but the *weighted*
    read must land close to the target — this is the property `AudienceRecord.
    weighted_approval` depends on being true."""
    frame = load_frame("us_1962")
    sample = sample_citizens(frame, 70, random.Random(42))
    total_weight = sum(c.weight for c in sample.citizens)
    weighted_share: dict[str, float] = {}
    for citizen in sample.citizens:
        category = getattr(citizen, dimension)
        weighted_share[category] = weighted_share.get(category, 0.0) + citizen.weight
    weighted_share = {k: v / total_weight for k, v in weighted_share.items()}
    for category, target in frame.dimensions[dimension].items():
        assert abs(weighted_share.get(category, 0.0) - target) < 0.01, (
            dimension,
            category,
        )


def test_stratum_coverage_is_reported_per_dimension() -> None:
    frame = load_frame("us_1962")
    sample = sample_citizens(frame, 70, random.Random(9))
    assert set(sample.stratum_coverage) == set(frame.dimensions)
    for ratio in sample.stratum_coverage.values():
        assert 0.0 <= ratio <= 1.0 + 1e-9


def test_raking_still_terminates_on_a_near_unreachable_target() -> None:
    """A dimension with a near-zero-probability category (small n makes it plausible the
    raw draw never lands on it) must not hang or divide by zero — the iteration cap and
    the `achieved_share > 0` guard in `_rake` bound it."""
    dimensions = {
        "region": {"common": 0.999999, "rare": 0.000001},
        "urbanicity": {"urban": 0.5, "rural": 0.5},
        "age_band": {"young": 0.5, "old": 0.5},
        "sex": {"female": 0.5, "male": 0.5},
        "education": {"some": 0.5, "none": 0.5},
        "party_id": {"a": 0.5, "b": 0.5},
    }
    frame = Frame(name="degenerate", dimensions=dimensions, validation_dimensions={})
    sample = sample_citizens(frame, 5, random.Random(1))
    assert len(sample.citizens) == 5
    assert all(c.weight > 0 for c in sample.citizens)


# ---------------------------------------------------------------------------
# The role never touches the disk cache (ADR 0009)
# ---------------------------------------------------------------------------


def test_a_citizen_call_never_touches_the_disk_cache(tmp_path: Path) -> None:
    """Stronger than `cacheable=False` elsewhere: a citizen's input is the decision and
    its justification, the thing that varies by design, so this role must never be served
    from or written to the disk cache — even with `cache_enabled=True` and the identical
    system/prompt/model repeated."""
    client = LLMClient(
        backend=MockBackend(), run_seed=1, cache=DiskCache(tmp_path), cache_enabled=True
    )
    system = "[[ROLE:citizen]]\nyou are a citizen"
    prompt = "how do you feel about this?"

    client.complete(role=Role.CITIZEN, system=system, prompt=prompt, cacheable=True)
    client.complete(role=Role.CITIZEN, system=system, prompt=prompt, cacheable=True)

    assert client.cache_hits == 0
    assert client.calls == 2


def test_a_non_citizen_call_with_the_same_prompt_does_cache(tmp_path: Path) -> None:
    """Anti-vacuity: the bypass in the prior test is scoped to `Role.CITIZEN`, not a
    disk-cache regression that would make every role miss."""
    client = LLMClient(
        backend=MockBackend(), run_seed=1, cache=DiskCache(tmp_path), cache_enabled=True
    )
    system = "[[ROLE:theorist]]\nyou are a theorist"
    prompt = "what do you think?"

    client.complete(role=Role.THEORIST, system=system, prompt=prompt, cacheable=True)
    client.complete(role=Role.THEORIST, system=system, prompt=prompt, cacheable=True)

    assert client.cache_hits == 1


# ---------------------------------------------------------------------------
# The prompt-build-time guard (ADR 0009). This is the same `assert_decontextualised`
# `agents.py` already uses for the President's query, called here in its other
# direction: guarding what is about to be *sent* to the citizen.
# ---------------------------------------------------------------------------


def test_a_planted_forbidden_token_makes_the_citizen_call_raise() -> None:
    """A leak that is quietly cleaned up is a leak nobody finds out about — this proves
    the guard actually raises `BoundaryViolation` rather than silently passing, by
    planting a token the built prompt is guaranteed to carry (the citizen's own region,
    which `build_citizen_identity_prompt` always renders)."""
    citizen = Citizen(**_citizen(region="northeast"))
    panelist = CitizenPanelist(LLMClient(backend=MockBackend(), run_seed=1), citizen)
    statement = PublicStatement(action=ActionType.NO_ACTION, justification="MOCK:")

    with pytest.raises(BoundaryViolation, match="citizen"):
        panelist.respond([], statement, forbidden_tokens=["northeast"])


def test_with_no_forbidden_token_planted_the_same_call_succeeds() -> None:
    """Anti-vacuity: the guard is not simply raising unconditionally."""
    citizen = Citizen(**_citizen(region="northeast"))
    panelist = CitizenPanelist(LLMClient(backend=MockBackend(), run_seed=1), citizen)
    statement = PublicStatement(action=ActionType.NO_ACTION, justification="MOCK:")

    response = panelist.respond([], statement, forbidden_tokens=["some_other_theorist"])
    assert response.citizen_id == "c001"
