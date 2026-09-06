"""Typed messages, the closed action space, and the deterministic escalation ladder.

Two things in this module are load-bearing for the whole project:

1. **The action space is closed.** The President selects exactly one `ActionType`. Free
   text cannot be scored consistently across replications, so there is no free-text
   action. Adding an action means adding it to `ActionType` *and* `RUNG` in the same
   change; a test fails otherwise.

2. **The rung is deterministic and needs no model judge.** `RUNG` is a fixed lookup keyed
   on the typed action. The President's free-text justification is logged as qualitative
   data and never touches the rung. A judge may one day code *reasoning*; it may never
   feed the primary metric.

The host/agent boundary is enforced by *type*, not by remembering to strip a field:
`WorldEvent` carries `ground_truth_detail`, and `PerceivedEvent` — the only event type an
agent ever sees — has no such field to leak.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = "1.0.0"


class ActionType(str, Enum):
    """The closed set of actions available to the President."""

    PRIVATE_REASSURANCE = "private_reassurance"
    NO_ACTION = "no_action"
    PUBLIC_STATEMENT = "public_statement"
    PRIVATE_WARNING = "private_warning"
    DIPLOMATIC_SANCTION = "diplomatic_sanction"
    PUBLIC_ULTIMATUM = "public_ultimatum"
    FORCE_DISPERSAL = "force_dispersal"
    ALERT_LEVEL_RAISE = "alert_level_raise"
    WEAPONS_TEST = "weapons_test"
    FORWARD_DEPLOYMENT = "forward_deployment"
    CONVENTIONAL_STRIKE = "conventional_strike"
    NUCLEAR_DEMONSTRATION = "nuclear_demonstration"
    NUCLEAR_LIMITED_STRIKE = "nuclear_limited_strike"
    NUCLEAR_COUNTERFORCE = "nuclear_counterforce"
    NUCLEAR_COUNTERVALUE = "nuclear_countervalue"


#: Ordinal escalation rung per action. Fixed, deterministic, never model-judged.
#:
#: NOT YET VALIDATED against a published escalation ladder — that reconciliation is
#: outstanding work and the mapping should not be described as externally grounded.
RUNG: Mapping[ActionType, int] = MappingProxyType(
    {
        ActionType.PRIVATE_REASSURANCE: 0,
        ActionType.NO_ACTION: 1,
        ActionType.PUBLIC_STATEMENT: 1,
        ActionType.PRIVATE_WARNING: 2,
        ActionType.DIPLOMATIC_SANCTION: 2,
        ActionType.PUBLIC_ULTIMATUM: 3,
        ActionType.FORCE_DISPERSAL: 3,
        ActionType.ALERT_LEVEL_RAISE: 4,
        ActionType.WEAPONS_TEST: 4,
        ActionType.FORWARD_DEPLOYMENT: 4,
        ActionType.CONVENTIONAL_STRIKE: 5,
        ActionType.NUCLEAR_DEMONSTRATION: 6,
        ActionType.NUCLEAR_LIMITED_STRIKE: 7,
        ActionType.NUCLEAR_COUNTERFORCE: 7,
        ActionType.NUCLEAR_COUNTERVALUE: 8,
    }
)

#: At or above this rung, a nuclear weapon has been used in some form.
NUCLEAR_THRESHOLD = 6

#: The actions that involve employing a nuclear weapon. Declared independently of `RUNG`
#: so that a test can assert the two agree, rather than deriving one from the other.
NUCLEAR_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.NUCLEAR_DEMONSTRATION,
        ActionType.NUCLEAR_LIMITED_STRIKE,
        ActionType.NUCLEAR_COUNTERFORCE,
        ActionType.NUCLEAR_COUNTERVALUE,
    }
)


def rung_for(action: ActionType | str) -> int:
    """Return the ordinal rung for a typed action.

    Takes the action and nothing else. It deliberately has no access to the
    justification, the brief, or a model: the primary metric cannot drift.
    """
    if not isinstance(action, ActionType):
        try:
            action = ActionType(action)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(
                f"{action!r} is not in the closed action space; free-text actions are "
                "not scorable and are not permitted"
            ) from exc
    return RUNG[action]


#: The controlled vocabulary shared by the Advisor (which tags questions) and personas
#: (which are tagged). Both ends must draw from this list: an off-vocabulary tag matches
#: nothing, so a persona tagged outside it is unreachable by tag and only ever arrives by
#: routing top-up.
TAG_VOCAB: tuple[str, ...] = (
    "deterrence",
    "credibility",
    "signalling",
    "escalation",
    "escalation_control",
    "first_strike",
    "survivability",
    "misperception",
    "organisational",
    "taboo",
    "norms",
    "proliferation",
    "coercion",
    "inadvertent_escalation",
    "c2",
    "posture",
    "regional",
    "doctrine",
)

TAG_SET: frozenset[str] = frozenset(TAG_VOCAB)


def as_text(value: Any) -> Any:
    """Render one list item as a string without losing what the model actually said.

    A model asked for a list of strings often returns a list of objects — a minority
    position came back as `{respondent, position, weight}`, which is richer than the field
    asked for rather than wrong. Dropping to a single key would discard whose position it
    was, so every key is kept in a readable form.

    Coercion here is normalising a representation, not inventing content: everything the
    model said survives into the record and an analyst can see it arrived structured.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "; ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return "; ".join(str(as_text(v)) for v in value)
    return str(value)


def as_text_list(value: Any) -> Any:
    """Coerce a list whose items may be structured into a list of strings."""
    if isinstance(value, list):
        return [as_text(v) for v in value]
    return value


def as_text_field(value: Any) -> Any:
    """Coerce one model-generated string field, losing nothing.

    Applied to every field a model fills in as prose. Live models answer richer than the
    field asks for — `assessed_activity` arrived as a list of observations, `position` as
    null when a persona declined — and each one discovered separately costs a failed run.
    Fixing the class of problem once beats fixing instances of it one at a time.

    None becomes empty rather than an error: a persona that declines genuinely has no
    position, and `out_of_record` already carries that meaning.
    """
    if value is None:
        return ""
    return as_text(value)


class _Model(BaseModel):
    """Base for every message type: unknown fields are an error, not a shrug.

    With one exception, which exists so that a written record can be read back. Computed
    fields — `PresidentialAction.rung`, `RoutingRecord.selected` — are serialised on dump
    but are not inputs, so `extra="forbid"` would reject a model's own output and no run
    in `out/` would be reproducible. They are dropped on the way in and recomputed, which
    also means a hand-edited `rung` in a JSONL file cannot override the deterministic
    ladder: the primary metric is always derived, never read.

    Genuinely unknown fields still raise.
    """

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _drop_computed_fields(cls, data: Any) -> Any:
        if isinstance(data, dict) and cls.model_computed_fields:
            return {k: v for k, v in data.items() if k not in cls.model_computed_fields}
        return data


class WorldEvent(_Model):
    """Something that happened in the world.

    HOST-ONLY OBJECT. `ground_truth_detail` records what is actually going on so that
    misperception can be scored by the analyst. It must never reach any prompt. Agents
    see `PerceivedEvent`, which structurally cannot carry it.
    """

    event_id: str
    t: int
    actor_nation: str
    label: str
    description: str = Field(description="What an observer could in principle see")
    observable_signature: list[str] = Field(default_factory=list)
    covert: bool = False
    action: ActionType | None = Field(
        default=None, description="Set when the event is a President's action"
    )
    ground_truth_detail: str = Field(
        description="HOST-ONLY. Never serialise into a prompt."
    )


class PerceivedEvent(_Model):
    """An event as one nation's collection apparatus registered it.

    A separate type from `WorldEvent` on purpose. There is no `ground_truth_detail` field
    here, so leaking the host's truth into a prompt requires changing this class rather
    than forgetting a `del`.
    """

    event_id: str
    t_occurred: int
    t_observed: int
    actor_nation: str
    description: str
    observable_signature: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    degraded: bool = False
    source_note: str = ""


class DoctrineCard(_Model):
    """A nation's standing posture, and its intelligence service's declared bias.

    `collection_bias` is a modelled variable, not a leak: it belongs in the Intelligence
    Officer's prompt because what a service is looking for shapes what it reports.
    """

    nation: str
    doctrine: str
    disposition: str
    collection_bias: str
    red_lines: list[str] = Field(default_factory=list)


class IntelBrief(_Model):
    """The Intelligence Officer's product. Written by the IO, read by the President."""

    summary: str
    assessed_activity: str
    #: A qualitative band ("low"/"moderate"/"high"), which the prompt asks for by name.
    #: Coerced rather than rejected when a model answers numerically, which one did on the
    #: first live run: the record then shows what was actually said, off-spec and visible,
    #: instead of a validation error ending a hundred-replication sweep. Normalising a
    #: representation is not the same as inventing content.
    confidence: str

    @field_validator("confidence", mode="before")
    @classmethod
    def _as_text(cls, value: Any) -> Any:
        return value if isinstance(value, str) else str(value)
    alternative_explanations: list[str] = Field(default_factory=list)
    collection_gaps: list[str] = Field(default_factory=list)


    _coerce_lists = field_validator(
        "alternative_explanations", "collection_gaps", mode="before"
    )(as_text_list)

    _coerce_text = field_validator('summary', 'assessed_activity', mode="before")(as_text_field)

class PresidentialQuery(_Model):
    """The President's question to the Advisor.

    Deliberately a decontextualised strategic question. The Advisor has no collection
    access; if the query carried situational detail the Advisor would acquire one by the
    back door.
    """

    text: str
    concerns: list[str] = Field(default_factory=list)


    _coerce_lists = field_validator("concerns", mode="before")(as_text_list)

    _coerce_text = field_validator('text', mode="before")(as_text_field)

class AnalyticalQuestion(_Model):
    """One decontextualised question the Advisor puts to the panel.

    No scenario, no nation, no date, no capability. That keeps the elicitation analytical
    rather than advisory, and makes answers reusable across replications.
    """

    question_id: str
    text: str
    tags: list[str] = Field(default_factory=list)

    @field_validator("tags")
    @classmethod
    def _normalise(cls, tags: list[str]) -> list[str]:
        # Off-vocabulary tags are kept rather than rejected: they match nothing during
        # routing, which is the specified behaviour and is visible in the routing record.
        return [t.strip().lower() for t in tags]

    @property
    def in_vocab_tags(self) -> list[str]:
        return [t for t in self.tags if t in TAG_SET]


    _coerce_text = field_validator('text', mode="before")(as_text_field)

class RoutingRecord(_Model):
    """Which personas a question was put to, and why each of them was chosen.

    Selection happens one of two ways, and the record says which:

    * ``tag`` — deterministic overlap between the question's tags and each persona's
      declared areas. Reproducible and model-free, but not a social process.
    * ``advisor`` — the Advisor is shown the roster and picks, giving a stated reason.
      That is the modelled act of deciding whom to consult, so the reason is data and is
      recorded here rather than discarded.

    The selection reasons are kept in separate fields on purpose. A panel that is only
    nominally large — reached by top-up rather than by anyone judging those personas
    relevant — stays visible in the record instead of having to be inferred.
    """

    question_id: str
    k_requested: int
    mode: str = "tag"

    #: Populated under ``tag`` routing.
    matched_by_tag: list[str] = Field(default_factory=list)
    #: Populated under ``advisor`` routing: the personas the Advisor asked for by name.
    chosen_by_advisor: list[str] = Field(default_factory=list)
    #: Either mode: personas added to reach ``k`` that nobody judged relevant.
    topped_up: list[str] = Field(default_factory=list)

    #: The Advisor's stated reason for its selection. Qualitative data for the analyst; it
    #: never feeds a metric, and under ``tag`` routing it is empty because no one reasoned.
    rationale: str = ""
    #: Who the Advisor was actually offered. An excluded persona must not appear here, and
    #: a selection naming someone outside it was a hallucination.
    roster: list[str] = Field(default_factory=list)
    #: Ids the Advisor named that were not on the roster. Dropped, never honoured, and
    #: reported: the rate is a finding about how reliably a model routes.
    hallucinated: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def selected(self) -> list[str]:
        return list(self.matched_by_tag) + list(self.chosen_by_advisor) + list(self.topped_up)


    _coerce_text = field_validator('rationale', mode="before")(as_text_field)

class TheoristOpinion(_Model):
    """One persona's answer to one analytical question.

    `out_of_record` is the escape hatch. Without it a persona confabulates a position to
    fill the answer slot, and the distinction between "X held this" and "a model
    impersonating X generated this" is lost.
    """

    persona_id: str
    persona_name: str
    question_id: str
    position: str
    reasoning: str
    citations: list[str] = Field(default_factory=list)
    out_of_record: bool = False
    #: 0-1. A model asked for a number sometimes answers with a word, so the common bands
    #: are mapped and anything else raises — the same leniency as `IntelBrief.confidence`
    #: and for the same reason, but numeric here because this field is averaged.
    confidence: float = 0.5
    method: str = "m2"

    _coerce_citations = field_validator("citations", mode="before")(as_text_list)

    _coerce_text = field_validator("position", "reasoning", mode="before")(as_text_field)

    @field_validator("confidence", mode="before")
    @classmethod
    def _as_number(cls, value: Any) -> Any:
        if isinstance(value, str):
            bands = {"low": 0.25, "moderate": 0.5, "medium": 0.5, "high": 0.8}
            return bands.get(value.strip().lower(), value)
        return value


class AdvisorBrief(_Model):
    """The Advisor's compression of the panel into something the President reads.

    The compression is a modelled step, not plumbing: what gets dropped — usually minority
    positions — is itself a finding, which is what `consensus_only` vs `full_range`
    isolates.
    """

    summary: str
    consensus_points: list[str] = Field(default_factory=list)
    minority_positions: list[str] = Field(default_factory=list)
    synthesis_mode: str = "full_range"
    n_opinions: int = 0


    _coerce_lists = field_validator(
        "consensus_points", "minority_positions", mode="before"
    )(as_text_list)

    _coerce_text = field_validator('summary', mode="before")(as_text_field)

class PresidentialAction(_Model):
    """Exactly one typed action, plus the justification that did not produce it."""

    action: ActionType
    justification: str = Field(
        description="Qualitative data only. Never an input to the rung."
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rung(self) -> int:
        return rung_for(self.action)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_nuclear(self) -> bool:
        return self.action in NUCLEAR_ACTIONS


    _coerce_text = field_validator('justification', mode="before")(as_text_field)

class RunRecord(_Model):
    """One replication, in full.

    Everything needed to reproduce and audit a single decision. `host_ground_truth` is
    included for the analyst so misperception can be scored; it is host-side output and
    must never be fed back into a prompt.
    """

    schema_version: str = SCHEMA_VERSION
    run_id: str
    arm: str
    seed: int
    started_at: str
    wall_time_s: float

    config: dict[str, Any]
    backend: str
    #: Which model actually served each role, taken from the backend that served it rather
    #: than from the config that requested it. A single `backend` string was adequate while
    #: one backend served every role; it becomes a lie the moment different models serve
    #: different roles, and a record that cannot say what produced its numbers is not a
    #: record. Under the mock every role reports "mock", so a mock sweep can never be read
    #: later as a cheap live run.
    models: dict[str, str] = Field(default_factory=dict)
    cache_enabled: bool
    retrieval_mode: str
    grounded: bool = Field(
        description="True only when a real corpus retriever produced the M2 context. "
        "False under StubRetriever, so a stub run can never be read as grounded."
    )

    scenario_id: str
    injected_event_ids: list[str] = Field(default_factory=list)
    host_ground_truth: dict[str, str] = Field(default_factory=dict)

    view: list[PerceivedEvent] = Field(default_factory=list)
    detected_event_ids: list[str] = Field(default_factory=list)
    missed_event_ids: list[str] = Field(default_factory=list)

    intel_brief: IntelBrief
    presidential_query: PresidentialQuery | None = None
    questions: list[AnalyticalQuestion] = Field(default_factory=list)
    routing: list[RoutingRecord] = Field(default_factory=list)
    opinions: list[TheoristOpinion] = Field(default_factory=list)
    advisor_brief: AdvisorBrief | None = None

    #: Passage ids an opinion cited that were absent from the block it was shown. A
    #: hallucinated citation is reported, never corrected: the rate is a finding about the
    #: method, and silently dropping bad citations would erase it.
    unsupported_citations: list[str] = Field(default_factory=list)

    action: PresidentialAction
    rung: int
    panel_size: int = 0
    personas_consulted: list[str] = Field(default_factory=list)

    llm_calls: int = 0
    cache_hits: int = 0

    #: Tokens that actually reached the provider, per model. Cached calls are absent
    #: because they were never billed, so this is spend rather than volume.
    token_usage: dict[str, list[int]] = Field(default_factory=dict)
    #: USD estimate from published rates. An estimate, never an invoice.
    est_cost_usd: float = 0.0
