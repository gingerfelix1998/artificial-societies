"""The ExComm roster: the deliberative committee's personas (ADR 0008).

Members are 1962-*shaped*, not the historical individuals — a prompt carries an
institutional seat and an anonymised disposition, never a real name, for the same
anti-leakage reason the scenario is 'Nation A / Nation B'. The real-name mapping lives in
`docs/excomm/roster-key.md` for maintainers and must never reach the code path or a prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from artsoc.personas import (
    EXCOMM_REGISTRY_PATH,
    ExCommMember,
    build_excomm_identity_prompt,
    excomm_seat_title,
    load_excomm,
)

ROSTER_KEY = Path(__file__).resolve().parents[1] / "docs" / "excomm" / "roster-key.md"


def _real_names() -> set[str]:
    """Every real name (and bare surname) from the roster-key table's figure column."""
    names: set[str] = set()
    for line in ROSTER_KEY.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0].startswith("---"):
            continue
        figure = cells[2]
        if not figure or figure.lower().startswith("figure"):
            continue
        names.add(figure)
        for part in figure.replace(".", "").split():
            if len(part) > 3:  # skip initials like "F." / "C."
                names.add(part)
    return names


def _member(**overrides) -> dict:
    base = {
        "member_id": "defense_secretary",
        "role_title": "Secretary of Defense",
        "disposition": "Analytical, revises hard under evidence.",
        "beliefs": ["Force needs a political objective."],
        "backing_literature": "memoirs",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def test_member_id_must_be_a_slug() -> None:
    """The id keys the deliberation record; a real name there would leak into the output."""
    with pytest.raises(ValidationError, match=r"\[a-z0-9_\]\+"):
        ExCommMember(**_member(member_id="Robert McNamara"))
    with pytest.raises(ValidationError):
        ExCommMember(**_member(member_id="Defense-Secretary"))


def test_a_member_with_no_beliefs_is_rejected() -> None:
    """No standing positions means no voice in the debate."""
    with pytest.raises(ValidationError, match="no standing positions"):
        ExCommMember(**_member(beliefs=[]))
    with pytest.raises(ValidationError):
        ExCommMember(**_member(beliefs=["   ", ""]))


def test_the_model_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ExCommMember(**_member(name="Robert McNamara"))


# ---------------------------------------------------------------------------
# The committed roster
# ---------------------------------------------------------------------------


def test_the_committed_roster_loads_and_is_well_formed() -> None:
    members = load_excomm()
    assert len(members) >= 8, "a committee of fewer than eight is not an ExComm"
    ids = [m.member_id for m in members]
    assert len(ids) == len(set(ids)), "member ids must be unique"
    for m in members:
        assert re.match(r"^[a-z0-9_]+$", m.member_id)
        assert m.beliefs, f"{m.member_id} has no standing positions"
        assert m.disposition.strip(), f"{m.member_id} has no disposition"


def test_no_committed_member_field_carries_a_real_name() -> None:
    """The registry file itself must be name-free — not just the prompts built from it."""
    raw = EXCOMM_REGISTRY_PATH.read_text(encoding="utf-8")
    hits = sorted(n for n in _real_names() if re.search(rf"\b{re.escape(n)}\b", raw))
    assert hits == [], f"data/excomm/registry.yaml carries real names: {hits}"


def test_the_roster_key_actually_lists_names() -> None:
    """Anti-vacuity: the leak checks below are only meaningful if names were extracted."""
    names = _real_names()
    assert len(names) >= 10 and "McNamara" in names


# ---------------------------------------------------------------------------
# The identity prompt
# ---------------------------------------------------------------------------


def test_the_identity_prompt_carries_disposition_beliefs_and_the_abstention_rule() -> None:
    member = load_excomm()[0]
    prompt = build_excomm_identity_prompt(member)
    assert member.disposition.split(".")[0] in prompt
    assert member.beliefs[0] in prompt
    assert member.role_title.split("—")[0].strip() in prompt
    assert "abstain" in prompt.lower(), "a member must be told abstaining is allowed"
    assert "named historical episode" in prompt, "ADR 0005-style constraint must be present"
    assert "You do not choose the course of action" in prompt


def test_no_identity_prompt_of_any_member_carries_a_real_name() -> None:
    names = _real_names()
    for member in load_excomm():
        prompt = build_excomm_identity_prompt(member)
        hits = sorted(n for n in names if re.search(rf"\b{re.escape(n)}\b", prompt))
        assert hits == [], f"{member.member_id}'s identity prompt carries real names: {hits}"


def test_the_identity_prompt_is_stable_across_the_debate() -> None:
    """It carries no situation and no round, so it does not change turn to turn."""
    member = load_excomm()[0]
    assert build_excomm_identity_prompt(member) == build_excomm_identity_prompt(member)


def test_load_excomm_raises_on_a_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="no ExComm roster"):
        load_excomm(tmp_path / "nope.yaml")


def test_excomm_seat_title_is_the_role_title_up_to_its_own_em_dash() -> None:
    """ADR 0010. `role_title` carries the seat plus a clause on what it does, for the
    identity prompt; a display label wants just the seat, and this is the one function
    every display call site shares so they cannot drift apart on how they trim it."""
    for member in load_excomm():
        assert "—" not in excomm_seat_title(member)
        assert member.role_title.startswith(excomm_seat_title(member))
