"""Sessions: a named set of arm runs over one scenario, and the guardrails around them.

A single arm answers almost nothing. Absolute rung distributions are not findings — base
models escalate in wargame settings from neutral starting conditions — so the interpretable
quantity is a delta against `escalation_prior`, and per-theorist attribution is a contrast
between `loo_*` arms. Both need several arms run together, which is what a session is.

**Every guardrail lives here rather than in `api.py`.** The API is an optional extra; if the
cost gate, the arm validation and the provenance flags lived in it, none of them would be
covered by a suite that must pass with FastAPI uninstalled. `api.py` is a transport shell
over this module and adds no rules of its own.

Three of those guardrails are worth stating outright.

**A session cannot invent a configuration.** `SessionSpec.arms` are names of files in
`configs/arms/`, resolved with `load_arm`. There is no field through which a `RunConfig`
override could arrive, so a UI driving this module cannot construct an experiment that no
file in the repository describes (invariant 5, and invariant 11 for the surface).

**Cost is estimated per arm, not by one formula.** `escalation_prior` sets
`consult_panel: false` and makes two calls per replication where `baseline` makes twenty.
A single upper bound across arms would overstate the control tenfold, and an estimate
nobody believes is an estimate nobody reads.

**Provenance travels with the numbers.** `SessionSummary` carries the backend, the model
that served each role, `grounded`, `cache_enabled`, `retrieval_mode` and every warning
`metrics` emitted, plus `smoke_test` and `mock` flags computed from what actually ran. A
client is expected to render those above the charts, because `docs/framework/measurement.md`
treats them as gates on interpretation rather than footnotes.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from artsoc.config import RunConfig, list_arms, load_arm
from artsoc.llm import PRICE_PER_MTOK, DiskCache, LLMClient, get_backend
from artsoc.metrics import (
    CONTROL_ARM,
    ArmSummary,
    Delta,
    delta,
    load_jsonl,
    reduce_tier,
    summarise,
)
from artsoc.narrative import (
    AnalysisAnswer,
    RunNarrative,
    SessionAnalysis,
    answer_question,
    summarise_run,
)

# Aliased: this module already has a `summarise_session` that builds the numeric
# `SessionSummary`. Two functions with one name, one returning figures and the other
# returning prose about them, is exactly the confusion to avoid here.
from artsoc.narrative import summarise_session as generate_session_analysis
from artsoc.schema import RunRecord
from artsoc.sim import CACHE_DIR, DEFAULT_OUT_DIR, run_many, write_jsonl
from artsoc.views import representative_run

#: Where sessions live. Under `out/`, which is gitignored: a session is reproducible from
#: its spec plus the arm configs, so the records themselves are not source.
SESSIONS_DIR = DEFAULT_OUT_DIR / "sessions"


class SessionError(RuntimeError):
    """A session was specified in a way that cannot be run."""


class SessionSpec(BaseModel):
    """What a session is: some committed arms, one scenario, n replications each.

    Frozen for the same reason `RunConfig` is: a session that could mutate its own spec
    part-way through would make `spec.json` a description of something other than what ran.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    label: str = ""
    scenario_id: str
    #: Arm config names. Not configurations — names of files in `configs/arms/`.
    arms: list[str]
    n: int = Field(ge=1)
    seed0: int = 1

    @field_validator("arms")
    @classmethod
    def _arms_are_unique_and_present(cls, arms: list[str]) -> list[str]:
        if not arms:
            raise ValueError("a session must name at least one arm")
        if len(set(arms)) != len(arms):
            raise ValueError("arms contains duplicates")
        return arms


class RoleCost(BaseModel):
    """The model that will serve one role, and what it costs per million tokens.

    Published rates, quoted so a reader can do the arithmetic themselves. `None` for a model
    with no published rate on file, which shows as a gap rather than as a fabricated number.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    model: str
    calls: int
    usd_per_mtok_in: float | None = None
    usd_per_mtok_out: float | None = None


class ArmEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    arm: str
    n: int
    consult_panel: bool
    calls_per_replication: int
    total_calls: int
    roles: list[RoleCost]


class CallEstimate(BaseModel):
    """What a session will ask the provider to do, before any of it happens.

    Call counts, not dollars. A pre-run USD figure needs tokens per call, which vary by an
    order of magnitude across roles and are not known until something has run; quoting one
    would be inventing the most quotable number in the response. Actual spend is metered
    from each record's `est_cost_usd` as the session runs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    arms: list[ArmEstimate]
    total_calls: int
    backend: str
    cache_enabled: bool
    #: Cached calls are never billed, so the total above is an upper bound. Theorist
    #: questions are decontextualised and repeat across replications of an arm, which is
    #: where nearly all of the saving is.
    note: str = (
        "Upper bound on provider calls before caching. Theorist questions are "
        "decontextualised and cache across replications, so billed calls are typically far "
        "fewer; the presidential decision is never cached, because caching the primary "
        "metric would collapse the distribution to a point mass. Spend is metered per "
        "replication as the session runs."
    )


class ArmProgress(BaseModel):
    """How far one arm has got. Written into `spec.json`'s sibling status file."""

    model_config = ConfigDict(extra="forbid")

    arm: str
    completed: int
    total: int
    failures: list[str] = Field(default_factory=list)


class SessionState(BaseModel):
    """A session's spec plus where it has got to."""

    model_config = ConfigDict(extra="forbid")

    spec: SessionSpec
    #: pending | running | complete | failed | cancelled
    status: str = "pending"
    created_at: str = ""
    finished_at: str | None = None
    progress: list[ArmProgress] = Field(default_factory=list)
    est_cost_usd: float = 0.0
    error: str | None = None


class ProgressEvent(BaseModel):
    """One completed replication, as the client sees it stream past."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    arm: str
    completed: int
    total: int
    #: The terminal rung of the replication that just landed. A distribution that is
    #: obviously degenerate is worth killing early, which is the only reason to stream this.
    rung: int | None = None
    seed: int | None = None
    est_cost_usd: float = 0.0
    cumulative_cost_usd: float = 0.0
    #: Set when a replication failed. Recorded, never swallowed: a replication may fail for
    #: reasons correlated with its outcome, so a distribution over the survivors is biased
    #: unless the reader can see how many were lost.
    failure: str | None = None


class SessionSummary(BaseModel):
    """Per-arm distributions, contrasts against the control, and the caveats.

    The caveats are fields rather than prose because a client has to be able to render them
    above the charts. A number that travels without them is how an absolute escalation rate
    becomes a finding about nuclear strategists, which it is not.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    label: str
    scenario_id: str
    #: `metrics.ArmSummary` and `metrics.Delta` are stdlib dataclasses. Declared here as
    #: themselves rather than mirrored into pydantic models, because a mirror is a second
    #: definition of the primary metric's shape and it would drift. Pydantic reads them,
    #: serialises them, and generates the frontend's TypeScript from them as they are.
    arms: list[ArmSummary]
    deltas: list[Delta]
    control_arm: str = CONTROL_ARM
    #: False when `escalation_prior` was not run. Nothing in the session is interpretable
    #: without it and the client must say so rather than showing absolute rates alone.
    has_control: bool = False
    warnings: list[str] = Field(default_factory=list)

    backend: str = ""
    models: dict[str, str] = Field(default_factory=dict)
    grounded: bool = False
    #: What the grounding was, reduced across every arm in the session: summary |
    #: encyclopedia | belief | stub | mixed | none. A client renders it beside `grounded`,
    #: which on its own stopped saying what a run was grounded in once one panel could draw
    #: on two kinds of source (ADR 0007).
    corpus_tier: str = "none"
    cache_enabled: bool = True
    retrieval_mode: str = ""
    est_cost_usd: float = 0.0

    #: Every role served by one model means `models_override` was set, which pins the
    #: presidential decision — the primary metric — to the same cheap model as everything
    #: else. That measures something different from a run without it.
    smoke_test: bool = False
    #: Mock output is `MOCK:`-prefixed nonsense by design, so a mock sweep can never be read
    #: later as a cheap live run.
    mock: bool = False


# ---------------------------------------------------------------------------
# Validation and estimation
# ---------------------------------------------------------------------------


def resolve_arms(spec: SessionSpec) -> dict[str, RunConfig]:
    """Load each named arm, or fail saying which name is not a file.

    The only route from a session to a configuration. A name that is not a file in
    `configs/arms/` cannot be run, which is what stops a client constructing an experiment
    the repository does not describe.
    """
    available = list_arms()
    unknown = [a for a in spec.arms if a not in available]
    if unknown:
        raise SessionError(
            f"no such arm(s): {unknown}. Arms are config files; available: {available}"
        )
    return {name: load_arm(name) for name in spec.arms}


def validate_spec(spec: SessionSpec) -> dict[str, RunConfig]:
    """Every arm exists, and they all run the same scenario.

    Scenario agreement matters because a session's whole purpose is contrast. Two arms over
    different scenarios produce a delta that carries both the arm difference and the
    scenario difference, and nothing in the record would say which was which.
    """
    configs = resolve_arms(spec)

    scenarios = {name: config.scenario_id for name, config in configs.items()}
    disagree = {s for s in scenarios.values() if s != spec.scenario_id}
    if disagree:
        wrong = {n: s for n, s in scenarios.items() if s != spec.scenario_id}
        raise SessionError(
            f"session declares scenario {spec.scenario_id!r} but {wrong} run other "
            "scenarios; a contrast across scenarios isolates nothing"
        )
    return configs


def estimate_calls(spec: SessionSpec) -> CallEstimate:
    """Upper-bound provider calls, per arm, per role, before caching.

    Derived from each arm's own `RunConfig` rather than from one formula, because
    `consult_panel: false` changes the shape of a replication rather than scaling it.
    """
    configs = validate_spec(spec)
    arms: list[ArmEstimate] = []
    backends = set()
    caching = set()

    for name, config in configs.items():
        models = config.resolved_models()
        backends.add(config.backend)
        caching.add(config.cache_enabled)

        # One entry per call site in `sim.run_once`, so the estimate is checkable against
        # the loop rather than against a formula that has to be kept in step with it.
        if config.consult_panel:
            per_role = {
                "intelligence_officer": 1,
                "president_query": 1,
                "advisor_questions": 1,
                "advisor_selection": config.n_questions,
                "theorist": config.n_questions * config.k_per_question,
                "advisor_synthesis": 1,
                "president_decision": 1,
            }
        else:
            # No advisor, no panel, no brief. The control arm is two calls, not twenty.
            per_role = {"intelligence_officer": 1, "president_decision": 1}

        per_replication = sum(per_role.values())

        arms.append(
            ArmEstimate(
                arm=name,
                n=spec.n,
                consult_panel=config.consult_panel,
                calls_per_replication=per_replication,
                total_calls=per_replication * spec.n,
                roles=[
                    RoleCost(
                        role=role,
                        model=models[role],
                        calls=calls * spec.n,
                        usd_per_mtok_in=(PRICE_PER_MTOK.get(models[role]) or (None, None))[0],
                        usd_per_mtok_out=(PRICE_PER_MTOK.get(models[role]) or (None, None))[1],
                    )
                    for role, calls in per_role.items()
                ],
            )
        )

    return CallEstimate(
        session_id=spec.session_id,
        arms=arms,
        total_calls=sum(a.total_calls for a in arms),
        backend=", ".join(sorted(backends)),
        cache_enabled=all(caching),
    )


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def session_dir(session_id: str, root: Path | None = None) -> Path:
    return (root or SESSIONS_DIR) / session_id


def narrative_path(session_id: str, arm: str, root: Path | None = None) -> Path:
    return session_dir(session_id, root) / f"{arm}.narrative.json"


def load_narrative(session_id: str, arm: str, root: Path | None = None) -> RunNarrative | None:
    """The stored narrative for an arm, or None.

    None is a normal state, not an error: sessions run before this existed have no file, and
    the UI falls back to the deterministic facts rather than showing nothing.
    """
    path = narrative_path(session_id, arm, root)
    if not path.exists():
        return None
    try:
        return RunNarrative.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def ensure_narrative(
    session_id: str, arm: str, root: Path | None = None
) -> RunNarrative | None:
    """The stored narrative for an arm, generating it once if it does not exist.

    **Generated on request, not during the sweep.** A sweep runs every arm; a reader opens
    one. Summarising at run time meant a twenty-arm session paid for twenty summaries to
    have nineteen of them never read — small against the sweep itself, and still waste with
    no upside, since a summary nobody opens tells nobody anything.

    Written to disk on first request and served from there afterwards, so the text is the
    same on every visit. A summary that changed on refresh would not be a record.

    A failure returns None rather than raising: the narrative is an orientation aid beside
    figures that are already correct, and its absence degrades to those figures alone.
    """
    existing = load_narrative(session_id, arm, root)
    if existing is not None:
        return existing

    try:
        records = arm_records(session_id, arm, root)
        config = load_arm(arm)
        client = LLMClient(
            backend=get_backend(
                config.backend, config.resolved_models(), effort=config.effort
            ),
            run_seed=0,
            cache=DiskCache(CACHE_DIR),
            cache_enabled=True,
        )
        narrative = summarise_run(representative_run(records).record, client, arm)
    except Exception:  # noqa: BLE001 - an orientation aid must not break a results page
        return None

    narrative_path(session_id, arm, root).write_text(
        narrative.model_dump_json(indent=2), encoding="utf-8"
    )
    return narrative


# ---------------------------------------------------------------------------
# Session-level interpretation. Generated on request, cached on disk, answers keyed by
# question so re-asking one is free.
# ---------------------------------------------------------------------------


def analysis_path(session_id: str, arm: str, root: Path | None = None) -> Path:
    return session_dir(session_id, root) / f"{arm}.analysis.json"


def _question_key(question: str) -> str:
    """A stable id for one question, so asking it twice is not billed twice.

    Normalised on whitespace and case before hashing: "why did it escalate?" and "Why did
    it escalate?" are the same question, and charging for the second would be charging for
    a capitalisation.
    """
    normalised = " ".join(question.lower().split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]


class StoredAnalysis(BaseModel):
    """The cached interpretation for one arm, plus every answered follow-up."""

    model_config = ConfigDict(extra="forbid")

    analysis: SessionAnalysis | None = None
    #: Keyed by a hash of the normalised question.
    answers: dict[str, AnalysisAnswer] = Field(default_factory=dict)


def load_analysis(session_id: str, arm: str, root: Path | None = None) -> StoredAnalysis:
    """What has been generated for this arm so far. Empty is a normal state, not an error."""
    path = analysis_path(session_id, arm, root)
    if not path.exists():
        return StoredAnalysis()
    try:
        return StoredAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return StoredAnalysis()


def _save_analysis(
    session_id: str, arm: str, stored: StoredAnalysis, root: Path | None = None
) -> None:
    analysis_path(session_id, arm, root).write_text(
        stored.model_dump_json(indent=2), encoding="utf-8"
    )


def analysis_payload(session_id: str, arm: str, root: Path | None = None) -> dict[str, Any]:
    """The figures a session-level call is given, and the only thing it is given.

    Assembled from already-computed views: the arm summary, the contrast against the
    control, the deterministic session facts, the course-of-action support and the
    diagnostics. **No record, no prompt, no `host_ground_truth`** — none of those views
    holds any of them, so this cannot carry one by accident, and a test scans the assembled
    block to keep that true.
    """
    from artsoc.views import coa_support, session_facts

    records = arm_records(session_id, arm, root)
    summary = summarise(records)

    control: ArmSummary | None = None
    state = load_session(session_id, root)
    if arm != CONTROL_ARM and CONTROL_ARM in state.spec.arms:
        control_path = session_dir(session_id, root) / f"{CONTROL_ARM}.jsonl"
        if control_path.exists():
            control = summarise(load_jsonl(control_path))

    contrast = delta(summary, control) if control is not None else None
    return {
        "arm": arm,
        "scenario_id": state.spec.scenario_id,
        "facts": session_facts(records, summary, contrast).model_dump(mode="json"),
        "distribution": summary.rung_distribution,
        "contrast_against_control": asdict(contrast) if contrast else None,
        "control_arm_was_run": control is not None,
        "course_of_action_support": coa_support(records).model_dump(mode="json"),
        "diagnostics": summary.warnings,
        "conditions": {
            "backend": summary.backend,
            "models": summary.models,
            "grounded": summary.grounded,
            "corpus_tier": summary.corpus_tier,
            "cache_enabled": summary.cache_enabled,
            "retrieval_mode": summary.retrieval_mode,
            "persona_method": summary.persona_method,
        },
    }


def _analysis_client(arm: str) -> LLMClient:
    """A client for a host-side analysis call, configured the way the arm's runs were."""
    config = load_arm(arm)
    return LLMClient(
        backend=get_backend(config.backend, config.resolved_models(), effort=config.effort),
        run_seed=0,
        cache=DiskCache(CACHE_DIR),
        cache_enabled=True,
    )


def ensure_analysis(
    session_id: str, arm: str, root: Path | None = None, *, regenerate: bool = False
) -> SessionAnalysis | None:
    """The stored interpretation for an arm, generating it once if absent.

    Returns None on failure rather than raising, the same way `ensure_narrative` does: this
    is a reading of figures that are already correct and already on the page, so its absence
    degrades to those figures alone.
    """
    stored = load_analysis(session_id, arm, root)
    if stored.analysis is not None and not regenerate:
        return stored.analysis
    try:
        payload = analysis_payload(session_id, arm, root)
        stored.analysis = generate_session_analysis(
            payload, _analysis_client(arm), session_id, arm
        )
    except Exception:  # noqa: BLE001 - an orientation aid must not break a results page
        return None
    _save_analysis(session_id, arm, stored, root)
    return stored.analysis


def ask_analysis(
    session_id: str, arm: str, question: str, root: Path | None = None
) -> AnalysisAnswer | None:
    """Answer one follow-up, serving a repeat of the same question from disk."""
    if not question.strip():
        raise SessionError("a question cannot be empty")

    stored = load_analysis(session_id, arm, root)
    key = _question_key(question)
    if key in stored.answers:
        return stored.answers[key]

    try:
        payload = analysis_payload(session_id, arm, root)
        answer = answer_question(question, payload, _analysis_client(arm), session_id, arm)
    except Exception:  # noqa: BLE001 - reported as no answer, never as a broken page
        return None

    stored.answers[key] = answer
    _save_analysis(session_id, arm, stored, root)
    return answer


def _write_state(state: SessionState, root: Path | None = None) -> None:
    target = session_dir(state.spec.session_id, root)
    target.mkdir(parents=True, exist_ok=True)
    (target / "spec.json").write_text(
        json.dumps(state.model_dump(mode="json"), indent=2), encoding="utf-8"
    )


def load_session(session_id: str, root: Path | None = None) -> SessionState:
    path = session_dir(session_id, root) / "spec.json"
    if not path.exists():
        raise SessionError(f"no session {session_id!r} at {path}")
    return SessionState.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_sessions(root: Path | None = None) -> list[SessionState]:
    """Every session on disk, newest first. Unreadable directories are skipped."""
    base = root or SESSIONS_DIR
    if not base.is_dir():
        return []
    states: list[SessionState] = []
    for child in base.iterdir():
        if not (child / "spec.json").exists():
            continue
        try:
            states.append(load_session(child.name, base))
        except (SessionError, ValueError):
            # A half-written or hand-edited session should not take the listing down.
            continue
    return sorted(states, key=lambda s: s.created_at, reverse=True)


def delete_session(session_id: str, root: Path | None = None) -> None:
    shutil.rmtree(session_dir(session_id, root), ignore_errors=True)


def arm_records(session_id: str, arm: str, root: Path | None = None) -> list[RunRecord]:
    """One arm's records, validated against the schema on the way in."""
    return load_jsonl(session_dir(session_id, root) / f"{arm}.jsonl")


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def create_session(spec: SessionSpec, root: Path | None = None) -> SessionState:
    """Validate a spec and write it to disk. Runs nothing."""
    validate_spec(spec)
    state = SessionState(
        spec=spec,
        status="pending",
        created_at=datetime.now(timezone.utc).isoformat(),
        progress=[ArmProgress(arm=a, completed=0, total=spec.n) for a in spec.arms],
    )
    _write_state(state, root)
    return state


def run_session(
    spec: SessionSpec,
    on_progress: Callable[[ProgressEvent], None] | None = None,
    *,
    root: Path | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> SessionState:
    """Run every arm, streaming progress, and write the summary.

    **The control arm runs first** where it is present. Every other arm's number is a delta
    against it, so a session killed half-way is far more useful with the control complete
    than with it pending.

    Cancellation keeps whatever has completed. A partial arm is written and its record count
    stated, rather than discarded — replications already paid for are still data, provided
    the reader can see how many there are.
    """
    configs = validate_spec(spec)
    state = create_session(spec, root)
    state.status = "running"
    _write_state(state, root)

    progress = {p.arm: p for p in state.progress}
    cumulative = 0.0
    ordered = sorted(spec.arms, key=lambda a: (a != CONTROL_ARM, spec.arms.index(a)))

    def emit(event: ProgressEvent) -> None:
        if on_progress is not None:
            on_progress(event)

    try:
        for arm in ordered:
            target = session_dir(spec.session_id, root) / f"{arm}.jsonl"
            failures: list[tuple[int, str]] = []
            records: list[RunRecord] = []
            cancelled = False

            for record in run_many(configs[arm], spec.n, spec.seed0, failures):
                records.append(record)
                cumulative = round(cumulative + record.est_cost_usd, 6)
                progress[arm].completed = len(records)
                emit(
                    ProgressEvent(
                        session_id=spec.session_id,
                        arm=arm,
                        completed=len(records),
                        total=spec.n,
                        rung=record.rung,
                        seed=record.seed,
                        est_cost_usd=record.est_cost_usd,
                        cumulative_cost_usd=cumulative,
                    )
                )
                if should_cancel is not None and should_cancel():
                    cancelled = True
                    break

            # Reported with their seeds, the way `artsoc run` does it. A replication may
            # fail for reasons correlated with its outcome, so silent loss biases the
            # distribution with nothing in the record to show it.
            for seed, reason in failures:
                progress[arm].failures.append(f"seed {seed}: {reason}")
                emit(
                    ProgressEvent(
                        session_id=spec.session_id,
                        arm=arm,
                        completed=len(records),
                        total=spec.n,
                        failure=f"seed {seed}: {reason}",
                        cumulative_cost_usd=cumulative,
                    )
                )

            if records:
                write_jsonl(records, target)
            state.est_cost_usd = cumulative
            _write_state(state, root)

            if cancelled:
                state.status = "cancelled"
                break
        else:
            state.status = "complete"
    except Exception as exc:  # noqa: BLE001 - a failed session is reported, not raised away
        state.status = "failed"
        state.error = f"{type(exc).__name__}: {exc}"

    state.finished_at = datetime.now(timezone.utc).isoformat()
    _write_state(state, root)

    if any(p.completed for p in state.progress):
        write_summary(spec.session_id, root)
    return state


# ---------------------------------------------------------------------------
# Summarising
# ---------------------------------------------------------------------------


def summarise_session(session_id: str, root: Path | None = None) -> SessionSummary:
    """Per-arm summaries, contrasts against the control, and the provenance flags.

    `metrics.summarise` and `metrics.delta` do the arithmetic. Nothing is recomputed here:
    a second implementation of the primary metric is a second thing that can disagree with
    the record.
    """
    state = load_session(session_id, root)
    summaries: list[ArmSummary] = []
    for arm in state.spec.arms:
        path = session_dir(session_id, root) / f"{arm}.jsonl"
        if not path.exists():
            continue
        summaries.append(summarise(load_jsonl(path)))

    control = next((s for s in summaries if s.arm == CONTROL_ARM), None)
    deltas: list[Delta] = (
        [delta(s, control) for s in summaries if s.arm != CONTROL_ARM] if control else []
    )

    warnings: list[str] = []
    for summary in summaries:
        for warning in summary.warnings:
            if warning not in warnings:
                warnings.append(warning)
    if control is None:
        warnings.insert(
            0,
            f"NO CONTROL ARM: {CONTROL_ARM} was not run in this session. Nothing here is "
            "interpretable — absolute escalation rates are not a finding, because base "
            "models escalate in wargame settings from neutral starting conditions. Only "
            "the delta against the control means anything.",
        )

    first = summaries[0] if summaries else None
    models = dict(first.models) if first else {}
    distinct = set(models.values())
    # Under the mock every role reports "mock", so one distinct value is the expected state
    # rather than evidence of `models_override`. Without this guard every free fixture
    # session raises a SMOKE TEST banner, and a banner that fires when nothing is wrong is
    # one people learn to click past. `metrics._warnings` carries the same guard.
    mock = bool(first) and first.backend == "mock"

    return SessionSummary(
        session_id=session_id,
        label=state.spec.label,
        scenario_id=state.spec.scenario_id,
        arms=summaries,
        deltas=deltas,
        has_control=control is not None,
        warnings=warnings,
        backend=first.backend if first else "",
        models=models,
        grounded=bool(first.grounded) if first else False,
        # Reduced across every arm rather than read off the first record, for the reason
        # `metrics.summarise` reduces within one: a session whose arms drew on different
        # source kinds is mixed, and naming whichever ran first would conceal that.
        corpus_tier=reduce_tier(s.corpus_tier for s in summaries),
        cache_enabled=bool(first.cache_enabled) if first else True,
        retrieval_mode=first.retrieval_mode if first else "",
        est_cost_usd=state.est_cost_usd,
        smoke_test=not mock and len(distinct) == 1 and len(models) > 1,
        mock=mock,
    )


def write_summary(session_id: str, root: Path | None = None) -> SessionSummary:
    summary = summarise_session(session_id, root)
    (session_dir(session_id, root) / "summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    return summary
