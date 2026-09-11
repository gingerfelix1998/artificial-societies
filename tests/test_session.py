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
    CHAT_TURN_CAP,
    ChatTurn,
    ProgressEvent,
    SessionError,
    SessionSpec,
    analysis_path,
    analysis_payload,
    arm_records,
    ask_analysis,
    chat_path,
    create_session,
    ensure_analysis,
    estimate_calls,
    list_sessions,
    load_analysis,
    load_chat,
    load_session,
    resolve_arms,
    run_session,
    send_citizen_chat_message,
    send_excomm_chat_message,
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
    # Seven fixed calls: intel, president_query, advisor_questions, advisor_synthesis,
    # advisor_coas (ADR 0006), president_lean (ADR 0008), president_decision. Plus
    # per-question advisor_selection and per-(question, k) theorist calls.
    expected = 7 + config.n_questions * (1 + config.k_per_question)
    estimate = estimate_calls(_spec(["baseline"], n=7))
    assert estimate.arms[0].calls_per_replication == expected
    assert estimate.arms[0].total_calls == expected * 7


def test_the_excomm_debate_arm_estimate_bounds_the_actual_loop() -> None:
    """The upper bound must be >= what a mock run actually makes (ADR 0008)."""
    from artsoc.personas import load_excomm
    from artsoc.sim import run_once

    config = load_arm("excomm_debate")
    roster = config.excomm_size or len(load_excomm())
    est = estimate_calls(_spec(["excomm_debate"], n=1)).arms[0]
    by_role = {r.role: r.calls for r in est.roles}
    assert by_role["excomm_member"] == roster * config.deliberation_max_rounds
    assert by_role["president_chair"] == config.deliberation_max_rounds
    assert by_role["president_lean"] == 1

    actual = run_once(
        config.model_copy(update={"backend": "mock", "retrieval_mode": "stub"}),
        3,
        use_disk_cache=False,
    )
    assert actual.llm_calls <= est.calls_per_replication, "the estimate under-bounds the loop"


def test_the_audience_d1_arm_estimate_bounds_the_actual_loop() -> None:
    """The upper bound must be >= what a mock run actually makes (ADR 0009). Also proves
    the audience call count is added on top of the panel arm's own, not in place of it."""
    from artsoc.sim import run_once

    config = load_arm("audience_d1")
    est = estimate_calls(_spec(["audience_d1"], n=1)).arms[0]
    by_role = {r.role: r.calls for r in est.roles}
    assert by_role["citizen"] == config.audience_size
    assert est.calls_per_replication > config.audience_size, (
        "the estimate must add the citizen calls on top of the panel arm's own"
    )

    actual = run_once(
        config.model_copy(update={"backend": "mock", "retrieval_mode": "stub"}),
        3,
        use_disk_cache=False,
    )
    assert actual.llm_calls <= est.calls_per_replication, "the estimate under-bounds the loop"


def test_the_control_arm_estimate_grows_when_the_audience_is_turned_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`audience_enabled` is added unconditionally on `consult_panel`, so it must also
    show up on the two-call control arm's estimate."""
    real = session_module.load_arm

    def mocked(name: str, *args: object, **kwargs: object) -> RunConfig:
        return real(name, *args, **kwargs).model_copy(
            update={"backend": "mock", "retrieval_mode": "stub", "audience_enabled": True}
        )

    monkeypatch.setattr(session_module, "load_arm", mocked)
    audience_size = load_arm(CONTROL_ARM).audience_size
    estimate = estimate_calls(_spec([CONTROL_ARM], n=1))
    arm = estimate.arms[0]
    assert arm.calls_per_replication == 2 + audience_size


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


# ---------------------------------------------------------------------------
# Session-level interpretation. The figures are the finding; this reads them and adds
# nothing, so what it is allowed to see matters more than what it says.
# ---------------------------------------------------------------------------


def _analysed(tmp_path: Path, arms: list[str] | None = None) -> tuple[str, Path]:
    spec = _spec(arms or [CONTROL_ARM, "baseline"], n=3)
    run_session(spec, root=tmp_path)
    return spec.session_id, tmp_path


def test_the_analysis_payload_carries_figures_and_nothing_else(tmp_path: Path) -> None:
    """It is assembled from computed views, none of which holds a record, a prompt or the
    host's truth — so it cannot carry one by accident. Scanned anyway, because the point of
    the access-matrix suite is that a path nobody anticipated is the one that leaks."""
    session_id, root = _analysed(tmp_path)
    blob = json.dumps(analysis_payload(session_id, "baseline", root))

    assert "host_ground_truth" not in blob
    assert "[[ROLE:" not in blob and "[[WHO:" not in blob
    assert "call_log" not in blob
    # The record's own free text is absent: the payload is summary statistics, so a
    # justification or a theorist's position appearing in it would mean a view leaked one.
    assert "justification" not in blob
    assert "reasoning" not in blob
    # ADR 0008: the lean's prose reason is host-only; only the aggregate shift is exposed.
    assert "secret_lean_reasoning" not in blob
    assert "mean_lean_shift" in blob
    # ADR 0009: a citizen's rationale is per-record free text; only the aggregate share
    # is exposed.
    assert "rationale" not in blob
    assert "weighted_approval" in blob


def test_the_analysis_payload_never_carries_a_citizens_rationale(tmp_path: Path) -> None:
    """Anti-vacuity for the check above: run an arm that actually produces citizen
    rationale text, and confirm none of it reached the payload."""
    session_id, root = _analysed(tmp_path, arms=[CONTROL_ARM, "audience_d1"])
    records = arm_records(session_id, "audience_d1", root)
    rationales = [
        r.rationale
        for record in records
        if record.audience is not None
        for r in record.audience.responses
        if r.rationale
    ]
    assert rationales, "no rationale text was produced; the scan proves nothing"

    blob = json.dumps(analysis_payload(session_id, "audience_d1", root))
    for rationale in rationales:
        assert rationale not in blob
    assert "n_with_audience" in blob


def test_the_analysis_payload_states_whether_a_control_was_run(tmp_path: Path) -> None:
    """Without the control there is no interpretable quantity, and the reader has to be
    told rather than left to infer it from a missing key."""
    with_control, root = _analysed(tmp_path)
    payload = analysis_payload(with_control, "baseline", root)
    assert payload["control_arm_was_run"] is True
    assert payload["contrast_against_control"]["control"] == CONTROL_ARM

    alone = _spec(["baseline"], n=2)
    run_session(alone, root=root)
    solo = analysis_payload(alone.session_id, "baseline", root)
    assert solo["control_arm_was_run"] is False
    assert solo["contrast_against_control"] is None


def test_the_analysis_payload_carries_every_diagnostic(tmp_path: Path) -> None:
    """Each warning gates how the numbers may be read, so the reader must see them all."""
    session_id, root = _analysed(tmp_path)
    payload = analysis_payload(session_id, "baseline", root)
    assert any("MOCK BACKEND" in w for w in payload["diagnostics"])


def test_an_analysis_is_generated_once_and_then_served_from_disk(tmp_path: Path) -> None:
    """A reading that changed on refresh would not be a record, and would be billed twice."""
    session_id, root = _analysed(tmp_path)

    first = ensure_analysis(session_id, "baseline", root)
    assert first is not None and first.sentences
    assert analysis_path(session_id, "baseline", root).exists()

    second = ensure_analysis(session_id, "baseline", root)
    assert second == first


def test_an_analysis_is_labelled_interpretation_rather_than_a_finding(
    tmp_path: Path,
) -> None:
    session_id, root = _analysed(tmp_path)
    analysis = ensure_analysis(session_id, "baseline", root)
    assert analysis is not None
    assert "not a finding" in analysis.caveat.lower()
    assert "control" in analysis.caveat.lower()


def test_no_analysis_is_generated_by_running_a_session(tmp_path: Path) -> None:
    """A sweep runs every arm; a reader opens one. Summarising during the sweep would bill
    for readings nobody asked for."""
    session_id, root = _analysed(tmp_path)
    for arm in (CONTROL_ARM, "baseline"):
        assert not analysis_path(session_id, arm, root).exists()
        assert load_analysis(session_id, arm, root).analysis is None


def test_asking_the_same_question_twice_is_answered_from_disk(tmp_path: Path) -> None:
    """Each question is a billed call. Charging twice for a difference in capitalisation
    would be charging for a capitalisation."""
    session_id, root = _analysed(tmp_path)

    first = ask_analysis(session_id, "baseline", "Did the panel change the outcome?", root)
    assert first is not None and first.answer

    again = ask_analysis(session_id, "baseline", "  did THE panel   change the outcome? ", root)
    assert again is not None
    assert again.answer == first.answer
    assert len(load_analysis(session_id, "baseline", root).answers) == 1


def test_a_different_question_is_stored_separately(tmp_path: Path) -> None:
    session_id, root = _analysed(tmp_path)
    ask_analysis(session_id, "baseline", "Did the panel change the outcome?", root)
    ask_analysis(session_id, "baseline", "Which theorists grounded the chosen option?", root)
    assert len(load_analysis(session_id, "baseline", root).answers) == 2


def test_an_empty_question_is_refused_before_anything_is_spent(tmp_path: Path) -> None:
    session_id, root = _analysed(tmp_path)
    with pytest.raises(SessionError, match="cannot be empty"):
        ask_analysis(session_id, "baseline", "   ", root)


def test_an_analysis_answer_carries_its_caveat(tmp_path: Path) -> None:
    session_id, root = _analysed(tmp_path)
    answer = ask_analysis(session_id, "baseline", "What drove the distribution?", root)
    assert answer is not None
    assert "not a finding" in answer.caveat.lower()
    assert "feeds" in answer.caveat.lower()


def test_the_analysis_prompt_forbids_reading_an_absolute_rate_as_a_result() -> None:
    """The constraint most likely to be forgotten between reading a number and writing it
    down is stated in the instructions the model is given, not only in the UI around it."""
    from artsoc.narrative import ANALYSIS_INSTRUCTION, ANSWER_INSTRUCTION

    for instruction in (ANALYSIS_INSTRUCTION, ANSWER_INSTRUCTION):
        assert "ONLY THE DELTA AGAINST THE CONTROL IS INTERPRETABLE" in instruction
        assert "not influence" in instruction
        assert "did not determine the action" in instruction


def test_the_analysis_never_acquires_a_role_of_its_own() -> None:
    """A host-side call made after every run has finished is not a participant. Giving it a
    role would put it in the access matrix and imply an agent that never existed."""
    import inspect

    from artsoc import narrative as narrative_module

    source = inspect.getsource(narrative_module)
    assert "Role.THEORIST" in source
    assert not any(
        f"Role.{name}" in source
        for name in ("ANALYST", "INTERPRETER", "JUDGE", "SUMMARISER")
    )


# ---------------------------------------------------------------------------
# Live chat with an ExComm member or a citizen (ADR 0010). Session-directory state, like
# the narrative and the analysis above — never RunRecord, never part of the sweep.
# ---------------------------------------------------------------------------


def _excomm_run(tmp_path: Path):
    spec = _spec(["excomm_debate"], n=1)
    run_session(spec, root=tmp_path)
    record = arm_records(spec.session_id, "excomm_debate", tmp_path)[0]
    return spec.session_id, tmp_path, record


def _audience_run(tmp_path: Path):
    spec = _spec(["audience_d1"], n=1)
    run_session(spec, root=tmp_path)
    record = arm_records(spec.session_id, "audience_d1", tmp_path)[0]
    return spec.session_id, tmp_path, record


def test_an_excomm_chat_reply_persists_and_is_labelled_advisor(tmp_path: Path) -> None:
    session_id, root, record = _excomm_run(tmp_path)
    member_id = record.deliberation[0].member_id

    turn = send_excomm_chat_message(
        session_id, "excomm_debate", record.run_id, member_id, "Why did you argue that?",
        root=root,
    )
    assert turn.role == "advisor"
    assert turn.text.strip()

    history = load_chat(session_id, "excomm", record.run_id, member_id, root=root)
    assert [t.role for t in history] == ["user", "advisor"]
    assert history[0].text == "Why did you argue that?"
    assert history[1] == turn


def test_a_citizen_chat_reply_persists_and_is_labelled_advisor(tmp_path: Path) -> None:
    session_id, root, record = _audience_run(tmp_path)
    citizen_id = record.audience.citizens[0].citizen_id

    turn = send_citizen_chat_message(
        session_id, "audience_d1", record.run_id, citizen_id, "Can you say more?", root=root,
    )
    assert turn.role == "advisor"
    assert turn.text.strip()

    history = load_chat(session_id, "citizen", record.run_id, citizen_id, root=root)
    assert [t.role for t in history] == ["user", "advisor"]


def test_a_chat_message_cannot_be_empty(tmp_path: Path) -> None:
    session_id, root, record = _excomm_run(tmp_path)
    member_id = record.deliberation[0].member_id
    with pytest.raises(SessionError, match="empty"):
        send_excomm_chat_message(
            session_id, "excomm_debate", record.run_id, member_id, "   ", root=root
        )


def test_chatting_with_an_unknown_member_or_citizen_raises(tmp_path: Path) -> None:
    session_id, root, record = _excomm_run(tmp_path)
    with pytest.raises(SessionError, match="no ExComm member"):
        send_excomm_chat_message(
            session_id, "excomm_debate", record.run_id, "not_a_real_seat", "hi?", root=root
        )

    audience_session, audience_root, audience_record = _audience_run(tmp_path)
    with pytest.raises(SessionError, match="no citizen"):
        send_citizen_chat_message(
            audience_session, "audience_d1", audience_record.run_id, "not_a_real_citizen",
            "hi?", root=audience_root,
        )


def test_a_run_with_no_committee_or_no_audience_cannot_be_chatted_with(tmp_path: Path) -> None:
    """`baseline` neither convenes an ExComm nor enables the audience; chatting must say
    why rather than fail obscurely."""
    spec = _spec(["baseline"], n=1)
    run_session(spec, root=tmp_path)
    record = arm_records(spec.session_id, "baseline", tmp_path)[0]

    with pytest.raises(SessionError, match="no committee to chat with"):
        send_excomm_chat_message(
            spec.session_id, "baseline", record.run_id, "defense_secretary", "hi?",
            root=tmp_path,
        )
    with pytest.raises(SessionError, match="no one to chat with"):
        send_citizen_chat_message(
            spec.session_id, "baseline", record.run_id, "c000", "hi?", root=tmp_path
        )


def test_the_conversation_turn_cap_is_enforced(tmp_path: Path) -> None:
    session_id, root, record = _excomm_run(tmp_path)
    member_id = record.deliberation[0].member_id

    turns = [
        ChatTurn(role="user", text=f"message {i}")
        if i % 2 == 0
        else ChatTurn(role="advisor", text=f"reply {i}")
        for i in range(CHAT_TURN_CAP)
    ]
    path = chat_path(session_id, "excomm", record.run_id, member_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([t.model_dump(mode="json") for t in turns]), encoding="utf-8")

    with pytest.raises(SessionError, match="turn limit"):
        send_excomm_chat_message(
            session_id, "excomm_debate", record.run_id, member_id, "one more?", root=root
        )


def test_chat_never_touches_run_record_or_the_schema_version(tmp_path: Path) -> None:
    """Session-directory state, like the narrative and the analysis — a chat must not
    change what a re-read of the arm's own JSONL file reports."""
    session_id, root, record = _excomm_run(tmp_path)
    member_id = record.deliberation[0].member_id
    before = arm_records(session_id, "excomm_debate", root)

    send_excomm_chat_message(
        session_id, "excomm_debate", record.run_id, member_id, "Why did you argue that?",
        root=root,
    )

    after = arm_records(session_id, "excomm_debate", root)
    assert [r.model_dump(mode="json") for r in before] == [r.model_dump(mode="json") for r in after]
