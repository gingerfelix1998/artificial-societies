"""The four roles, and the context boundaries each one is held to.

This module is where invariant 1 is actually implemented. `tests/test_access_matrix.py`
checks it from the outside by scanning every prompt these roles emit; what follows is the
inside of that guarantee.

The boundaries, and why each exists:

* **The Intelligence Officer** reads `PerceivedEvent`s and its own service's declared
  `collection_bias`. It cannot reach a `WorldEvent`, so `ground_truth_detail` is not
  withheld from it by care — the type it receives has no such field.
* **The President** reads the intelligence brief and the advisory brief. Never raw
  opinions: the compression from many opinions into a few hundred tokens is a modelled
  step, and what it drops is itself a finding.
* **The Advisor** reads the President's query and the opinions it collected. Never
  intelligence reporting — otherwise the brief stops being a compression of expert opinion
  and becomes a second, unlogged analytic layer.
* **A Theorist** reads one decontextualised question and its own record. Never the
  scenario, never another theorist. Peer visibility would make apparent consensus a
  herding artifact of call ordering.

The one path by which situational detail could reach the Advisor is the President's query,
which is written *after* reading the intelligence brief. `assert_decontextualised` closes
it, and raises rather than scrubbing: a leak that is quietly cleaned up is a leak nobody
finds out about.
"""

from __future__ import annotations

import json
from typing import Any

from artsoc.llm import CONSENSUS_MARKER, LLMClient, Role, role_marker
from artsoc.personas import (
    Persona,
    build_identity_prompt,
    build_question_prompt,
)
from artsoc.retrieval import Retriever, verify_citations
from artsoc.schema import (
    TAG_VOCAB,
    ActionType,
    AdvisorBrief,
    AnalyticalQuestion,
    DoctrineCard,
    IntelBrief,
    PerceivedEvent,
    PresidentialAction,
    PresidentialQuery,
    TheoristOpinion,
)

#: Synthesis modes. `consensus_only` drops minority positions; `full_range` keeps them.
#: The contrast between them isolates what compression costs, which is why it is an arm
#: rather than a formatting preference.
SYNTHESIS_MODES: frozenset[str] = frozenset({"full_range", "consensus_only"})


class BoundaryViolation(RuntimeError):
    """Raised when text about to cross a role boundary carries context it must not.

    Not a ValueError: this is not bad input, it is the experiment leaking, and every run
    in `out/` produced after it would be invalid.
    """


def assert_decontextualised(text: str, forbidden_tokens: list[str], *, where: str) -> None:
    """Refuse to pass `text` onward if it carries situational detail.

    Raises rather than redacting. A scrubbed leak still means the upstream role wrote
    situational detail into a channel that is supposed to be analytical, and silently
    cleaning it up would hide that the prompt needs fixing.
    """
    lowered = text.lower()
    found = sorted({t for t in forbidden_tokens if t and t.lower() in lowered})
    if found:
        raise BoundaryViolation(
            f"{where} carries situational detail {found}; the Advisor has no collection "
            "access and a query that smuggles it in would give it one by the back door"
        )


def _parse_json(raw: str, role: Role) -> dict[str, Any]:
    """Parse a backend response, raising on anything malformed.

    A partial salvage would put a half-parsed record into `out/` looking like a complete
    one. A failed call is better than a plausible fabrication.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{role.value} returned malformed JSON: {raw[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{role.value} returned {type(payload).__name__}, expected an object")
    return payload


def _system(role: Role, body: str) -> str:
    """Every system prompt carries its role marker, which the choke point requires."""
    return f"{role_marker(role)} {body}"


# ---------------------------------------------------------------------------
# Intelligence Officer
# ---------------------------------------------------------------------------

_IO_SYSTEM = (
    "You are an intelligence liaison officer. You report what your collection apparatus "
    "observed and what it may mean. Report uncertainty honestly: state alternative "
    "explanations for the same observations, and name what you did not collect. You do "
    "not recommend policy."
)


class IntelligenceOfficer:
    """Turns one nation's partial view of the world into a brief for its President.

    Receives `PerceivedEvent`s only. `WorldEvent.ground_truth_detail` is not filtered out
    here; it is structurally absent from the type this role is given.
    """

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def brief(self, events: list[PerceivedEvent], doctrine: DoctrineCard) -> IntelBrief:
        system = _system(Role.INTEL_OFFICER, _IO_SYSTEM)
        lines = [
            f"YOUR SERVICE'S COLLECTION ORIENTATION: {doctrine.collection_bias}",
            "",
            "REPORTING:",
        ]
        for i, event in enumerate(events):
            # "EVENT " is the token the mock counts; a real model reads the same heading.
            lines.append(f"EVENT {i + 1} (t={event.t_observed}, actor={event.actor_nation})")
            lines.append(f"  {event.description}")
            for element in event.observable_signature:
                lines.append(f"  - {element}")
            lines.append(
                f"  collection confidence {event.confidence}; "
                f"{'degraded' if event.degraded else 'nominal'}; {event.source_note}"
            )
            lines.append("")
        lines.append(
            "Produce JSON with keys: summary, assessed_activity, confidence, "
            "alternative_explanations, collection_gaps."
        )
        payload = _parse_json(
            self.client.complete(role=Role.INTEL_OFFICER, system=system, prompt="\n".join(lines)),
            Role.INTEL_OFFICER,
        )
        return IntelBrief.model_validate(payload)


# ---------------------------------------------------------------------------
# President
# ---------------------------------------------------------------------------

_PRESIDENT_QUERY_SYSTEM = (
    "You are the head of state of a nuclear-armed nation, reading an intelligence brief "
    "during a developing situation. You are about to consult a strategic advisor who has "
    "no access to intelligence reporting and must not acquire any. Ask a general "
    "analytical question about strategy. Do not name any nation, describe the situation, "
    "or repeat anything from the brief."
)

_PRESIDENT_DECISION_SYSTEM = (
    "You are the head of state of a nuclear-armed nation. You have an intelligence brief "
    "and an advisor's synthesis of expert opinion. Select exactly one action from the "
    "closed list you are given, and justify it. The justification is recorded but does "
    "not determine anything."
)


class President:
    """Reads briefs, asks one question, and takes exactly one typed action."""

    def __init__(self, client: LLMClient, doctrine: DoctrineCard) -> None:
        self.client = client
        self.doctrine = doctrine

    def query(self, intel: IntelBrief, forbidden_tokens: list[str]) -> PresidentialQuery:
        """Formulate the decontextualised question that goes to the Advisor.

        `forbidden_tokens` are the scenario's proper nouns. The guard runs on the way out
        rather than trusting the instruction above to have been followed.
        """
        system = _system(Role.PRESIDENT_QUERY, _PRESIDENT_QUERY_SYSTEM)
        prompt = "\n".join(
            [
                f"YOUR STANDING DOCTRINE: {self.doctrine.doctrine}",
                f"YOUR DISPOSITION: {self.doctrine.disposition}",
                "",
                "INTELLIGENCE BRIEF:",
                f"  {intel.summary}",
                f"  assessment: {intel.assessed_activity}",
                f"  confidence: {intel.confidence}",
                "",
                "Produce JSON with keys: text, concerns. `text` must be a general "
                "analytical question about strategy, carrying no situational detail.",
            ]
        )
        payload = _parse_json(
            self.client.complete(role=Role.PRESIDENT_QUERY, system=system, prompt=prompt),
            Role.PRESIDENT_QUERY,
        )
        query = PresidentialQuery.model_validate(payload)

        assert_decontextualised(query.text, forbidden_tokens, where="the presidential query")
        for concern in query.concerns:
            assert_decontextualised(concern, forbidden_tokens, where="a presidential concern")
        return query

    def decide(self, intel: IntelBrief, brief: AdvisorBrief | None) -> PresidentialAction:
        """Select one action. The rung is derived from the action afterwards, not here.

        `brief` is `None` in the `escalation_prior` control arm, where the President has no
        advisory input at all. The advisory section is then omitted rather than sent empty:
        a heading with nothing under it still tells the model an advisor was consulted and
        had nothing to say, which is a different situation from not having one.
        """
        system = _system(Role.PRESIDENT_DECISION, _PRESIDENT_DECISION_SYSTEM)
        lines = [
            f"YOUR STANDING DOCTRINE: {self.doctrine.doctrine}",
            f"YOUR DISPOSITION: {self.doctrine.disposition}",
            "YOUR DECLARED RED LINES:",
            *(f"  - {line}" for line in self.doctrine.red_lines),
            "",
            "INTELLIGENCE BRIEF:",
            f"  {intel.summary}",
            f"  assessment: {intel.assessed_activity}",
            f"  confidence: {intel.confidence}",
            "  alternative explanations:",
            *(f"    - {alt}" for alt in intel.alternative_explanations),
            "  collection gaps:",
            *(f"    - {gap}" for gap in intel.collection_gaps),
            "",
        ]
        if brief is not None:
            lines += [
                # The advisory brief only. Raw opinions are never reproduced here: what the
                # compression dropped is a finding, and showing both would erase it.
                "ADVISOR'S BRIEF:",
                f"  {brief.summary}",
                "  points of consensus:",
                *(f"    - {point}" for point in brief.consensus_points),
                "  minority positions:",
                *(f"    - {pos}" for pos in brief.minority_positions),
                "",
            ]
        lines += [
            "AVAILABLE ACTIONS (choose exactly one):",
            *(f"  - {action.value}" for action in ActionType),
            "",
            "Produce JSON with keys: action, justification.",
        ]
        payload = _parse_json(
            self.client.complete(
                role=Role.PRESIDENT_DECISION,
                system=system,
                prompt="\n".join(lines),
                # The decision must vary with the seed. Caching it would collapse the
                # Monte Carlo distribution to a point mass.
                cacheable=False,
            ),
            Role.PRESIDENT_DECISION,
        )
        return PresidentialAction.model_validate(payload)


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------

_ADVISOR_QUESTIONS_SYSTEM = (
    "You are a strategic advisor, expert across the nuclear-strategy literature. You have "
    "no access to intelligence reporting and no knowledge of any current situation. Break "
    "the question you are given into decontextualised analytical questions that could be "
    "put to a theorist who knows nothing of any crisis. Tag each from the controlled "
    "vocabulary you are given."
)

_ADVISOR_SYNTHESIS_SYSTEM = (
    "You are a strategic advisor. Compress the expert opinions you collected into a brief. "
    "You are not adding analysis of your own and you have no access to intelligence "
    "reporting."
)


class Advisor:
    """Formulates questions for the panel, then compresses what comes back.

    Never receives intelligence reporting. The compression is a modelled step, not
    plumbing — `consensus_only` versus `full_range` is what measures its cost.
    """

    def __init__(self, client: LLMClient) -> None:
        self.client = client

    def formulate(self, query: PresidentialQuery, n_questions: int) -> list[AnalyticalQuestion]:
        system = _system(Role.ADVISOR_QUESTIONS, _ADVISOR_QUESTIONS_SYSTEM)
        prompt = "\n".join(
            [
                # The query only. No brief, no events, no nation.
                "QUESTION FROM THE PRESIDENT:",
                f"  {query.text}",
                "  stated concerns:",
                *(f"    - {c}" for c in query.concerns),
                "",
                f"CONTROLLED TAG VOCABULARY: {', '.join(TAG_VOCAB)}",
                "",
                # The mock reads this marker for the count; a real model reads the
                # sentence around it. Both see the same instruction.
                f"Produce exactly [[N:{n_questions}]] questions as JSON with key "
                "`questions`, each an object with keys `text` and `tags`.",
            ]
        )
        payload = _parse_json(
            self.client.complete(role=Role.ADVISOR_QUESTIONS, system=system, prompt=prompt),
            Role.ADVISOR_QUESTIONS,
        )
        raw = payload.get("questions", [])
        if not isinstance(raw, list) or not raw:
            raise ValueError("the advisor returned no questions")
        return [
            AnalyticalQuestion(
                # Ids are assigned here, not by the model: they key the routing record and
                # must be stable and unique regardless of what came back.
                question_id=f"q{i}",
                text=item["text"],
                tags=list(item.get("tags", [])),
            )
            for i, item in enumerate(raw)
        ]

    def synthesise(
        self,
        query: PresidentialQuery,
        opinions: list[TheoristOpinion],
        mode: str = "full_range",
    ) -> AdvisorBrief:
        if mode not in SYNTHESIS_MODES:
            raise ValueError(f"unknown synthesis mode {mode!r}; expected one of {SYNTHESIS_MODES}")

        system = _system(Role.ADVISOR_SYNTHESIS, _ADVISOR_SYNTHESIS_SYSTEM)
        lines = [
            "QUESTION FROM THE PRESIDENT:",
            f"  {query.text}",
            "",
            "OPINIONS COLLECTED:",
        ]
        for opinion in opinions:
            marker = " [DECLINED — OUT OF RECORD]" if opinion.out_of_record else ""
            lines.append(f"  {opinion.persona_name} (q={opinion.question_id}){marker}")
            lines.append(f"    position: {opinion.position}")
            lines.append(f"    reasoning: {opinion.reasoning}")
        lines.append("")
        if mode == "consensus_only":
            lines.append(
                f"{CONSENSUS_MARKER} Report only points of consensus. Omit minority positions."
            )
        else:
            lines.append(
                "Report points of consensus AND any minority or dissenting positions, "
                "including those held by a single respondent."
            )
        lines.append(
            "Produce JSON with keys: summary, consensus_points, minority_positions."
        )
        payload = _parse_json(
            self.client.complete(
                role=Role.ADVISOR_SYNTHESIS, system=system, prompt="\n".join(lines)
            ),
            Role.ADVISOR_SYNTHESIS,
        )
        return AdvisorBrief(
            summary=payload["summary"],
            consensus_points=list(payload.get("consensus_points", [])),
            minority_positions=list(payload.get("minority_positions", [])),
            synthesis_mode=mode,
            n_opinions=len(opinions),
        )


# ---------------------------------------------------------------------------
# Theorist
# ---------------------------------------------------------------------------


class Theorist:
    """One persona answering one decontextualised question from its own record.

    Holds no reference to the panel, the scenario, or any other persona's output. It is
    constructed with exactly one `Persona` and asked exactly one question at a time, so
    peer visibility is not prevented by discipline — there is nothing to see.
    """

    def __init__(
        self,
        client: LLMClient,
        persona: Persona,
        method: str = "m2",
        retriever: Retriever | None = None,
    ) -> None:
        self.client = client
        self.persona = persona
        self.method = method
        self.retriever = retriever

    def opine(self, question: AnalyticalQuestion) -> tuple[TheoristOpinion, str]:
        """Answer one question. Returns the opinion and the record block it was shown.

        The block comes back so the caller can run `verify_citations` against exactly what
        this persona saw, rather than against a corpus it may not have been given.
        """
        record_block = ""
        if self.method != "m1" and self.retriever is not None:
            record_block = self.retriever.retrieve(self.persona, question.text)

        system = build_identity_prompt(self.persona, self.method)
        # The identity prompt is built by personas.py, which cannot import llm.py, so the
        # role marker is applied here at the boundary instead.
        system = _system(Role.THEORIST, system)
        prompt = build_question_prompt(question, record_block, self.method)
        prompt = (
            f"{prompt}\n\nProduce JSON with keys: position, reasoning, citations, "
            "out_of_record, confidence."
        )

        payload = _parse_json(
            # Cacheable: the question is decontextualised and the record is fixed, so the
            # same persona asked the same question across replications gives the same
            # answer. That is the main cost control.
            self.client.complete(
                role=Role.THEORIST, system=system, prompt=prompt, cacheable=True
            ),
            Role.THEORIST,
        )
        opinion = TheoristOpinion(
            # persona_id and persona_name are host-side bookkeeping. Under M3 the prompt
            # above is anonymous while the record still names which position was used —
            # the analyst needs that, and the persona never sees it.
            persona_id=self.persona.persona_id,
            persona_name=self.persona.name,
            question_id=question.question_id,
            position=payload["position"],
            reasoning=payload["reasoning"],
            citations=list(payload.get("citations", [])),
            out_of_record=bool(payload.get("out_of_record", False)),
            confidence=float(payload.get("confidence", 0.5)),
            method=self.method,
        )
        return opinion, record_block

    def unsupported_citations(self, opinion: TheoristOpinion, record_block: str) -> list[str]:
        """Ids this persona cited that were not in the block it was shown."""
        return verify_citations(opinion.citations, record_block)
