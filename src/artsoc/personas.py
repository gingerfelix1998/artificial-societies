"""Persona construction (M1/M2/M3), the tag vocabulary contract, and routing.

This module builds the population being modelled and decides which members of it are put
to any given question. Three things here are load-bearing.

**Tags are validated at load, not at route time.** An off-vocabulary tag matches no
question, so a persona carrying one is reachable only by routing top-up and quietly
contributes less than the registry implies. That is a silent failure, so `load_registry`
raises on it instead.

**Routing keeps `matched_by_tag` and `topped_up` apart.** A panel that is nominally large
but really answers from six personas is the central threat to the "100 personas" claim.
Keeping the two selection reasons in separate fields means a nominal panel is visible in
the output record rather than something an analyst has to infer.

**This module makes no model call and does not import `artsoc.llm`.** Persona construction
produces prompt *text*; only `agents.py` sends it anywhere. Keeping that separation means
the access-matrix tests can inspect what a persona would say about itself without a
backend, and means a persona cannot acquire context through a call it makes on its own.

M3 personas carry no real theorist name on purpose. If a panel's effect can be reproduced
by position-defined personas with invented names, the effect was the positions; if it
cannot, some of it was the celebrity of the names. That contrast is the `synth_only` arm
and it only works if M3 is genuinely anonymous.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from artsoc.schema import TAG_SET, AnalyticalQuestion, RoutingRecord

#: Repo root, resolved the same way `world.py` does it.
REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "data" / "theorists" / "registry.yaml"

#: The persona construction methods.
#:
#: M1  name only — the cheap baseline. No record, so nothing anchors the answer and there
#:     is nothing for the escape hatch to be measured against.
#: M2  name plus retrieved record, with the out-of-record escape hatch. The default.
#: M3  position-defined, anonymous. Controls for celebrity effects.
METHODS: frozenset[str] = frozenset({"m1", "m2", "m3"})

#: Prefix for synthetic persona ids, so an M3 persona can never be confused with a real
#: theorist in an output record.
SYNTH_PREFIX = "synth_"

#: Where a persona's store is built from. Closed, and checked at load: a typo here would
#: otherwise route a persona down whichever branch the dispatch happens to end on.
CORPUS_SOURCES: frozenset[str] = frozenset({"markdown", "wikipedia"})


class Persona(BaseModel):
    """One member of the modelled population.

    `corpus_notes` and `prominence` are placeholders — see the header of
    `data/theorists/registry.yaml`. Neither is evidence and `prominence` is not used to
    weight anything today.
    """

    model_config = ConfigDict(extra="forbid")

    persona_id: str
    name: str
    era: str = "unspecified"
    #: Which pipeline builds this persona's store: `wikipedia` fetches and chunks the page
    #: below, `markdown` reads committed documents from `data/corpora-src/<persona_id>/`.
    #:
    #: Declared, never inferred. Deciding it from whether a source directory happens to
    #: exist is a silent fallback under another name — a persona whose documents were not
    #: added yet would be built from an encyclopedia article and still reported as
    #: grounded. The default exists so personas constructed in code need not restate it;
    #: a test requires every registry entry to declare it explicitly.
    corpus_source: str = "wikipedia"
    #: Wikipedia page title for `artsoc ingest`. None means this persona has no corpus and
    #: will decline every question — correct behaviour, not a failure to work around.
    wikipedia: str | None = None
    #: VERIFIED Semantic Scholar author id, or None. Verified against the author's actual
    #: top papers: a name search alone resolved "Bernard Brodie" to a pharmacologist. A
    #: wrong id fills a persona's store with another person's work, so None is preferred.
    semantic_scholar: str | None = None
    #: Titles whose abstracts are looked up directly, which sidesteps author
    #: disambiguation. Patchy by nature — most of this literature predates abstracts.
    key_works: list[str] = Field(default_factory=list)
    prominence: float = Field(
        default=0.5,
        description="INVENTED placeholder, not a citation count. Not used for weighting.",
    )
    tags: list[str] = Field(default_factory=list)
    corpus_notes: str = Field(
        default="",
        description="PLACEHOLDER paraphrase written so the loop runs. Never evidence.",
    )

    @field_validator("corpus_source")
    @classmethod
    def _corpus_source_must_be_known(cls, value: str) -> str:
        if value not in CORPUS_SOURCES:
            raise ValueError(
                f"unknown corpus_source {value!r}; expected one of {sorted(CORPUS_SOURCES)}. "
                "The source of record is declared here and never inferred from what happens "
                "to be on disk"
            )
        return value

    @field_validator("tags")
    @classmethod
    def _tags_must_be_in_vocab(cls, tags: list[str]) -> list[str]:
        # Rejected here rather than at route time. An off-vocabulary tag is not an error
        # that surfaces later — it is a persona that quietly stops being reachable.
        normalised = [t.strip().lower() for t in tags]
        unknown = sorted(set(normalised) - TAG_SET)
        if unknown:
            raise ValueError(
                f"tags {unknown} are not in schema.TAG_VOCAB; an off-vocabulary tag "
                "matches no question and leaves the persona reachable only by top-up"
            )
        return normalised

    @property
    def is_synthetic(self) -> bool:
        return self.persona_id.startswith(SYNTH_PREFIX)


class Registry(BaseModel):
    """The persona registry as loaded from disk."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    personas: list[Persona]

    @field_validator("personas")
    @classmethod
    def _ids_are_unique(cls, personas: list[Persona]) -> list[Persona]:
        seen: set[str] = set()
        for persona in personas:
            if persona.persona_id in seen:
                raise ValueError(
                    f"duplicate persona_id {persona.persona_id!r}; ids key the routing "
                    "record and the response cache, so they must be unique"
                )
            seen.add(persona.persona_id)
        return personas


def load_registry(path: Path | None = None) -> list[Persona]:
    """Load and validate the persona registry."""
    target = path or REGISTRY_PATH
    if not target.exists():
        raise FileNotFoundError(f"no persona registry at {target}")
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    return Registry.model_validate(data).personas


# ---------------------------------------------------------------------------
# Construction. Each method returns the persona's system prompt text.
#
# None of these take the scenario, the intel brief, or peer opinions. There is no
# parameter through which they could: a theorist is defined by who it is and what its own
# record says, and it answers a decontextualised question. That is invariant 1, and it is
# what makes the answers cacheable across replications.
# ---------------------------------------------------------------------------

_SHARED_INSTRUCTION = (
    "Answer only the analytical question put to you. You do not know what situation "
    "prompted it, you are not advising on one, and you must not speculate about it. "
    "State the position you would take and the reasoning behind it. Argue from "
    "theoretical principle: do not name a specific real country, war, or dated "
    "contemporary event as your evidence, even if your own record discusses one — state "
    "the underlying mechanism instead of the case that illustrates it."
)

_OUT_OF_RECORD_INSTRUCTION = (
    "If the question falls outside what your record actually addresses, say so and set "
    "out_of_record. Declining is a correct answer. Do not construct a position you did "
    "not hold in order to fill the slot."
)


#: Emitted into the *user* prompt when retrieval returned nothing. Kept identical to
#: `llm.NO_RECORD_MARKER` but not imported from there: this module must not depend on the
#: backend module (see the header, and `test_persona_construction_makes_no_model_call`).
#: A test asserts the two constants agree, so they cannot drift apart silently.
NO_RECORD_MARKER = "[[CORPUS:none]]"


def _check_method(method: str) -> None:
    if method not in METHODS:
        raise ValueError(f"unknown persona method {method!r}; expected one of {sorted(METHODS)}")


def build_identity_prompt(persona: Persona, method: str) -> str:
    """The system prompt for one persona: who it is and how it must answer.

    Carries no record and no question, so it is stable across every question this persona
    is ever asked. See ADR 0001 for why the record lives in the user prompt instead.
    """
    _check_method(method)

    if method == "m1":
        # No record at all. The escape hatch is deliberately not offered: with nothing to
        # be out of, "out of record" would have no meaning, and M1 exists precisely to
        # show what a name alone produces.
        return f"You are {persona.name}, a nuclear-strategy theorist.\n\n{_SHARED_INSTRUCTION}"

    if method == "m3":
        # No name. The position is the whole persona.
        return (
            "You are an anonymous nuclear-strategy theorist whose published position is "
            f"characterised as follows:\n\n{persona.corpus_notes}\n\n"
            f"Do not claim to be any named individual.\n\n{_SHARED_INSTRUCTION}\n"
            f"{_OUT_OF_RECORD_INSTRUCTION}"
        )

    return (
        f"You are {persona.name}, a nuclear-strategy theorist. Answer from your own "
        "written record, which is supplied with each question, and cite the passage ids "
        f"you rely on.\n\n{_SHARED_INSTRUCTION}\n{_OUT_OF_RECORD_INSTRUCTION}"
    )


#: How a belief block is framed. Distinct from the source framing on purpose.
#:
#: A persona shown its own stated positions and told to "answer from your written record
#: and cite the passage ids" declines, because a position is not a record and has no
#: source to cite. That is what happened: retrieval supplied beliefs to three of
#: twenty-four theorists and every one of them still declined. Beliefs are reasoned from
#: directly; they need no source behind them, which is the whole point of the fallback
#: (ADR 0004).
_BELIEF_FRAMING = (
    "The corpus does not cover this question, but these are positions you argued for. "
    "Reason from them directly: they are your own views and need no source to support "
    "them. Cite their ids as the basis of your answer. Decline only if the question is "
    "genuinely unrelated to the positions below."
)

#: How a claim block is framed. Distinct from both of the above, because it is neither.
#:
#: A belief was a position with nothing behind it; a source passage was prose with no
#: position attached. A claim is a stated position shown together with the prose that
#: argues it, so the instruction has to say that both are citable — otherwise a persona
#: cites only the evidence, and the position it actually answered from goes unrecorded
#: (ADR 0007).
_CLAIM_FRAMING = (
    "Each position below is one you argued, followed by the passages from that work which "
    "argue it. Answer from these. Cite the position's id, the ids of the passages beneath "
    "it, or both. Where the same position appears more than once, it is one you argued in "
    "more than one work. Decline if the positions below do not address the question."
)


def build_question_prompt(
    question: AnalyticalQuestion,
    record_block: str = "",
    method: str = "m2",
    basis: str = "sources",
) -> str:
    """The user prompt: one decontextualised question, plus this persona's own record.

    `record_block` is retrieved text supplied by the caller. This function retrieves
    nothing itself, so a persona cannot reach a corpus that routing did not give it, and
    cannot reach another persona's corpus at all.

    The record goes here rather than in the identity prompt because that is where a
    backend reads its structured markers — without it the out-of-record hatch never fires
    and no citation is ever offered. ADR 0001.
    """
    _check_method(method)

    if method == "m1":
        # M1 has no record by construction, so it gets no RECORD section and no marker.
        return f"QUESTION:\n{question.text}"

    block = record_block.strip() or NO_RECORD_MARKER
    if basis == "beliefs" and record_block.strip():
        return (
            f"QUESTION:\n{question.text}\n\n"
            f"YOUR STATED POSITIONS:\n{block}\n\n{_BELIEF_FRAMING}"
        )
    if basis == "claims" and record_block.strip():
        return (
            f"QUESTION:\n{question.text}\n\n"
            f"POSITIONS FROM YOUR RECORD, WITH THE PASSAGES THAT ARGUE THEM:\n{block}"
            f"\n\n{_CLAIM_FRAMING}"
        )
    return f"QUESTION:\n{question.text}\n\nRECORD:\n{block}"


def synthetic_panel(n: int, seed: int = 0) -> list[Persona]:
    """Build `n` position-defined personas carrying no real theorist name.

    The `synth_only` arm's control. Positions are drawn from the tag vocabulary so the
    synthetic panel spans the same analytical space as the real one and remains routable.
    """
    rng = random.Random(seed)
    vocab = sorted(TAG_SET)
    personas: list[Persona] = []
    for i in range(n):
        tags = rng.sample(vocab, min(3, len(vocab)))
        personas.append(
            Persona(
                persona_id=f"{SYNTH_PREFIX}{i:03d}",
                name=f"Anonymous theorist {i:03d}",
                era="synthetic",
                prominence=0.5,
                tags=tags,
                corpus_notes=(
                    "SYNTHETIC persona, not a real theorist. Position emphasises: "
                    + ", ".join(tags)
                    + "."
                ),
            )
        )
    return personas


# ---------------------------------------------------------------------------
# Routing.
# ---------------------------------------------------------------------------


def route(
    question: AnalyticalQuestion,
    personas: list[Persona],
    k: int,
    rng: random.Random,
) -> RoutingRecord:
    """Select `k` personas for one question, recording why each was chosen.

    Tag matches come first, ordered by how many of the question's in-vocab tags they hit,
    with ties broken by the injected rng rather than by registry order — otherwise the
    same few personas lead every panel and apparent consensus is an artifact of file
    ordering.

    Any shortfall is filled from the remaining personas and recorded as `topped_up`. The
    two are kept apart because a question that reaches `k` personas entirely by top-up
    consulted nobody who claims relevant expertise, and that must be visible.

    `rng` is injected rather than global so a run stays reproducible from config plus seed,
    matching how `world.PerceptionFilter.view` threads its own rng.
    """
    if k < 0:
        raise ValueError("k must be non-negative")

    wanted = set(question.in_vocab_tags)

    matched: list[Persona] = []
    unmatched: list[Persona] = []
    for persona in personas:
        (matched if wanted & set(persona.tags) else unmatched).append(persona)

    # Shuffle first, then sort by overlap. Python's sort is stable, so the shuffle decides
    # ties within an overlap count and nothing else.
    rng.shuffle(matched)
    rng.shuffle(unmatched)
    matched.sort(key=lambda p: len(wanted & set(p.tags)), reverse=True)

    selected_matched = matched[:k]
    shortfall = k - len(selected_matched)
    topped_up = (matched[k:] + unmatched)[:shortfall] if shortfall > 0 else []

    return RoutingRecord(
        question_id=question.question_id,
        k_requested=k,
        matched_by_tag=[p.persona_id for p in selected_matched],
        topped_up=[p.persona_id for p in topped_up],
    )


def panel_coverage(routing: list[RoutingRecord]) -> set[str]:
    """The distinct personas actually consulted across a set of routing records.

    This gates the panel-size claim. If coverage is far below the declared panel size, the
    panel is nominal and the claim must be restated — see `CLAUDE.md`. Returning the set
    rather than a count keeps the diagnostic usable for finding *which* personas never
    speak, which is the more interesting question.
    """
    consulted: set[str] = set()
    for record in routing:
        consulted.update(record.selected)
    return consulted


# ---------------------------------------------------------------------------
# The ExComm deliberative panel (ADR 0008).
#
# A separate population from the theorists, sharing nothing with them but this module.
# A theorist is defined by a published record and answers one decontextualised question in
# isolation; an ExComm member is defined by a disposition and a standing belief system, is
# shown the (anonymised) crisis, and argues it in a peer-visible debate.
#
# Members are 1962-SHAPED, not the historical individuals: a prompt carries an institutional
# role title and an anonymised disposition, never a real name. That is the same anti-leakage
# choice the scenario makes with 'Nation A / Nation B' — a roster of real names would let a
# model retrieve how the real episode ended just as effectively as a real dyad would.
# `docs/excomm/roster-key.md` maps `member_id` -> real person for the humans maintaining the
# profiles; nothing in the code path reads it.
# ---------------------------------------------------------------------------

EXCOMM_REGISTRY_PATH = REPO_ROOT / "data" / "excomm" / "registry.yaml"

_MEMBER_ID = re.compile(r"^[a-z0-9_]+$")


class ExCommMember(BaseModel):
    """One seat on the President's deliberative committee.

    `disposition` and `beliefs` are hand-authored, anonymised, and 1962-shaped. They are
    the member's own temperament and prior positions — not evidence in the sense a
    theorist's cited record is, and no grounding claim rests on them.
    """

    model_config = ConfigDict(extra="forbid")

    #: Slug, e.g. `defense_secretary`. Lowercase, underscore-separated, never a real name.
    member_id: str
    #: The institutional position, in prose. Never a real name.
    role_title: str
    #: A nuanced behavioural profile: temperament, ideology, decision style, how the member
    #: moves under pressure. Anonymised — no real name, no dated episode.
    disposition: str
    #: Standing positions the member argues from, drawn from that figure's writing and
    #: memoranda, phrased as general principle rather than dated statement.
    beliefs: list[str]
    #: One line naming what the beliefs are drawn from. Carried into the identity prompt so
    #: the grounding is inspectable; not itself a citable source.
    backing_literature: str = ""

    @field_validator("member_id")
    @classmethod
    def _id_is_a_slug(cls, value: str) -> str:
        if not _MEMBER_ID.match(value):
            raise ValueError(
                f"member_id {value!r} must match [a-z0-9_]+; it keys the deliberation "
                "record and must not carry a real name"
            )
        return value

    @field_validator("beliefs")
    @classmethod
    def _beliefs_are_present(cls, value: list[str]) -> list[str]:
        cleaned = [b.strip() for b in value if b and b.strip()]
        if not cleaned:
            raise ValueError(
                "an ExComm member with no standing positions has no voice in the debate; "
                "give it at least one belief"
            )
        return cleaned


class ExCommRoster(BaseModel):
    """The committee as loaded from disk."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    members: list[ExCommMember]

    @field_validator("members")
    @classmethod
    def _ids_are_unique(cls, members: list[ExCommMember]) -> list[ExCommMember]:
        seen: set[str] = set()
        for member in members:
            if member.member_id in seen:
                raise ValueError(
                    f"duplicate member_id {member.member_id!r}; ids key the deliberation "
                    "record, so they must be unique"
                )
            seen.add(member.member_id)
        return members


def load_excomm(path: Path | None = None) -> list[ExCommMember]:
    """Load and validate the ExComm roster."""
    target = path or EXCOMM_REGISTRY_PATH
    if not target.exists():
        raise FileNotFoundError(f"no ExComm roster at {target}")
    data = yaml.safe_load(target.read_text(encoding="utf-8"))
    return ExCommRoster.model_validate(data).members


_EXCOMM_INSTRUCTION = (
    "Reason about the situation exactly as it is presented to you. Do not identify it with "
    "any named historical episode, and do not claim to know how a comparable case turned "
    "out. You do not choose the course of action — the President does; your job is to "
    "sharpen the choice by arguing your view and engaging with what other members have "
    "said. If the discussion has not moved since your last turn, or another member has "
    "already made your point, say so and abstain: abstaining is a valid contribution, not "
    "a failure to participate. Do not claim to be any named individual — you are this "
    "committee role."
)


def build_excomm_identity_prompt(member: ExCommMember) -> str:
    """The system prompt for one ExComm member: its role, temperament and prior positions.

    Carries no situation and no round, so it is stable across the whole debate. The
    situation, the brief, the courses of action and the running transcript live in the
    user prompt, built by `agents.py`.
    """
    positions = "\n".join(f"- {b}" for b in member.beliefs)
    provenance = (
        f"\n\nThese positions are drawn from {member.backing_literature}."
        if member.backing_literature.strip()
        else ""
    )
    return (
        "You are a senior member of the committee the President has convened to deliberate "
        f"a live crisis. Your seat is: {member.role_title}.\n\n"
        f"HOW YOU THINK:\n{member.disposition}\n\n"
        f"YOUR STANDING POSITIONS:\n{positions}{provenance}\n\n"
        f"{_EXCOMM_INSTRUCTION}"
    )
