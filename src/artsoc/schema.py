"""Typed messages, the closed action space, and the deterministic escalation ladder.

Two things in this module are load-bearing for the whole project:

1. **The action space is closed.** The President selects exactly one `ActionType`. Free
   text cannot be scored consistently across replications, so there is no free-text
   action. Adding an action means adding it to `ActionType` *and* every table in
   `_LADDERS` in the same change; a test fails otherwise.

2. **The rung is deterministic and needs no model judge.** `RUNG_KAHN` (the default) or
   `RUNG_PROJECT` is a fixed lookup keyed on the typed action; `rung_for(action,
   ladder=...)` sees nothing else. The President's free-text justification is logged as
   qualitative data and never touches the rung. A judge may one day code *reasoning*; it
   may never feed the primary metric. See `docs/framework/ladder.md` for what grounds the
   default ladder and what it does and does not license.

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

#: 1.1.0: courses of action (ADR 0006). Not a purely additive bump — the mechanism that
#: produces `action` changed (advisor-curated choice of three, rather than a free choice
#: among all fifteen, under `consult_panel: true`), so a record from before this version
#: cannot be reproduced by re-running the same config and seed against current code.
#:
#: 1.2.0: the claim-indexed markdown corpus (ADR 0007). Bumped on the same reasoning
#: rather than treated as the additive change `corpus_tier` and `corroboration` look like:
#: what a theorist is shown changes, which changes its opinion, which changes the brief and
#: the courses of action, and therefore `action`. Observability alone would not warrant it.
#:
#: 1.3.0: the ExComm deliberation and the secret lean (ADR 0008). Under
#: `convene_excomm: true` the President's decision prompt gains a debate transcript it did
#: not have before, so `action` cannot be reproduced from a pre-1.3.0 config and seed. The
#: `secret_lean` and `deliberation` fields look additive but the mechanism changed — the
#: same test ADR 0006 and 0007 applied.
#:
#: 1.4.0: the citizen audience (ADR 0009). Unlike every prior bump, this one *is* purely
#: additive — `RunRecord.audience` is populated by a stage that runs strictly after
#: `action` is decided and cannot feed back into it (invariant 1; enforced by
#: `tests/test_access_matrix.py`), so a pre-1.4.0 record's `action` is still exactly
#: reproducible from its config and seed. The version still moves, because the shape of
#: `RunRecord` moved and the reason for each bump is recorded here even when, as here, it
#: is the boring reason.
SCHEMA_VERSION = "1.4.0"


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


#: The project's own ordinal escalation table (formerly `RUNG`). Fixed, deterministic,
#: never model-judged — but its own invention: the spacing between levels and the
#: location of its nuclear cutoff were chosen by us, with no external warrant. Kept as a
#: secondary sensitivity ordinal (ADR 0011) so a finding can be checked against a second,
#: independently-numbered scale; no longer the default `rung_for` reads from.
RUNG_PROJECT: Mapping[ActionType, int] = MappingProxyType(
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

#: The default, published escalation ladder (ADR 0011): Herman Kahn, *On Escalation:
#: Metaphors and Scenarios* (Praeger, 1965), forty-four rungs grouped into eight bands
#: 0-7. `docs/framework/ladder.md` is the single source of truth for the band structure,
#: the mapping below, and the four judgement calls it required; this table is the
#: committed artefact — our mapping, not a reproduction of Kahn's full rung table.
#:
#: UNVERIFIED: the individual Kahn rung numbers cited in the trailing comments below are
#: corroborated in outline by secondary treatments only, and have not yet been checked
#: against the primary text. The band structure itself is not in question; a specific
#: rung citation may still need correction.
RUNG_KAHN: Mapping[ActionType, int] = MappingProxyType(
    {
        ActionType.PRIVATE_REASSURANCE: 0,  # Kahn: pre-escalation
        ActionType.NO_ACTION: 0,  # Kahn: pre-escalation
        ActionType.PRIVATE_WARNING: 1,  # Kahn rung 2, political/economic/diplomatic gestures
        ActionType.PUBLIC_STATEMENT: 1,  # Kahn rung 3, solemn and formal declarations
        ActionType.PUBLIC_ULTIMATUM: 2,  # Kahn rung 4, hardening of positions
        ActionType.WEAPONS_TEST: 2,  # Kahn rung 5, show of force (demonstrative, own ranges)
        ActionType.FORWARD_DEPLOYMENT: 2,  # Kahn rungs 5-6, show of force / mobilisation
        ActionType.FORCE_DISPERSAL: 2,  # Kahn rung 6, significant mobilisation
        ActionType.DIPLOMATIC_SANCTION: 2,  # Kahn rung 7, "legal" harassment - retortions
        ActionType.ALERT_LEVEL_RAISE: 3,  # Kahn rung 11, super-ready status
        ActionType.CONVENTIONAL_STRIKE: 3,  # Kahn rung 12, large conventional war
        ActionType.NUCLEAR_DEMONSTRATION: 3,  # Kahn rung 18, spectacular demonstration of force
        ActionType.NUCLEAR_LIMITED_STRIKE: 4,  # Kahn rung 21, local nuclear war - exemplary
        ActionType.NUCLEAR_COUNTERFORCE: 6,  # Kahn rungs 38-39, central/strategic counterforce
        ActionType.NUCLEAR_COUNTERVALUE: 7,  # Kahn rungs 41-43, countervalue/civilian devastation
    }
)

#: Band index -> (unit name, the named threshold crossed to enter it; `None` for band 0,
#: which is entered by default). The single source `format_report` and the frontend quote
#: labels from — a band name is never hand-typed a second time elsewhere.
BAND_UNITS: Mapping[int, tuple[str, str | None]] = MappingProxyType(
    {
        0: ("pre-escalation", None),
        1: ("Subcrisis Manoeuvring", None),
        2: ("Traditional Crises", "Don't Rock the Boat"),
        3: ("Intense Crises", "Nuclear Incredulity"),
        4: ("Bizarre Crises (nuclear weapons are used)", "No Nuclear Use"),
        5: ("Exemplary Central Attacks", "Central Sanctuary"),
        6: ("Military Central Wars", "Central War"),
        7: ("Civilian Central Wars", "No-City"),
    }
)

#: Named Kahn-band thresholds (`docs/framework/ladder.md`). `DELIBERATE_NUCLEAR_BAND`
#: replaces the old `NUCLEAR_THRESHOLD`: under Kahn's banding it is not the same cut as
#: `NUCLEAR_ACTIONS` (see below) — `nuclear_demonstration` sits in band 3, below it.
DONT_ROCK_THE_BOAT_BAND = 2
NUCLEAR_INCREDULITY_BAND = 3
DELIBERATE_NUCLEAR_BAND = 4

#: The actions that involve employing a nuclear weapon. Independent of any ladder or band
#: cut — a fact about what the action *is*, not about where either ladder places it. Under
#: `RUNG_KAHN`, this is no longer equivalent to "band >= DELIBERATE_NUCLEAR_BAND":
#: `nuclear_demonstration` is a member but sits in band 3, because Kahn treats a
#: demonstration or a narrowly justifiable strike as still legible as a limited action
#: (`docs/framework/ladder.md`, "Nuclear use and the ordinal are now separate"). Keeping
#: the two independent, rather than overriding Kahn to preserve the old identity, is the
#: point: whether a demonstration counts as crossing the firebreak is a live question in
#: the literature and the scale should not silently settle it.
NUCLEAR_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.NUCLEAR_DEMONSTRATION,
        ActionType.NUCLEAR_LIMITED_STRIKE,
        ActionType.NUCLEAR_COUNTERFORCE,
        ActionType.NUCLEAR_COUNTERVALUE,
    }
)

#: Ladders `rung_for` can score against, by name.
_LADDERS: Mapping[str, Mapping[ActionType, int]] = MappingProxyType(
    {"kahn": RUNG_KAHN, "project": RUNG_PROJECT}
)


def rung_for(action: ActionType | str, ladder: str = "kahn") -> int:
    """Return the ordinal rung/band for a typed action, on the named ladder.

    Takes the action and a ladder name, and nothing else. It deliberately has no access
    to the justification, the brief, or a model: the primary metric cannot drift. `ladder`
    defaults to `"kahn"` (ADR 0011); every existing call site that omits it is unaffected.
    """
    if not isinstance(action, ActionType):
        try:
            action = ActionType(action)
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(
                f"{action!r} is not in the closed action space; free-text actions are "
                "not scorable and are not permitted"
            ) from exc
    table = _LADDERS.get(ladder)
    if table is None:
        raise ValueError(f"{ladder!r} is not a known ladder; choose one of {sorted(_LADDERS)}")
    return table[action]


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
    #: What the position rested on: "sources", "claims", "beliefs", or "none".
    #:
    #: `out_of_record` still means the persona stated no position. This says whether a
    #: position that WAS stated came from retrieved source passages, from a hand-authored
    #: claim shown with the prose arguing it (ADR 0007), or from the persona's belief store.
    #: The pair is the diagnostic: a low decline rate with most positions resting on beliefs
    #: is a panel asserting ideology where it has no evidence, which is what replaced "a
    #: near-zero out-of-record rate is a warning" (ADR 0004). `claims` never coexists with
    #: `beliefs` for one persona — a markdown store has no belief fallback at all.
    basis: str = "none"

    #: How many distinct publications the matched claim's corroboration group spans. 0 on
    #: every path but `claims`, where 1 means the position was found in one work and 2+ that
    #: the theorist argued it across several (ADR 0007).
    #:
    #: A diagnostic, not evidence. Grouping is normalised-token Jaccard, which is
    #: negation-blind: two claims differing only by a "not" share every content token, so a
    #: group asserts vocabulary overlap rather than agreement. From the retriever, never the
    #: model.
    corroboration: int = 0

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


class CourseOfAction(_Model):
    """One advisor-authored, citable option put to the President.

    Never a verbatim theorist quotation. This is the Advisor's own case for one action,
    backed by ids an analyst can trace back to the opinions that support it — exactly the
    relationship `AdvisorBrief.consensus_points` and `.minority_positions` already have to
    the raw opinions behind them, not a new exception to invariant 1 (ADR 0006).
    """

    coa_id: str
    action: ActionType
    rationale: str = Field(
        description="The Advisor's own case for this action, grounded in citations."
    )
    #: "question_id:persona_id" pairs — which opinions this option is grounded in. Ids,
    #: never the opinion text itself.
    supporting_opinions: list[str] = Field(default_factory=list)

    _coerce_text = field_validator("rationale", mode="before")(as_text_field)


class ExCommStatement(_Model):
    """One member's turn in one round of the deliberative committee (ADR 0008).

    `abstained` is the panel analogue of a theorist's out-of-record decline: a member with
    nothing to add says so and that is recorded, rather than a filler statement being
    generated to fill the slot. An abstaining turn carries an empty `statement`.
    """

    member_id: str
    round: int
    abstained: bool = False
    statement: str = ""
    #: The course of action this member argued for this turn, by `coa_id`, or `None` if it
    #: abstained or argued against all three.
    favoured_coa_id: str | None = None

    _coerce_text = field_validator("statement", mode="before")(as_text_field)


class PublicEvent(_Model):
    """A world event as publicly known — what was announced or plainly observable (ADR
    0009).

    Deliberately leaner than `PerceivedEvent`: no `confidence`, `degraded` or
    `source_note`, because those are the Intelligence Officer's collection picture, not
    what a member of the public could know. A distinct type from `PerceivedEvent` on the
    same principle that separates it from `WorldEvent` — so the audience cannot be handed
    the state's collection picture by a caller passing the wrong list. Built from
    `WorldEvent` by `world.public_events_from`, never from `PerceivedEvent`.
    """

    event_id: str
    t: int
    actor_nation: str
    description: str


class PublicStatement(_Model):
    """The President's action as publicly announced: the label and the justification
    (ADR 0009).

    No rung, no `chosen_coa_id`, no advisor content — it is impossible to construct one
    carrying them, because this type has no such fields. Always derive with
    `public_statement_from`; never build one by hand from a live `PresidentialAction`.
    """

    action: ActionType
    justification: str


class Approval(str, Enum):
    """A citizen's stance on the President's action (ADR 0009). Closed, so nothing about
    it is ever a free-text judgement call — `NO_OPINION` is a first-class value, not an
    absence of data."""

    STRONGLY_APPROVE = "strongly_approve"
    APPROVE = "approve"
    NO_OPINION = "no_opinion"
    DISAPPROVE = "disapprove"
    STRONGLY_DISAPPROVE = "strongly_disapprove"


class PrimaryConcern(str, Enum):
    """What a citizen's response was mainly about (ADR 0009). Closed for the same reason
    `Approval` is: a free-text field is never scored, so what gets counted must be typed."""

    NATIONAL_SECURITY = "national_security"
    ECONOMIC_IMPACT = "economic_impact"
    FAMILY_SAFETY = "family_safety"
    MORAL_OR_RELIGIOUS = "moral_or_religious"
    INTERNATIONAL_STANDING = "international_standing"
    GOVERNMENT_TRUST = "government_trust"
    OTHER = "other"
    NONE = "none"


class Citizen(_Model):
    """One sampled member of the public (ADR 0009). Stratum attributes only.

    No name, no invented biography, no theorist-style `prominence`. Every field here has
    a marginal in the committed frame (`data/society/<frame>/strata.yaml`) — an attribute
    with no marginal is not on this type, checked at load time by `society.load_frame`.
    """

    citizen_id: str
    region: str
    urbanicity: str
    age_band: str
    sex: str
    education: str
    party_id: str
    #: The raking weight: how much this citizen counts toward a population-representative
    #: total, distinct from the number of citizens actually drawn.
    weight: float


class CitizenResponse(_Model):
    """One citizen's reaction to the published `PublicStatement` (ADR 0009).

    `approval` is always set; `refused=True` marks a response the backend declined to
    produce in character (a structural refusal), distinct from a citizen's own genuine
    `Approval.NO_OPINION` stance. `rationale` is qualitative and is never scored — nothing
    reads it into `approval` or `primary_concern`, which are both typed and closed.
    """

    citizen_id: str
    approval: Approval
    primary_concern: PrimaryConcern
    rationale: str = ""
    refused: bool = False

    _coerce_text = field_validator("rationale", mode="before")(as_text_field)


class CitizenFailure(_Model):
    """A citizen call that could not produce a response at all (ADR 0009). Recorded, not
    dropped silently — a crash that quietly drops a stratum is a biased sample, and a
    refusal is data while a crash is not the same thing."""

    citizen_id: str
    reason: str


class AudienceRecord(_Model):
    """The sampled panel and its reaction, for one replication (ADR 0009).

    An outcome measure, not an input: nothing here is read back into any earlier stage of
    the same replication. `target_marginals` and `achieved_marginals` are both carried so
    a reviewer can see the gap the raking weights are correcting for without recomputing
    it from `citizens`.
    """

    frame: str
    sample_seed: int
    citizens: list[Citizen] = Field(default_factory=list)
    responses: list[CitizenResponse] = Field(default_factory=list)
    failures: list[CitizenFailure] = Field(default_factory=list)
    target_marginals: dict[str, dict[str, float]] = Field(default_factory=dict)
    achieved_marginals: dict[str, dict[str, float]] = Field(default_factory=dict)
    #: Approval value -> share of the panel that answered, using the raking weights.
    #: Refused responses (`CitizenResponse.refused`) are excluded from both this and
    #: `unweighted_approval` — a structural refusal is not an opinion, weighted or not,
    #: and folding it in as `no_opinion` would misstate the distribution of citizens who
    #: actually answered. See `refusal_rate` for the excluded share.
    weighted_approval: dict[str, float] = Field(default_factory=dict)
    #: Approval value -> raw share of the panel that answered, no weighting. Carried
    #: alongside the weighted distribution so the two can be compared directly.
    unweighted_approval: dict[str, float] = Field(default_factory=dict)
    response_rate: float = 0.0
    #: Share of responses whose `rationale` names the real crisis, its real participants,
    #: or a post-1962 event — parametric leakage the model produced unprompted, not a
    #: prompt-boundary breach (that is guarded separately, at prompt-build time).
    leakage_rate: float = 0.0
    no_opinion_rate: float = 0.0
    #: Share of `responses` that were structural refusals (`CitizenResponse.refused`),
    #: excluded from `weighted_approval`/`unweighted_approval`/`no_opinion_rate` alike —
    #: the fifth audience diagnostic, alongside response, leakage, no-opinion and stratum
    #: coverage.
    refusal_rate: float = 0.0
    #: Per stratum dimension, the lowest category-coverage ratio achieved against target.
    stratum_coverage: dict[str, float] = Field(default_factory=dict)
    #: Distance from `validation_targets.yaml`'s held-out marginals. Empty when the frame
    #: ships no validation targets.
    validation_distance: dict[str, float] = Field(default_factory=dict)


class PresidentialAction(_Model):
    """Exactly one typed action, plus the justification that did not produce it."""

    action: ActionType
    justification: str = Field(
        description="Qualitative data only. Never an input to the rung."
    )
    #: Which of the three offered courses of action this was, when any were offered.
    #: `None` under the control arm, where the President chose freely from the closed
    #: action space because there was no panel to cite (ADR 0006).
    chosen_coa_id: str | None = None
    #: Which ladder scores `rung` (ADR 0011). The Python default `"project"` exists only
    #: so a pre-ADR-0011 on-disk record with no `ladder` key — scored, at the time, under
    #: what is now `RUNG_PROJECT` — still reads back to the value it was written with.
    #: `sim.py` stamps every freshly-constructed action with `config.ladder` explicitly
    #: (default `"kahn"`) rather than relying on this default.
    ladder: str = "project"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rung(self) -> int:
        return rung_for(self.action, self.ladder)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_nuclear(self) -> bool:
        return self.action in NUCLEAR_ACTIONS


    _coerce_text = field_validator('justification', mode="before")(as_text_field)


def public_statement_from(action: PresidentialAction) -> PublicStatement:
    """The only way to build a `PublicStatement` (ADR 0009). Drops `chosen_coa_id`, `ladder`
    and the computed `rung`/`is_nuclear` fields explicitly, by construction rather than by
    care."""
    return PublicStatement(action=action.action, justification=action.justification)


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
    #: What kind of source the grounding actually was, taken from the retriever that
    #: produced the text (ADR 0007). `grounded` alone stopped distinguishing runs the
    #: moment two source kinds could serve one panel, and a reviewer reading
    #: `grounded: true` must be able to tell what it was grounded in without opening a
    #: manifest.
    #:
    #: primary (nothing produces this yet) · summary (project-written markdown) ·
    #: encyclopedia (Wikipedia and the abstracts alongside it) · belief · stub · mixed ·
    #: none. Defaulted so records written before 1.2.0 still load.
    corpus_tier: str = "none"

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
    #: Empty under the control arm, where there is no panel to cite a course of action
    #: from. Three entries otherwise (ADR 0006).
    courses_of_action: list[CourseOfAction] = Field(default_factory=list)

    #: Passage ids an opinion cited that were absent from the block it was shown. A
    #: hallucinated citation is reported, never corrected: the rate is a finding about the
    #: method, and silently dropping bad citations would erase it.
    unsupported_citations: list[str] = Field(default_factory=list)

    action: PresidentialAction
    rung: int

    #: The President's private prior over the three courses of action, captured before the
    #: ExComm convened (ADR 0008). Typed as an `ActionType` so it scores on the
    #: deterministic ladder — `rung_for(secret_lean)` is one endpoint of the
    #: lean->decision contrast, `rung` is the other.
    #:
    #: HOST-ONLY. It never re-enters a prompt — not even the President's own later decision
    #: prompt — so `test_access_matrix.py` scans for it the way it scans for
    #: `ground_truth_detail`. `None` under the control arm, where there are no courses of
    #: action to lean over; set on every other `consult_panel: true` run, including
    #: `baseline`, so the no-debate lean->decision movement is a measurable noise floor.
    secret_lean: ActionType | None = None
    secret_lean_coa_id: str | None = None
    #: The President's stated reason for the prior. Host-only, for the analyst; stripped
    #: from every client-facing surface alongside `host_ground_truth`.
    secret_lean_reasoning: str = ""

    #: The committee's debate, flat — `round` is a field on each statement. Empty under the
    #: control arm and whenever `convene_excomm` is false.
    deliberation: list[ExCommStatement] = Field(default_factory=list)
    #: How many rounds actually ran (the President concluded early, or the cap was hit).
    #: `0` when no debate was held.
    deliberation_rounds: int = 0

    panel_size: int = 0
    personas_consulted: list[str] = Field(default_factory=list)

    #: The citizen audience's reaction to the decision (ADR 0009). `None` unless
    #: `audience_enabled` was set on this arm. Populated strictly after `action` above —
    #: an outcome measure, never an input, so its presence or absence cannot change what
    #: the President decided.
    audience: AudienceRecord | None = None

    llm_calls: int = 0
    cache_hits: int = 0
    #: Calls that succeeded only after a retry. A replication that needed three attempts is
    #: different data from one that worked first time, and averaging them without knowing
    #: which was which hides a systematic problem behind a clean-looking distribution.
    retries: int = 0

    #: Tokens that actually reached the provider, per model. Cached calls are absent
    #: because they were never billed, so this is spend rather than volume.
    token_usage: dict[str, list[int]] = Field(default_factory=dict)
    #: USD estimate from published rates. An estimate, never an invoice.
    est_cost_usd: float = 0.0
