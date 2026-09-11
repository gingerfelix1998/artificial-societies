"""The orchestration loop and the Monte Carlo runner.

Hand-rolled on purpose. `CLAUDE.md` forbids an orchestration framework here because every
prompt, seed and selection has to be recoverable from an output record, and a framework's
internal prompt handling would sit inside the access matrix without being tested. The
control flow below is therefore explicit and boring, which is the point.

**One replication is not a result.** `run_once` produces a `RunRecord`; the deliverable is
the distribution of `rung` over many of them, plus the contrast against `escalation_prior`.
A single transcript is an anecdote.

**Arms are configs, not branches.** There is exactly one conditional on arm behaviour in
this module — `config.consult_panel`, which is the structural difference between the
control arm and every other. Everything else varies by parameter. A new arm should never
need a new branch here; if it does, that is a signal the thing being varied belongs in
`RunConfig`.

**`config.audience_enabled` is a second, independent top-level conditional (ADR 0009), not
a violation of the rule above.** The panel-consultation gate above decides whether the
advisory apparatus runs at all; the audience is an orthogonal, post-decision stage that
must be able to run whether or not a panel was consulted (it reacts to `action`, which
exists either way), so it cannot be nested inside that branch the way `convene_excomm` is.
The invariant this file actually holds is "one conditional gating whether the advisory
apparatus runs", not "one conditional in the file" — `routing_mode` inside `_consult`
already varies arm behaviour on a second axis for the same reason. A dedicated test pins
`audience_enabled`'s own occurrence count the same way the panel gate's is pinned.

**`grounded` comes from the retriever, never from the config.** A config could claim
anything; the retriever object knows what it actually did.
"""

from __future__ import annotations

import json
import random
import re
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from artsoc.agents import (
    Advisor,
    CitizenPanelist,
    ExCommMember,
    IntelligenceOfficer,
    President,
    Theorist,
    render_deliberation,
    render_situation,
)
from artsoc.config import RunConfig
from artsoc.llm import DiskCache, LLMClient, estimate_cost, get_backend
from artsoc.personas import (
    Persona,
    load_excomm,
    load_registry,
    panel_coverage,
    route,
    synthetic_panel,
)
from artsoc.retrieval import get_retriever
from artsoc.schema import (
    ActionType,
    AdvisorBrief,
    AnalyticalQuestion,
    Approval,
    AudienceRecord,
    Citizen,
    CitizenFailure,
    CitizenResponse,
    CourseOfAction,
    ExCommStatement,
    IntelBrief,
    PerceivedEvent,
    PresidentialAction,
    PresidentialQuery,
    RoutingRecord,
    RunRecord,
    TheoristOpinion,
    public_statement_from,
)
from artsoc.society import Frame, load_frame, sample_citizens
from artsoc.world import PerceptionFilter, Scenario, build_world, load_scenario, public_events_from

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / ".cache" / "llm"
DEFAULT_OUT_DIR = REPO_ROOT / "out"


def forbidden_tokens(scenario: Scenario) -> list[str]:
    """Scenario terms that must not reach a role without collection access.

    Derived from the scenario rather than hardcoded, so a new scenario guards itself
    instead of silently inheriting the first one's proper nouns.
    """
    tokens = {scenario.self_nation, scenario.adversary_nation}
    for event in scenario.events:
        tokens.update(part for part in event.label.split("_") if len(part) > 2)
    return sorted(t for t in tokens if t)


def _retriever_for(config: RunConfig):
    """The retriever an arm asks for, with its threshold applied.

    Only the corpus retriever takes the knobs; the stub does no relevance selection at all,
    so passing them would imply a choice it does not make.
    """
    if config.retrieval_mode == "corpus":
        return get_retriever(
            "corpus",
            top_k=config.retrieval_top_k,
            min_terms=config.retrieval_min_terms,
            belief_min_terms=config.retrieval_belief_min_terms,
            claim_min_terms=config.retrieval_claim_min_terms,
            claim_top_k=config.retrieval_claim_top_k,
        )
    return get_retriever(config.retrieval_mode)


def build_panel(config: RunConfig, rng: random.Random) -> list[Persona]:
    """The personas available to this replication.

    Exclusion happens here, before anything else sees the registry, which is what makes
    "the world operates as though they never existed" true rather than aspirational: an
    excluded persona is absent from the panel, therefore from every roster the Advisor is
    shown, therefore from every prompt. Filtering later — at routing, say — would leave
    them visible to the Advisor as someone it declined to pick.

    Sampling to `panel_size` uses the run rng rather than taking the first N, so a small
    panel is not always the same personas — otherwise `small_panel` would measure "these
    four theorists" rather than "a panel of four".
    """
    if config.panel_source == "synthetic":
        pool = synthetic_panel(config.panel_size, seed=rng.randrange(2**32))
    else:
        pool = load_registry()

    excluded = set(config.excluded_personas)
    if excluded:
        known = {p.persona_id for p in pool}
        unknown = sorted(excluded - known)
        if unknown:
            # An arm that excludes a persona who does not exist silently tests nothing:
            # it would run, produce a distribution, and be indistinguishable from baseline.
            raise ValueError(
                f"arm {config.arm!r} excludes unknown personas {unknown}; "
                f"available: {sorted(known)}"
            )
        pool = [p for p in pool if p.persona_id not in excluded]

    if config.panel_size >= len(pool):
        return pool
    return rng.sample(pool, config.panel_size)


def build_excomm(config: RunConfig, rng: random.Random):
    """The deliberative committee for this replication (ADR 0008).

    Mirrors `build_panel`: the whole roster unless `excomm_size` caps it smaller, in which
    case the run rng samples — so a future `small_excomm` arm measures "a committee of N"
    rather than "these N seats".
    """
    roster = load_excomm()
    if config.excomm_size and config.excomm_size < len(roster):
        return rng.sample(roster, config.excomm_size)
    return roster


@dataclass
class _Deliberation:
    """What the advisory half produced past the courses of action (ADR 0008).

    Defaults are the control-arm shape: no lean, no debate. `transcript` is the final
    rendered debate, kept here so `run_once` can hand it to `President.decide` without
    needing the roster.
    """

    lean_action: ActionType | None = None
    lean_coa_id: str | None = None
    lean_reasoning: str = ""
    statements: list[ExCommStatement] = field(default_factory=list)
    rounds: int = 0
    transcript: str = ""


def _deliberate(
    config: RunConfig,
    client: LLMClient,
    scenario: Scenario,
    intel,
    view: list[PerceivedEvent],
    brief: AdvisorBrief,
    coas: list[CourseOfAction],
    rng: random.Random,
) -> _Deliberation:
    """Record the President's prior, then run the committee if `convene_excomm` is set.

    Sequential by construction — round-robin, each turn depends on the last — so it never
    touches the theorist fan-out's concurrency and the "same record at any concurrency"
    guarantee holds because there is nothing here to reorder.
    """
    lean_action, lean_coa_id, lean_reasoning = President(
        client, scenario.doctrine_card
    ).lean(intel, brief, coas)
    result = _Deliberation(
        lean_action=lean_action, lean_coa_id=lean_coa_id, lean_reasoning=lean_reasoning
    )
    if not config.convene_excomm:
        return result

    roster = build_excomm(config, rng)
    situation = render_situation(intel, view)
    chair = President(client, scenario.doctrine_card)
    for round_no in range(1, config.deliberation_max_rounds + 1):
        result.rounds = round_no
        for member in roster:
            transcript = render_deliberation(result.statements, roster)
            result.statements.append(
                ExCommMember(client, member).contribute(
                    round_no, situation, brief, coas, transcript
                )
            )
        if (
            chair.chair(
                round_no,
                config.deliberation_max_rounds,
                render_deliberation(result.statements, roster),
            )
            == "conclude"
        ):
            break
    result.transcript = render_deliberation(result.statements, roster)
    return result


def _consult(
    config: RunConfig,
    client: LLMClient,
    scenario: Scenario,
    intel,
    view: list[PerceivedEvent],
    rng: random.Random,
    panel: list[Persona],
    retriever,
) -> tuple[PresidentialQuery, list[AnalyticalQuestion], list[RoutingRecord],
           list[TheoristOpinion], AdvisorBrief, list[CourseOfAction], list[str],
           _Deliberation]:
    """The advisory half of the loop: query, panel, brief.

    Split out so `run_once` reads as the sequence it is, and so the control arm's absence
    of all this is one `if` rather than a scatter of them.

    **The retriever is passed in, never built here.** `run_once` reads provenance off the
    object that did the retrieving, so a second instance would leave it reporting on a
    retriever that never served anything. That went unnoticed while `mode` and `grounded`
    were class attributes — identical on any instance — and became wrong the moment
    `corpus_tier` recorded what actually happened.
    """
    president = President(client, scenario.doctrine_card)
    query = president.query(intel, forbidden_tokens(scenario))

    advisor = Advisor(client)
    questions = advisor.formulate(query, config.n_questions)

    routing: list[RoutingRecord] = []
    by_id = {p.persona_id: p for p in panel}

    # Routing stays sequential: each selection consumes the run rng, and reordering those
    # draws would change which personas are chosen.
    jobs: list[tuple[int, AnalyticalQuestion, str]] = []
    for question in questions:
        # The only branch on arm behaviour in the consultation path. `advisor` models the
        # social act of choosing whom to ask and records the reason; `tag` is the
        # mechanical control that needs no model and is exactly reproducible.
        if config.routing_mode == "advisor":
            record = advisor.select(query, question, panel, config.k_per_question, rng)
        else:
            record = route(question, panel, k=config.k_per_question, rng=rng)
        routing.append(record)
        for persona_id in record.selected:
            jobs.append((len(jobs), question, persona_id))

    def ask(job: tuple[int, AnalyticalQuestion, str]):
        index, question, persona_id = job
        theorist = Theorist(client, by_id[persona_id], config.persona_method, retriever)
        opinion, block = theorist.opine(question)
        return index, opinion, theorist.unsupported_citations(opinion, block)

    # The one place fanning out is safe: theorist calls cannot see each other by design, so
    # nothing about one depends on another having finished. Results are keyed by index and
    # re-sorted, so the record is ordered by (question, persona) whatever order they return
    # in — a run must produce the same record at any concurrency, which a test pins.
    if config.max_concurrency > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=config.max_concurrency) as pool:
            results = list(pool.map(ask, jobs))
    else:
        results = [ask(job) for job in jobs]
    results.sort(key=lambda r: r[0])

    opinions = [opinion for _, opinion, _ in results]
    unsupported = [cite for _, _, cites in results for cite in cites]

    brief = advisor.synthesise(query, opinions, config.synthesis_mode)
    coas = advisor.propose_coas(query, opinions)
    deliberation = _deliberate(config, client, scenario, intel, view, brief, coas, rng)
    return query, questions, routing, opinions, brief, coas, unsupported, deliberation


#: Response-content leakage markers (ADR 0009): parametric knowledge the model produced
#: unprompted, not a prompt-boundary breach (that is `assert_decontextualised`, at
#: prompt-build time in `agents.CitizenPanelist.respond`). Whole-word, case-insensitive.
_LEAKAGE_MARKERS: tuple[str, ...] = (
    "Cuba",
    "Cuban",
    "Kennedy",
    "Khrushchev",
    "Castro",
    "missile crisis",
)
#: Any year after the scenario's own setting reads as post-1962 leakage.
_LEAKAGE_YEAR = re.compile(r"\b(19[6-9][3-9]|20\d{2})\b")


def _leaks(text: str) -> bool:
    if _LEAKAGE_YEAR.search(text):
        return True
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _LEAKAGE_MARKERS)


def _audience_forbidden_tokens(
    panel: list[Persona],
    opinions: list[TheoristOpinion],
    deliberation: _Deliberation,
    intel: IntelBrief,
    ground_truth: dict[str, str],
) -> list[str]:
    """Every theorist name/id, every claim/chunk id an opinion cited, every ExComm
    participant label, the intel brief text, and every `ground_truth_detail` string (ADR
    0009's list). Guarded even under `escalation_prior`, where `panel` is empty because no
    panel was consulted — the full registry stands in so the guard still has names to
    check rather than nothing.
    """
    named = panel if panel else load_registry()
    tokens: list[str] = [p.persona_id for p in named] + [p.name for p in named]
    for opinion in opinions:
        tokens.append(opinion.position)
        tokens.append(opinion.reasoning)
        tokens.extend(opinion.citations)
    if deliberation.statements:
        roster = load_excomm()
        tokens.extend(m.member_id for m in roster)
        tokens.extend(m.role_title for m in roster)
    tokens.extend([intel.summary, intel.assessed_activity])
    tokens.extend(intel.alternative_explanations)
    tokens.extend(intel.collection_gaps)
    tokens.extend(ground_truth.values())
    if deliberation.lean_reasoning:
        tokens.append(deliberation.lean_reasoning)
    return [t for t in tokens if t]


def _survey_audience(
    config: RunConfig,
    client: LLMClient,
    scenario: Scenario,
    world,
    panel: list[Persona],
    opinions: list[TheoristOpinion],
    deliberation: _Deliberation,
    intel: IntelBrief,
    ground_truth: dict[str, str],
    action: PresidentialAction,
    seed: int,
) -> AudienceRecord:
    """The citizen audience's reaction, strictly after the decision (ADR 0009). An outcome
    measure: nothing computed here is read by anything upstream — it runs after `action`
    already exists and is never passed back into `President.decide` or any earlier call.
    """
    frame = load_frame(config.audience_frame)
    # Own rng stream, exactly as perception's is in `run_once`: turning the audience on or
    # off must not shift panel/routing/perception draws at the same seed, which is what
    # keeps a baseline-vs-baseline+audience contrast clean.
    sample = sample_citizens(frame, config.audience_size, random.Random(seed))
    public_events = public_events_from(world.events)
    statement = public_statement_from(action)
    forbidden = _audience_forbidden_tokens(panel, opinions, deliberation, intel, ground_truth)

    def ask_citizen(
        job: tuple[int, Citizen],
    ) -> tuple[int, CitizenResponse | None, CitizenFailure | None]:
        index, citizen = job
        try:
            response = CitizenPanelist(client, citizen).respond(
                public_events, statement, forbidden
            )
            return index, response, None
        except Exception as exc:  # noqa: BLE001 — a crash must not silently drop a stratum
            return index, None, CitizenFailure(citizen_id=citizen.citizen_id, reason=str(exc))

    jobs = list(enumerate(sample.citizens))
    if config.max_concurrency > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=config.max_concurrency) as pool:
            results = list(pool.map(ask_citizen, jobs))
    else:
        results = [ask_citizen(job) for job in jobs]
    results.sort(key=lambda r: r[0])

    responses = [r for _, r, _ in results if r is not None]
    failures = [f for _, _, f in results if f is not None]

    return _assemble_audience_record(
        frame, config.audience_frame, seed, sample, responses, failures
    )


def _assemble_audience_record(
    frame: Frame,
    frame_name: str,
    seed: int,
    sample,
    responses: list[CitizenResponse],
    failures: list[CitizenFailure],
) -> AudienceRecord:
    weights = {c.citizen_id: c.weight for c in sample.citizens}
    total_weight = sum(weights.values()) or 1.0

    unweighted: dict[str, float] = {}
    weighted: dict[str, float] = {}
    for response in responses:
        key = response.approval.value
        unweighted[key] = unweighted.get(key, 0.0) + 1
        weighted[key] = weighted.get(key, 0.0) + weights.get(response.citizen_id, 0.0)
    n_responses = len(responses) or 1
    unweighted = {k: v / n_responses for k, v in unweighted.items()}
    weighted = {k: v / total_weight for k, v in weighted.items()}

    n_sampled = len(sample.citizens) or 1
    response_rate = len(responses) / n_sampled

    answered = [r for r in responses if not r.refused]
    no_opinion_rate = (
        sum(1 for r in answered if r.approval == Approval.NO_OPINION) / len(answered)
        if answered
        else 0.0
    )
    leaked = sum(1 for r in responses if r.rationale and _leaks(r.rationale))
    leakage_rate = leaked / len(responses) if responses else 0.0

    validation_distance: dict[str, float] = {}
    for dim, targets in frame.validation_dimensions.items():
        achieved: dict[str, float] = {}
        for citizen in sample.citizens:
            category = getattr(citizen, dim, None)
            if category is None:
                continue
            achieved[category] = achieved.get(category, 0.0) + weights.get(citizen.citizen_id, 0.0)
        achieved = {k: v / total_weight for k, v in achieved.items()}
        categories = set(targets) | set(achieved)
        distance = sum(abs(targets.get(k, 0.0) - achieved.get(k, 0.0)) for k in categories)
        validation_distance[dim] = round(distance, 4)

    return AudienceRecord(
        frame=frame_name,
        sample_seed=seed,
        citizens=sample.citizens,
        responses=responses,
        failures=failures,
        target_marginals=sample.target_marginals,
        achieved_marginals=sample.achieved_marginals,
        weighted_approval=weighted,
        unweighted_approval=unweighted,
        response_rate=round(response_rate, 4),
        leakage_rate=round(leakage_rate, 4),
        no_opinion_rate=round(no_opinion_rate, 4),
        stratum_coverage=sample.stratum_coverage,
        validation_distance=validation_distance,
    )


def run_once(config: RunConfig, seed: int, *, use_disk_cache: bool = True) -> RunRecord:
    """One replication, start to finish, fully recorded.

    Everything needed to reproduce and audit the decision goes into the record: the config,
    the seed, what was perceived and what was missed, the routing, the opinions, the brief,
    and the action. `host_ground_truth` is included for the analyst to score misperception
    against — it is host-side output and never re-enters a prompt.
    """
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()

    scenario = load_scenario(config.scenario_id)
    rng = random.Random(seed)

    world = build_world(scenario)
    # Perception gets its own rng stream so that adding or removing an advisory call
    # cannot shift what the nation saw. Otherwise escalation_prior and baseline would
    # differ in perception as well as in advice, and the contrast would be confounded.
    view, missed = PerceptionFilter(scenario.self_nation, scenario.perception).view(
        world, scenario.now, random.Random(seed)
    )

    cache = DiskCache(CACHE_DIR) if use_disk_cache else None
    client = LLMClient(
        backend=get_backend(
            config.backend,
            config.resolved_models(),
            effort=config.effort,
            max_parse_retries=config.max_parse_retries,
            max_api_retries=config.max_api_retries,
        ),
        run_seed=seed,
        cache=cache,
        cache_enabled=config.cache_enabled,
    )
    retriever = _retriever_for(config)

    intel = IntelligenceOfficer(client).brief(view, scenario.doctrine_card)

    panel = build_panel(config, rng) if config.consult_panel else []
    query: PresidentialQuery | None = None
    questions: list[AnalyticalQuestion] = []
    routing: list[RoutingRecord] = []
    opinions: list[TheoristOpinion] = []
    brief: AdvisorBrief | None = None
    coas: list[CourseOfAction] = []
    unsupported: list[str] = []
    deliberation = _Deliberation()

    if config.consult_panel:
        (
            query, questions, routing, opinions, brief, coas, unsupported, deliberation
        ) = _consult(config, client, scenario, intel, view, rng, panel, retriever)

    # `coas` stays [] under the control arm, and President.decide's free-choice path is
    # what runs when the list is empty — the base-rate measurement every other arm's delta
    # is read against is untouched by ADR 0006 (`decide` treats `coas=None` the same as
    # today; an empty list from a consulted-but-COA-less path would be a design error, so
    # it is passed through honestly rather than coerced to None here).
    #
    # The deliberation transcript is added under `convene_excomm` (ADR 0008); it is "" on
    # every other arm, including the control. The President's secret lean is NOT passed
    # here — it never re-enters a prompt.
    action = President(client, scenario.doctrine_card).decide(
        intel, brief, coas or None, deliberation_transcript=deliberation.transcript
    )

    ground_truth = scenario.ground_truth()

    # A second, independent top-level stage (ADR 0009) — not nested inside the panel gate
    # above like `convene_excomm` is, because the audience must be able to react to the
    # decision whether or not a panel was consulted (it composes with
    # `escalation_prior` too). It runs strictly after `action` exists above and nothing it
    # produces is read by anything before this line.
    audience: AudienceRecord | None = None
    if config.audience_enabled:
        audience = _survey_audience(
            config, client, scenario, world, panel, opinions, deliberation, intel,
            ground_truth, action, seed,
        )

    return RunRecord(
        run_id=f"{config.arm}-{seed}",
        arm=config.arm,
        seed=seed,
        started_at=started_at,
        wall_time_s=round(time.perf_counter() - started, 4),
        config=config.model_dump(),
        backend=config.backend,
        # From the call log, so it reports what served rather than what was configured.
        models=client.models_used(),
        cache_enabled=config.cache_enabled,
        retrieval_mode=retriever.mode,
        # From the retriever object, not the config: only the thing that did the
        # retrieving knows whether it was grounded, or what it grounded in. The tier is
        # read after the panel has run, because it is a fact about what actually served.
        grounded=retriever.grounded,
        corpus_tier=retriever.corpus_tier,
        scenario_id=scenario.scenario_id,
        injected_event_ids=[e.event_id for e in scenario.events],
        host_ground_truth=ground_truth,
        view=view,
        detected_event_ids=[e.event_id for e in view],
        missed_event_ids=missed,
        intel_brief=intel,
        presidential_query=query,
        questions=questions,
        routing=routing,
        opinions=opinions,
        advisor_brief=brief,
        courses_of_action=coas,
        unsupported_citations=unsupported,
        action=action,
        rung=action.rung,
        # ADR 0008. `None`/`[]`/`0` on the control arm and whenever `convene_excomm` is
        # false but a lean was still recorded; the lean's `_reasoning` is host-only.
        secret_lean=deliberation.lean_action,
        secret_lean_coa_id=deliberation.lean_coa_id,
        secret_lean_reasoning=deliberation.lean_reasoning,
        deliberation=deliberation.statements,
        deliberation_rounds=deliberation.rounds,
        # ADR 0009. `None` unless `audience_enabled` was set on this arm.
        audience=audience,
        panel_size=len(panel),
        personas_consulted=sorted(panel_coverage(routing)),
        llm_calls=client.calls,
        cache_hits=client.cache_hits,
        retries=client.retries,
        token_usage={m: list(v) for m, v in getattr(client.backend, "usage", {}).items()},
        est_cost_usd=estimate_cost(getattr(client.backend, "usage", {})),
    )


def run_many(
    config: RunConfig,
    n: int,
    seed0: int = 1,
    failures: list[tuple[int, str]] | None = None,
) -> Iterator[RunRecord]:
    """`n` replications with consecutive seeds. Failures are recorded, never swallowed.

    Seeds are consecutive from `seed0` rather than random so that a sweep is reproducible
    from two integers, and so a single replication can be re-run in isolation.

    **A failed replication is recorded and skipped.** Pass a list as `failures` to collect
    `(seed, reason)`; the caller reports them and `metrics` states how many were attempted.

    Neither alternative is acceptable. Aborting loses a sweep at replication 1,847, which
    is how people start disabling checks. Dropping silently is worse: a replication may
    fail for reasons correlated with its outcome — a long theorist answer that exceeded a
    token limit is not a random sample — so a distribution over the survivors would be
    quietly biased with nothing in the record to show it.
    """
    if n < 1:
        raise ValueError("n must be at least 1")
    for i in range(n):
        seed = seed0 + i
        try:
            yield run_once(config, seed)
        except Exception as exc:  # noqa: BLE001 - any failure is data, not a crash
            if failures is None:
                raise
            failures.append((seed, f"{type(exc).__name__}: {exc}"))


def write_jsonl(records: Iterable[RunRecord], path: Path, *, append: bool = False) -> int:
    """Write records as JSON lines. Returns how many were written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    written = 0
    with path.open(mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.model_dump(mode="json")) + "\n")
            written += 1
    return written
