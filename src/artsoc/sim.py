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

**`grounded` comes from the retriever, never from the config.** A config could claim
anything; the retriever object knows what it actually did.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from artsoc.agents import Advisor, IntelligenceOfficer, President, Theorist
from artsoc.config import RunConfig
from artsoc.llm import DiskCache, LLMClient, estimate_cost, get_backend
from artsoc.personas import (
    Persona,
    load_registry,
    panel_coverage,
    route,
    synthetic_panel,
)
from artsoc.retrieval import get_retriever
from artsoc.schema import (
    AdvisorBrief,
    AnalyticalQuestion,
    CourseOfAction,
    PresidentialQuery,
    RoutingRecord,
    RunRecord,
    TheoristOpinion,
)
from artsoc.world import PerceptionFilter, Scenario, build_world, load_scenario

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


def _consult(
    config: RunConfig,
    client: LLMClient,
    scenario: Scenario,
    intel,
    rng: random.Random,
    panel: list[Persona],
    retriever,
) -> tuple[PresidentialQuery, list[AnalyticalQuestion], list[RoutingRecord],
           list[TheoristOpinion], AdvisorBrief, list[CourseOfAction], list[str]]:
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
    return query, questions, routing, opinions, brief, coas, unsupported


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

    if config.consult_panel:
        query, questions, routing, opinions, brief, coas, unsupported = _consult(
            config, client, scenario, intel, rng, panel, retriever
        )

    # `coas` stays [] under the control arm, and President.decide's free-choice path is
    # what runs when the list is empty — the base-rate measurement every other arm's delta
    # is read against is untouched by ADR 0006 (`decide` treats `coas=None` the same as
    # today; an empty list from a consulted-but-COA-less path would be a design error, so
    # it is passed through honestly rather than coerced to None here).
    action = President(client, scenario.doctrine_card).decide(intel, brief, coas or None)

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
        host_ground_truth=scenario.ground_truth(),
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
