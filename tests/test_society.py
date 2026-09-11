"""The citizen audience: schema, the committed sampling frame, and the sampler (ADR 0009).

The audience is a second, structurally different population from both the theorist panel
and the ExComm (ADR 0008): it reads the decision after it is made and reacts to it. Nothing
it produces returns to the President — see `tests/test_access_matrix.py` for the boundary
tests proving that. This file covers what is testable without a backend: the types, the
committed frame, and the sampler.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
