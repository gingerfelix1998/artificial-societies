"""Read-only local API for the frontend. Optional extra; nothing in `artsoc` imports it.

A transport shell over `session.py` and `views.py`. Every rule it appears to enforce is
actually enforced there, where the offline test suite can reach it — this module exists to
turn function calls into HTTP and must not become a second place experiment semantics are
decided.

**It is read-only with respect to experiment definition.** The only thing a client may
send is a `SessionSpec`: a scenario id, some arm *names*, `n` and `seed0`. Arm names are
resolved with `config.load_arm`, so a body naming something that is not a file in
`configs/arms/` 404s. There is no field through which a `RunConfig` override could arrive,
which is invariant 11 held structurally rather than by validation.

**Prompts never leave the process.** `RunRecord` carries none — `call_log` is not persisted
into it (invariant 10) — so no response here can contain one. That is a property of the
schema rather than of this module's care, and a test asserts it of the responses anyway.

**`host_ground_truth` is gated.** It exists in the record so an analyst can score
misperception, and it is exactly the thing a demo viewer would mistake for something the
President knew. It is stripped unless explicitly asked for, and returned wrapped so it
cannot be rendered unlabelled.

**Runs cost money.** `configs/base.yaml` decides the backend, and it currently declares a
live one. `POST /api/sessions` therefore refuses without `confirm: true` and hands back the
call estimate instead, so no client can start a paid sweep by accident.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from artsoc.config import base_defaults, list_arms, load_arm, varied_fields
from artsoc.metrics import CONTROL_ARM
from artsoc.narrative import AnalysisAnswer, RunNarrative, SessionAnalysis
from artsoc.retrieval import resolve_passages
from artsoc.schema import RunRecord
from artsoc.session import (
    CallEstimate,
    ProgressEvent,
    SessionError,
    SessionSpec,
    SessionState,
    SessionSummary,
    arm_records,
    ask_analysis,
    create_session,
    ensure_analysis,
    ensure_narrative,
    estimate_calls,
    list_sessions,
    load_analysis,
    load_narrative,
    load_session,
    run_session,
    summarise_session,
)
from artsoc.views import (
    AgentDetail,
    CoaSupport,
    EngagementSummary,
    InteractionGraph,
    LoopStep,
    PipelineFlow,
    ProvenanceFlow,
    RepresentativeRun,
    RunFacts,
    SessionFacts,
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
from artsoc.world import SCENARIO_DIR, load_scenario


class _Run:
    """One background session: the thread, its event queue, and its cancel flag."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.events: queue.Queue[ProgressEvent | None] = queue.Queue()
        self.cancelled = threading.Event()
        self.thread: threading.Thread | None = None


#: In-flight sessions, by id. Nothing here is persisted: the state that matters is on disk
#: in `spec.json`, and a restart should lose the stream rather than keep a half-remembered
#: idea of one.
_RUNNING: dict[str, _Run] = {}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ScenarioInfo(BaseModel):
    """One committed scenario, as a client may see it.

    Two things are absent on purpose. `ground_truth_detail` is host-only and exists so
    misperception can be scored, not so anyone reading a scenario card can know the answer.
    `Scenario.notes` are the host's *design* commentary — what the ambiguity is meant to do
    and why the ground truth is withheld — and describing the mechanism to a viewer is a
    softer version of the same leak.

    What is shown instead is `observable_signature`: exactly what a collection apparatus
    could in principle see. It is the agent-visible half of the event by definition, and it
    is what makes the ambiguity legible without narrating it.
    """

    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    label: str
    description: str
    self_nation: str
    adversary_nation: str
    n_events: int
    observable_signature: list[str] = Field(default_factory=list)


class ArmInfo(BaseModel):
    """One committed arm, and what it varies from base.

    `varies` is what makes the arm list interpretable: an arm is only worth running because
    of the one field it moves, and a client picking arms should see that rather than a list
    of names.
    """

    model_config = ConfigDict(extra="forbid")

    arm: str
    scenario_id: str
    notes: str
    varies: dict[str, Any]
    is_control: bool
    is_exclusion_arm: bool
    consult_panel: bool


class SessionCreated(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    state: SessionState
    estimate: CallEstimate


class Passage(BaseModel):
    """One cited passage, resolved to the text it points at."""

    model_config = ConfigDict(extra="forbid")

    passage_id: str
    #: The middle segment of the passage id. For a Wikipedia store that is the source kind
    #: — `wikipedia`, `abstract` or `belief` — and Wikipedia is TERTIARY: an article about
    #: the theorist, not the theorist's own writing. For a markdown store it is the
    #: publication slug instead, because ids there are per-work, and `section` says whether
    #: the record is a stated claim or the prose arguing it (ADR 0007).
    source: str
    section: str
    text: str


class PassageLookup(BaseModel):
    """Cited ids resolved against a persona's own store.

    `unresolved` is the interesting half. An id the store does not contain was invented by
    the persona, and the rate of that is a finding about the method — so it is returned as
    its own list rather than quietly omitted from `passages`.
    """

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    passages: list[Passage]
    unresolved: list[str]
    note: str = (
        "An id that did not resolve was not in the block the persona was shown. It is "
        "reported, never filled in: the rate is a finding about the method."
    )


class LandingView(BaseModel):
    """What the simulation landing page states, and the caveats that gate reading it.

    One arm — the one the reader is looking at — plus the contrast against the control.
    `facts` carries every number, so the generated prose beside it never has to state one.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    label: str
    scenario: ScenarioInfo | None
    #: The arm this page is about. Defaults to a full-loop arm rather than the control,
    #: whose distribution is the base rate and not what anyone opened the page to read.
    arm: str
    arms: list[str]
    facts: SessionFacts
    #: Whose opinions the chosen course of action cited. NOT influence — the model carries
    #: its own note saying so, and the UI renders it.
    coa_support: CoaSupport
    #: Present once generated. Null until someone asks, the same as `RunNarrative`.
    analysis: SessionAnalysis | None = None
    summary: SessionSummary


class AnalysisQuestion(BaseModel):
    """One follow-up. The only thing a client may send to the analysis endpoint."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)


class RepresentativeView(BaseModel):
    """The representative run, its derived views, and its provenance in one payload.

    Bundled rather than split across endpoints because the three panels that consume it —
    Gantt, graph, event log — must agree on step count, and fetching them separately makes
    disagreement possible.
    """

    model_config = ConfigDict(extra="forbid")

    arm: str
    representative: RepresentativeRun
    steps: list[LoopStep]
    graph: InteractionGraph
    panel: list[str]
    #: One entry per node the graph draws, so no clickable node opens an empty panel.
    agents: list[AgentDetail]
    #: Every number the header states, read from the record rather than interpreted. The
    #: narrative beside it therefore never has to carry a count it could get wrong.
    facts: RunFacts
    #: Present only once one has been generated for this arm. Narratives are written on
    #: request rather than during the sweep — a sweep runs every arm and a reader opens one
    #: — so this is null until someone asks. The UI shows `facts` alone meanwhile and
    #: fetches the summary separately, which also keeps this payload off the critical path
    #: of a page load.
    narrative: RunNarrative | None = None
    engagement: EngagementSummary
    flow: PipelineFlow
    #: Cited passages → theorist positions → proposed courses of action → the decision.
    #: Every link comes from an id the record holds; none is inferred from wording.
    provenance: ProvenanceFlow
    #: Present only when explicitly requested. Host-only: it is in the record so an analyst
    #: can score misperception, and no agent in the run ever saw it.
    host_ground_truth: dict[str, str] | None = None
    host_only_note: str = (
        "HOST-ONLY. This is what was actually happening. No agent in the simulation saw "
        "it; it exists so misperception can be scored after the fact."
    )


def _record_without_ground_truth(record: RunRecord) -> dict[str, Any]:
    """A record as JSON with the host's truth removed.

    Removed on the way out rather than never fetched, because the analyst path needs it and
    both paths read the same file. The removal is one place, and the reveal flag is the only
    thing that reinstates it.
    """
    dumped = record.model_dump(mode="json")
    dumped["host_ground_truth"] = {}
    return dumped


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def create_app(*, static_dir: Path | None = None) -> FastAPI:
    """Build the app. A factory so tests get a clean instance per case.

    `static_dir` serves a built frontend from the same process, so a demo is one command on
    one port instead of two. It is mounted last, after every `/api` route, so a built
    `index.html` can never shadow the API.
    """
    app = FastAPI(
        title="artsoc local API",
        description=(
            "Read-only local API for the artsoc frontend. Selects among committed arm "
            "configs; it cannot construct a configuration that no file in configs/ "
            "describes."
        ),
        version="0.1.0",
    )

    @app.get("/api/scenarios", response_model=list[ScenarioInfo])
    def get_scenarios() -> list[ScenarioInfo]:
        return [
            _scenario_info(load_scenario(path.stem), path.stem)
            for path in sorted(SCENARIO_DIR.glob("*.json"))
        ]

    @app.get("/api/arms", response_model=list[ArmInfo])
    def get_arms(scenario_id: str | None = None) -> list[ArmInfo]:
        base = base_defaults()
        out: list[ArmInfo] = []
        for name in list_arms():
            config = load_arm(name)
            if scenario_id is not None and config.scenario_id != scenario_id:
                continue
            out.append(
                ArmInfo(
                    arm=name,
                    scenario_id=config.scenario_id,
                    notes=" ".join(config.notes.split()),
                    varies={k: _jsonable(v) for k, v in varied_fields(config, base).items()},
                    is_control=name == CONTROL_ARM,
                    is_exclusion_arm=bool(config.excluded_personas),
                    consult_panel=config.consult_panel,
                )
            )
        return out

    @app.post("/api/sessions", response_model=SessionCreated)
    def post_session(
        spec: SessionSpec, confirm: bool = Query(default=False)
    ) -> SessionCreated:
        """Start a session. Refuses without explicit confirmation.

        The refusal is the cost gate: `configs/base.yaml` decides the backend and currently
        declares a live one, so an unconfirmed POST returns the call estimate with 409 and
        starts nothing.
        """
        try:
            estimate = estimate_calls(spec)
        except SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if not confirm:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "confirmation required",
                    "message": (
                        "This session will make provider calls against the backend named "
                        "in configs/base.yaml. Re-send with confirm=true to start it."
                    ),
                    "estimate": estimate.model_dump(mode="json"),
                },
            )

        # Created synchronously so the response describes a session that exists on disk.
        # Leaving it to the thread races the client's first GET, and the client would see
        # a 404 for a session it had just been told the id of.
        try:
            state = create_session(spec)
        except SessionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        run = _Run(spec.session_id)
        _RUNNING[spec.session_id] = run

        def work() -> None:
            try:
                run_session(
                    spec,
                    run.events.put,
                    should_cancel=run.cancelled.is_set,
                )
            finally:
                # Sentinel: the SSE stream ends when it sees this, rather than polling a
                # thread's liveness and guessing.
                run.events.put(None)

        run.thread = threading.Thread(target=work, daemon=True, name=f"session-{spec.session_id}")
        run.thread.start()

        return SessionCreated(session_id=spec.session_id, state=state, estimate=estimate)

    @app.get("/api/sessions", response_model=list[SessionState])
    def get_sessions() -> list[SessionState]:
        return list_sessions()

    @app.get("/api/sessions/{session_id}", response_model=SessionState)
    def get_session(session_id: str) -> SessionState:
        return _session_or_404(session_id)

    @app.post("/api/sessions/{session_id}/cancel", response_model=SessionState)
    def cancel_session(session_id: str) -> SessionState:
        """Stop a running session, keeping every replication already completed."""
        run = _RUNNING.get(session_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"session {session_id} is not running")
        run.cancelled.set()
        return _session_or_404(session_id)

    @app.get("/api/sessions/{session_id}/events")
    async def session_events(session_id: str) -> StreamingResponse:
        """Server-sent progress, one event per completed replication.

        Useful rather than decorative: a distribution that is obviously degenerate is worth
        killing early, and under a live backend that is money not spent.
        """
        run = _RUNNING.get(session_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"session {session_id} is not running")

        async def stream() -> AsyncIterator[str]:
            loop = asyncio.get_running_loop()
            while True:
                # The session runs in a thread and the queue is blocking, so the wait is
                # pushed off the event loop rather than polling with a sleep.
                event = await loop.run_in_executor(None, run.events.get)
                if event is None:
                    state = load_session(session_id)
                    yield _sse("done", state.model_dump(mode="json"))
                    _RUNNING.pop(session_id, None)
                    return
                yield _sse("progress", event.model_dump(mode="json"))

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/sessions/{session_id}/summary", response_model=SessionSummary)
    def get_summary(session_id: str) -> SessionSummary:
        _session_or_404(session_id)
        try:
            return summarise_session(session_id)
        except (SessionError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/sessions/{session_id}/landing", response_model=LandingView)
    def get_landing(session_id: str, arm: str | None = None) -> LandingView:
        """The simulation landing page: scenario, figures, and who grounded the choice."""
        state = _session_or_404(session_id)
        chosen_arm = arm or _default_arm(state)
        if chosen_arm not in state.spec.arms:
            raise HTTPException(status_code=404, detail=f"session has no arm {chosen_arm!r}")

        try:
            records = arm_records(session_id, chosen_arm)
            summary = summarise_session(session_id)
        except (SessionError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        arm_summary = next((s for s in summary.arms if s.arm == chosen_arm), None)
        if arm_summary is None:
            raise HTTPException(status_code=404, detail=f"no records for arm {chosen_arm!r}")
        contrast = next((d for d in summary.deltas if d.arm == chosen_arm), None)

        scenario = None
        try:
            loaded = load_scenario(state.spec.scenario_id)
            scenario = _scenario_info(loaded, state.spec.scenario_id)
        except FileNotFoundError:
            # A session whose scenario file has since been renamed still has figures worth
            # reading. The card is omitted rather than the page refused.
            scenario = None

        return LandingView(
            session_id=session_id,
            label=state.spec.label,
            scenario=scenario,
            arm=chosen_arm,
            arms=list(state.spec.arms),
            facts=session_facts(records, arm_summary, contrast),
            coa_support=coa_support(records),
            analysis=load_analysis(session_id, chosen_arm).analysis,
            summary=summary,
        )

    @app.post(
        "/api/sessions/{session_id}/analysis",
        response_model=SessionAnalysis | None,
    )
    def post_analysis(
        session_id: str, arm: str | None = None, regenerate: bool = Query(default=False)
    ) -> SessionAnalysis | None:
        """Generate this arm's interpretation, or return the one already stored.

        A POST because the first call costs a model call. Idempotent after that: written to
        disk and served from there, so a reader who revisits pays nothing and sees the same
        text. A reading that changed on refresh would not be a record.
        """
        state = _session_or_404(session_id)
        chosen_arm = arm or _default_arm(state)
        if chosen_arm not in state.spec.arms:
            raise HTTPException(status_code=404, detail=f"session has no arm {chosen_arm!r}")
        return ensure_analysis(session_id, chosen_arm, regenerate=regenerate)

    @app.post(
        "/api/sessions/{session_id}/analysis/ask",
        response_model=AnalysisAnswer | None,
    )
    def post_analysis_question(
        session_id: str, body: AnalysisQuestion, arm: str | None = None
    ) -> AnalysisAnswer | None:
        """Answer one follow-up from the figures on the page, and nothing else.

        Billed per distinct question and cached by it, so re-asking the same thing — in any
        capitalisation — is free. The model is given summary statistics only: no record, no
        prompt, and no `host_ground_truth`.
        """
        state = _session_or_404(session_id)
        chosen_arm = arm or _default_arm(state)
        if chosen_arm not in state.spec.arms:
            raise HTTPException(status_code=404, detail=f"session has no arm {chosen_arm!r}")
        try:
            return ask_analysis(session_id, chosen_arm, body.question)
        except SessionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/passages/{persona_id}", response_model=PassageLookup)
    def get_passages(persona_id: str, ids: str = Query(default="")) -> PassageLookup:
        """Resolve cited passage ids to the text behind them.

        Analyst-facing and read-only. A citation is only checkable against the claim it was
        attached to if the passage can be read, and `RunRecord` stores the ids rather than
        the block — deliberately, since storing the block would mean storing what went into
        a prompt.

        This is not part of the retrieval path. It reads ids that are already in a record;
        `Theorist.opine` goes through `Retriever.retrieve` and has no route here.
        """
        wanted = [i.strip() for i in ids.split(",") if i.strip()]
        try:
            found = resolve_passages(persona_id, wanted)
        except OSError as exc:  # pragma: no cover - a corpus that cannot be read
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return PassageLookup(
            persona_id=persona_id,
            passages=[Passage(**found[i]) for i in wanted if i in found],
            unresolved=[i for i in wanted if i not in found],
        )

    @app.get("/api/sessions/{session_id}/runs/{arm}/representative")
    def get_representative(
        session_id: str, arm: str, reveal_ground_truth: bool = Query(default=False)
    ) -> dict[str, Any]:
        """The representative run plus every derived view of it.

        `host_ground_truth` is stripped unless `reveal_ground_truth` is set, and is returned
        under an explicit host-only label when it is, so a viewer cannot mistake it for
        something the President knew.
        """
        state = _session_or_404(session_id)
        if arm not in state.spec.arms:
            raise HTTPException(status_code=404, detail=f"session has no arm {arm!r}")
        try:
            records = arm_records(session_id, arm)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        chosen = representative_run(records)
        record = chosen.record
        payload = RepresentativeView(
            arm=arm,
            representative=chosen,
            steps=loop_steps(record),
            graph=interaction_graph(record),
            panel=panel_for(record),
            agents=agent_details(record),
            facts=run_facts(record),
            narrative=load_narrative(session_id, arm),
            engagement=engagement_stats(records),
            flow=pipeline_flow(records),
            provenance=provenance_flow(record),
            host_ground_truth=dict(record.host_ground_truth) if reveal_ground_truth else None,
        ).model_dump(mode="json")

        # Serialised by hand so the record itself can have its host-only field removed
        # without a second RunRecord model that could drift from the first.
        payload["representative"]["record"] = (
            record.model_dump(mode="json")
            if reveal_ground_truth
            else _record_without_ground_truth(record)
        )
        return payload

    @app.post(
        "/api/sessions/{session_id}/runs/{arm}/narrative",
        response_model=RunNarrative | None,
    )
    def post_narrative(session_id: str, arm: str) -> RunNarrative | None:
        """Generate this arm's summary, or return the one already stored.

        A POST because the first call has an effect and costs a model call. Idempotent
        after that: the narrative is written to disk and served from there, so a reader who
        revisits the page pays nothing and sees the same text.

        Deliberately not part of the representative payload's generation path. Summarising
        every arm as a sweep finished meant paying for twenty summaries so that nineteen
        could go unread.
        """
        state = _session_or_404(session_id)
        if arm not in state.spec.arms:
            raise HTTPException(status_code=404, detail=f"session has no arm {arm!r}")
        return ensure_narrative(session_id, arm)

    if static_dir is not None and static_dir.is_dir():
        _serve_frontend(app, static_dir)

    return app


def _serve_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve a built frontend from this process, with a client-side routing fallback.

    Registered after every `/api` route so nothing static can shadow the API, and the
    catch-all refuses `/api/...` explicitly — otherwise a mistyped endpoint would return the
    index page with a 200 and the client would try to parse HTML as JSON.

    The fallback is what makes deep links work: the router owns `/sessions/<id>`, and there
    is no such file on disk, so a plain static mount 404s on every URL but the root.
    """
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = static_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"no endpoint /{full_path}")
        candidate = static_dir / full_path
        if full_path and candidate.is_file() and candidate.resolve().is_relative_to(
            static_dir.resolve()
        ):
            return FileResponse(candidate)
        return FileResponse(index)


#: Terms in scenario labels that are acronyms rather than words. Title-casing turns
#: "tel_dispersal" into "Tel Dispersal", which reads as a name; TEL is a
#: transporter-erector-launcher, and a page heading that misreads it is the most visible
#: place to get the domain wrong.
LABEL_ACRONYMS: frozenset[str] = frozenset({"tel", "icbm", "slbm", "c2", "nato", "eez", "sam"})


def _humanise_label(label: str) -> str:
    return " ".join(
        part.upper() if part.lower() in LABEL_ACRONYMS else part.capitalize()
        for part in label.split("_")
    )


def _scenario_info(scenario: Any, fallback_id: str) -> ScenarioInfo:
    """A scenario as a client may see it. One definition, used by both routes that need it.

    Neither `ground_truth_detail` nor `Scenario.notes` appears: the first is the host's
    truth, and the second is the host's design commentary explaining what the ambiguity is
    meant to do — describing the mechanism to a viewer is a softer version of the same leak.
    `observable_signature` is shown instead, being the agent-visible half by definition.
    """
    event = scenario.events[0] if scenario.events else None
    return ScenarioInfo(
        scenario_id=scenario.scenario_id,
        label=(_humanise_label(event.label) if event else fallback_id),
        description=event.description if event else "",
        self_nation=scenario.self_nation,
        adversary_nation=scenario.adversary_nation,
        n_events=len(scenario.events),
        observable_signature=list(event.observable_signature) if event else [],
    )


def _default_arm(state: SessionState) -> str:
    """The arm a page opens on: a full-loop one, not the control.

    The control's distribution is the base rate the others are measured against, not a
    result anyone opened the page to read. Opening on it would put the least interpretable
    figures in front of the reader first.
    """
    for arm in state.spec.arms:
        if arm != CONTROL_ARM:
            return arm
    return state.spec.arms[0]


def _session_or_404(session_id: str) -> SessionState:
    try:
        return load_session(session_id)
    except SessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _jsonable(value: Any) -> Any:
    """Arm-varied values are plain config scalars, but lists come back as lists."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def main() -> None:  # pragma: no cover - entry point
    """`make api` / `make demo`. Localhost only: this API has no authentication and
    exposes analyst-facing data, so it must not be bound to a public interface."""
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(prog="artsoc-api", description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--static",
        type=Path,
        default=None,
        help="serve a built frontend from this directory on the same port",
    )
    args = parser.parse_args()
    uvicorn.run(create_app(static_dir=args.static), host="127.0.0.1", port=args.port)


__all__ = [
    "ArmInfo",
    "Passage",
    "PassageLookup",
    "RepresentativeView",
    "ScenarioInfo",
    "SessionCreated",
    "create_app",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    main()
