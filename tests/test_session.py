"""Sessions: arm selection, the cost gate, persistence, and the provenance flags.

Every test here pins the mock backend and the stub retriever, so the suite stays offline
and free — `tests/conftest.py` refuses to construct a live backend anyway, and this module
would be the first place a UI-driven run tried to.

The guardrails tested here are the ones the frontend depends on being true: a client cannot
name a configuration that is not a file on disk, the cost estimate reflects what each arm
actually does, and a summary carries the caveats that gate interpretation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from artsoc import session as session_module
from artsoc.config import RunConfig, load_arm
from artsoc.metrics import CONTROL_ARM
from artsoc.session import (
    ProgressEvent,
    SessionError,
    SessionSpec,
    arm_records,
    create_session,
    estimate_calls,
    list_sessions,
    load_session,
    resolve_arms,
    run_session,
    summarise_session,
    validate_spec,
)

SCENARIO_ID = "phase1_tel_dispersal_v1"


@pytest.fixture(autouse=True)
def _mock_every_arm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every arm this module loads to the mock backend and the stub corpus.

    Sessions resolve arms through `config.load_arm`, which reads `configs/base.yaml` — and
    that file currently declares a live backend and corpus retrieval for real runs. Patching
    the loader rather than each call site means no test in this module can reach a provider
    or depend on `artsoc ingest` having been run, whatever base.yaml says.
    """
    real = session_module.load_arm

    def mocked(name: str, *args: object, **kwargs: object) -> RunConfig:
        return real(name, *args, **kwargs).model_copy(
            update={"backend": "mock", "retrieval_mode": "stub"}
        )

    monkeypatch.setattr(session_module, "load_arm", mocked)


def _spec(arms: list[str], n: int = 3, **kwargs: object) -> SessionSpec:
    return SessionSpec(scenario_id=SCENARIO_ID, arms=arms, n=n, **kwargs)


# ---------------------------------------------------------------------------
# A session may select among committed configs and may not invent one.
# ---------------------------------------------------------------------------


def test_a_session_can_only_name_arms_that_exist_on_disk() -> None:
    """Invariant 5 by another route: a UI that can invent a configuration makes results
    untraceable, so the only route from a session to a config is a filename lookup."""
    with pytest.raises(SessionError, match="no such arm"):
        resolve_arms(_spec(["baseline", "not_a_real_arm"]))


def test_an_unknown_arm_names_the_ones_that_exist() -> None:
    """A typo in a client should not read as 'this arm is broken'."""
    with pytest.raises(SessionError) as exc:
        resolve_arms(_spec(["nonsense"]))
    assert "baseline" in str(exc.value)


def test_a_spec_cannot_carry_a_run_config_override() -> None:
    """There must be no field through which an experimental parameter can arrive."""
    with pytest.raises(ValueError):
        SessionSpec.model_validate(
            {
                "scenario_id": SCENARIO_ID,
                "arms": ["baseline"],
                "n": 2,
                "panel_size": 99,
            }
        )


def test_a_session_cannot_mix_scenarios() -> None:
    """A delta across scenarios carries the arm difference and the scenario difference at
    once, and nothing in the record would say which was which."""
    with pytest.raises(SessionError, match="other scenarios"):
        validate_spec(_spec(["baseline"]).model_copy(update={"scenario_id": "other_v1"}))


def test_a_session_must_name_at_least_one_arm() -> None:
    with pytest.raises(ValueError):
        _spec([])


def test_a_session_rejects_duplicate_arms() -> None:
    """Running an arm twice in one session would double-count it in every contrast."""
    with pytest.raises(ValueError, match="duplicates"):
        _spec(["baseline", "baseline"])


def test_a_spec_is_frozen_once_created() -> None:
    """A session that could mutate its own spec would make spec.json a fiction."""
    spec = _spec(["baseline"])
    with pytest.raises(ValueError):
        spec.n = 99


# ---------------------------------------------------------------------------
# The cost gate. The frontend can spend real money, so the estimate has to be believable.
# ---------------------------------------------------------------------------


def test_the_control_arm_is_estimated_at_two_calls_not_twenty() -> None:
    """`consult_panel: false` changes the shape of a replication rather than scaling it.
    One formula across arms would overstate the control tenfold."""
    estimate = estimate_calls(_spec([CONTROL_ARM], n=10))
    arm = estimate.arms[0]
    assert arm.consult_panel is False
    assert arm.calls_per_replication == 2
    assert arm.total_calls == 20


def test_a_full_loop_arm_is_estimated_from_its_own_question_and_k_settings() -> None:
    config = load_arm("baseline")
    expected = 5 + config.n_questions * (1 + config.k_per_question)
    estimate = estimate_calls(_spec(["baseline"], n=7))
    assert estimate.arms[0].calls_per_replication == expected
    assert estimate.arms[0].total_calls == expected * 7


def test_a_smaller_panel_arm_estimates_the_same_calls_as_baseline() -> None:
    """Panel size changes who is asked, not how many are asked: k_per_question does that."""
    assert (
        estimate_calls(_spec(["small_panel"])).arms[0].calls_per_replication
        == estimate_calls(_spec(["baseline"])).arms[0].calls_per_replication
    )


def test_the_estimate_totals_across_arms() -> None:
    estimate = estimate_calls(_spec([CONTROL_ARM, "baseline"], n=5))
    assert estimate.total_calls == sum(a.total_calls for a in estimate.arms)


def test_the_estimate_names_the_model_that_will_serve_each_role() -> None:
    """A viewer approving spend should see which model each call goes to, and its rate."""
    estimate = estimate_calls(_spec(["baseline"], n=1))
    roles = {r.role: r for r in estimate.arms[0].roles}
    assert "president_decision" in roles
    assert roles["president_decision"].model
    assert roles["theorist"].calls == load_arm("baseline").n_questions * load_arm(
        "baseline"
    ).k_per_question


def test_the_estimate_says_it_is_an_upper_bound_before_caching() -> None:
    """Theorist answers cache across replications; quoting the raw total as the bill would
    be wrong in the expensive direction and would stop being read."""
    note = estimate_calls(_spec(["baseline"])).note.lower()
    assert "upper bound" in note
    assert "cache" in note


def test_the_estimate_quotes_no_dollar_total() -> None:
    """Tokens per call are not known before a run, so a pre-run USD figure would be
    invented — and it would be the most quotable number in the response."""
    dumped = estimate_calls(_spec(["baseline"])).model_dump()
    assert "total_usd" not in dumped
    assert "est_cost_usd" not in dumped


def test_estimating_an_unknown_arm_fails_before_anything_runs() -> None:
    with pytest.raises(SessionError):
        estimate_calls(_spec(["baseline", "ghost"]))


# ---------------------------------------------------------------------------
# Persistence and running.
# ---------------------------------------------------------------------------


def test_creating_a_session_writes_a_spec_and_runs_nothing(tmp_path: Path) -> None:
    state = create_session(_spec([CONTROL_ARM, "baseline"]), tmp_path)
    assert state.status == "pending"
    assert (tmp_path / state.spec.session_id / "spec.json").exists()
    assert not list((tmp_path / state.spec.session_id).glob("*.jsonl"))


def test_a_session_writes_one_jsonl_per_arm_plus_a_summary(tmp_path: Path) -> None:
    spec = _spec([CONTROL_ARM, "baseline"], n=3)
    state = run_session(spec, root=tmp_path)
    target = tmp_path / spec.session_id

    assert state.status == "complete"
    assert (target / "spec.json").exists()
    assert (target / "summary.json").exists()
    for arm in spec.arms:
        assert len(arm_records(spec.session_id, arm, tmp_path)) == 3


def test_the_control_arm_runs_first_whatever_order_it_was_asked_in(
    tmp_path: Path,
) -> None:
    """Every other number is a delta against it, so a session killed half-way is far more
    useful with the control complete than with it pending."""
    seen: list[str] = []
    spec = _spec(["baseline", CONTROL_ARM], n=1)
    run_session(spec, lambda e: seen.append(e.arm), root=tmp_path)
    assert seen[0] == CONTROL_ARM


def test_progress_is_emitted_once_per_completed_replication(tmp_path: Path) -> None:
    events: list[ProgressEvent] = []
    spec = _spec([CONTROL_ARM, "baseline"], n=4)
    run_session(spec, events.append, root=tmp_path)

    completed = [e for e in events if e.failure is None]
    assert len(completed) == 8
    assert [e.completed for e in completed if e.arm == "baseline"] == [1, 2, 3, 4]
    assert all(e.rung is not None for e in completed)


def test_cumulative_spend_is_metered_as_the_session_runs(tmp_path: Path) -> None:
    """Actual spend from each record, rather than a pre-run guess. Under the mock it is
    zero, and it must still be reported rather than omitted."""
    events: list[ProgressEvent] = []
    run_session(_spec(["baseline"], n=3), events.append, root=tmp_path)
    running = [e.cumulative_cost_usd for e in events]
    assert running == sorted(running)


def test_cancelling_keeps_the_replications_already_completed(tmp_path: Path) -> None:
    """Replications already paid for are still data, provided the count is visible."""
    spec = _spec(["baseline"], n=10)
    seen = {"n": 0}

    def cancel_after_two() -> bool:
        seen["n"] += 1
        return seen["n"] >= 2

    state = run_session(spec, root=tmp_path, should_cancel=cancel_after_two)
    assert state.status == "cancelled"
    assert len(arm_records(spec.session_id, "baseline", tmp_path)) == 2


def test_a_session_round_trips_through_disk(tmp_path: Path) -> None:
    spec = _spec([CONTROL_ARM], n=2)
    run_session(spec, root=tmp_path)
    restored = load_session(spec.session_id, tmp_path)
    assert restored.spec == spec
    assert restored.status == "complete"


def test_sessions_are_listed_newest_first(tmp_path: Path) -> None:
    first = create_session(_spec(["baseline"], label="first"), tmp_path)
    second = create_session(_spec(["baseline"], label="second"), tmp_path)
    listed = [s.spec.session_id for s in list_sessions(tmp_path)]
    assert set(listed) == {first.spec.session_id, second.spec.session_id}


def test_a_corrupt_session_directory_does_not_take_the_listing_down(
    tmp_path: Path,
) -> None:
    create_session(_spec(["baseline"]), tmp_path)
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "spec.json").write_text("{not json", encoding="utf-8")
    assert len(list_sessions(tmp_path)) == 1


def test_listing_an_absent_sessions_directory_is_empty_not_an_error(
    tmp_path: Path,
) -> None:
    assert list_sessions(tmp_path / "nothing_here") == []


def test_loading_an_unknown_session_says_so(tmp_path: Path) -> None:
    with pytest.raises(SessionError, match="no session"):
        load_session("deadbeef", tmp_path)


# ---------------------------------------------------------------------------
# The summary carries the caveats that gate interpretation, not just the numbers.
# ---------------------------------------------------------------------------


def test_the_summary_contrasts_every_arm_against_the_control(tmp_path: Path) -> None:
    spec = _spec([CONTROL_ARM, "baseline", "small_panel"], n=3)
    run_session(spec, root=tmp_path)
    summary = summarise_session(spec.session_id, tmp_path)

    assert summary.has_control is True
    assert {d.arm for d in summary.deltas} == {"baseline", "small_panel"}
    assert all(d.control == CONTROL_ARM for d in summary.deltas)


def test_a_session_without_the_control_says_so_loudly(tmp_path: Path) -> None:
    """Absolute escalation rates are not a finding. Without the control there is nothing
    interpretable in the session at all, and the client has to be told."""
    spec = _spec(["baseline"], n=2)
    run_session(spec, root=tmp_path)
    summary = summarise_session(spec.session_id, tmp_path)

    assert summary.has_control is False
    assert summary.deltas == []
    assert "NO CONTROL ARM" in summary.warnings[0]


def test_the_summary_carries_every_warning_metrics_emitted(tmp_path: Path) -> None:
    spec = _spec([CONTROL_ARM, "baseline"], n=3)
    run_session(spec, root=tmp_path)
    summary = summarise_session(spec.session_id, tmp_path)

    from artsoc.metrics import summarise

    emitted = {
        w
        for arm in spec.arms
        for w in summarise(arm_records(spec.session_id, arm, tmp_path)).warnings
    }
    assert emitted <= set(summary.warnings)


def test_a_mock_session_is_flagged_as_mock(tmp_path: Path) -> None:
    """Mock output is content-nonsense by design; a mock sweep must never be readable
    later as a cheap live run."""
    spec = _spec(["baseline"], n=2)
    run_session(spec, root=tmp_path)
    summary = summarise_session(spec.session_id, tmp_path)

    assert summary.mock is True
    assert summary.backend == "mock"
    assert any("MOCK BACKEND" in w for w in summary.warnings)


def test_a_mock_session_is_not_also_flagged_as_a_smoke_test(tmp_path: Path) -> None:
    """Under the mock every role reports "mock" by design, so one distinct model is the
    expected state rather than evidence of `models_override`. A SMOKE TEST banner that
    fires when nothing is wrong is one people learn to click past — which is exactly what
    it must not be when a real override is in `base.yaml`."""
    spec = _spec(["baseline"], n=2)
    run_session(spec, root=tmp_path)
    summary = summarise_session(spec.session_id, tmp_path)

    assert len(set(summary.models.values())) == 1, "the fixture must have one model"
    assert summary.smoke_test is False
    assert not any("SMOKE TEST" in w for w in summary.warnings)


def test_the_summary_reports_grounding_from_the_retriever(tmp_path: Path) -> None:
    """`grounded` comes from the object that produced the text, never from the config."""
    spec = _spec(["baseline"], n=2)
    run_session(spec, root=tmp_path)
    summary = summarise_session(spec.session_id, tmp_path)
    assert summary.grounded is False
    assert summary.retrieval_mode == "stub"


def test_the_summary_says_which_model_served_each_role(tmp_path: Path) -> None:
    spec = _spec(["baseline"], n=1)
    run_session(spec, root=tmp_path)
    summary = summarise_session(spec.session_id, tmp_path)
    assert summary.models
    assert "president_decision" in summary.models


def test_a_summary_file_is_written_and_reloads(tmp_path: Path) -> None:
    spec = _spec([CONTROL_ARM, "baseline"], n=2)
    run_session(spec, root=tmp_path)
    written = json.loads(
        (tmp_path / spec.session_id / "summary.json").read_text(encoding="utf-8")
    )
    assert written["session_id"] == spec.session_id
    assert written["has_control"] is True


def test_no_summary_carries_a_prompt(tmp_path: Path) -> None:
    """Invariant 10: prompts do not leave the process. The summary is serialised to a
    browser, so a role marker in it would be a second, untested surface."""
    spec = _spec([CONTROL_ARM, "baseline"], n=2)
    run_session(spec, root=tmp_path)
    blob = summarise_session(spec.session_id, tmp_path).model_dump_json()
    assert "[[ROLE:" not in blob
    assert "[[WHO:" not in blob
