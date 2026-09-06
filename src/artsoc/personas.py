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
    prominence: float = Field(
        default=0.5,
        description="INVENTED placeholder, not a citation count. Not used for weighting.",
    )
    tags: list[str] = Field(default_factory=list)
    corpus_notes: str = Field(
        default="",
        description="PLACEHOLDER paraphrase written so the loop runs. Never evidence.",
    )

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
    "State the position you would take and the reasoning behind it."
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


def build_question_prompt(
    question: AnalyticalQuestion, record_block: str = "", method: str = "m2"
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
