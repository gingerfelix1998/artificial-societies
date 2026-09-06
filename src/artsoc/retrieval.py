"""The M2 grounding interface, and the boundary between grounded and ungrounded runs.

Invariant 4 is the reason this module exists as a module rather than as a function inside
`agents.py`: **a real retriever must raise rather than degrade to `StubRetriever`.** A
silent fallback is the one failure that would let an ungrounded run be written up as
corpus-grounded, and no test downstream could detect it after the fact — the output record
would look identical to a real one.

So `grounded` is a property of the retriever, not a flag the caller sets. Whatever ends up
in `RunRecord.grounded` comes from the object that actually produced the text, and the only
way to get `True` is to construct a `CorpusRetriever`, which currently cannot be
constructed at all.

**One store per persona.** `retrieve` is handed a single `Persona` and has no access to the
registry, so persona A structurally cannot retrieve persona B's text and cite it as its
own. That is a property of the signature, not of the implementation being careful.

**Passage ids are content-addressed, not positional.** `TheoristOpinion.citations` are
verified against the block the persona was shown, so an id that shifts when an index is
rebuilt makes every past record unverifiable. The stub's ids are trivially stable because
there is one passage per persona; the real retriever must derive ids from content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from artsoc.llm import PASSAGE_ID
from artsoc.personas import Persona

#: Repo root, resolved the same way `world.py` and `personas.py` do it.
REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_ROOT = REPO_ROOT / "data" / "corpora"


@runtime_checkable
class Retriever(Protocol):
    """What the theorist step needs from a source of record.

    `grounded` travels with the retriever precisely so that it cannot be asserted by a
    caller that did not do the retrieving.
    """

    mode: str
    grounded: bool

    def retrieve(self, persona: Persona, question_text: str) -> str: ...


def format_passage(persona_id: str, source: str, index: int, text: str) -> str:
    """Render one passage with a citable id.

    The id format is what `llm.PASSAGE_ID` matches; a passage rendered any other way is
    invisible to the backend and can never be cited, so both ends use this one function.
    """
    return f"[{persona_id}:{source}:{index}] {text}"


class StubRetriever:
    """A one-line paraphrase from the registry. Never grounded, and says so.

    This exists so the loop runs end to end without a corpus. The text it returns is a
    `corpus_notes` placeholder — not a quotation, not evidence, and not something any claim
    of grounding may rest on. `grounded` is `False` and there is no constructor argument
    that can change it.
    """

    mode = "stub"
    grounded = False

    def retrieve(self, persona: Persona, question_text: str) -> str:
        # question_text is accepted and deliberately unused: the stub does no relevance
        # selection at all. A stub that appeared to select would invite the reader to
        # interpret which passages came back, and there is nothing there to interpret.
        if not persona.corpus_notes.strip():
            # No note for this persona, so nothing was "retrieved". Returning empty is the
            # mechanism that makes out_of_record fire, which is the honest outcome here.
            return ""
        return format_passage(persona.persona_id, "notes", 0, persona.corpus_notes.strip())


class CorpusRetriever:
    """Real per-theorist corpus retrieval. NOT IMPLEMENTED.

    Deliberately raises on construction rather than existing in a half-built state that
    something could fall back from. See `docs/prompts/01-corpus-retrieval.md` for the task
    that implements it.
    """

    mode = "corpus"
    grounded = True

    def __init__(self, corpus_root: Path | None = None) -> None:
        root = corpus_root or CORPUS_ROOT
        raise NotImplementedError(
            f"CorpusRetriever is not implemented (corpus root {root}). Phase 1 runs "
            "against StubRetriever and no run may be described as corpus-grounded. This "
            "raises rather than returning a stub: a silent fallback would let an "
            "ungrounded run be written up as grounded."
        )

    def retrieve(self, persona: Persona, question_text: str) -> str:  # pragma: no cover
        raise NotImplementedError


def get_retriever(mode: str) -> Retriever:
    """Resolve a retriever by name.

    Mirrors `llm.get_backend`. There is no default and no fallback: an unknown mode is an
    error, and asking for the corpus you do not have is an error, because both alternatives
    end with an ungrounded run wearing a grounded label.
    """
    if mode == "stub":
        return StubRetriever()
    if mode == "corpus":
        return CorpusRetriever()
    raise ValueError(f"unknown retrieval mode {mode!r}; expected 'stub' or 'corpus'")


def passage_ids(record_block: str) -> set[str]:
    """Every citable id in a block, as the backend would see them."""
    return set(PASSAGE_ID.findall(record_block))


def verify_citations(citations: list[str], record_block: str) -> list[str]:
    """Return the cited ids that do not appear in the block the persona was shown.

    A non-empty result is a hallucinated citation: the persona attributed a claim to a
    passage it was not given. Reported rather than corrected — the rate is a finding about
    the method, and silently dropping bad citations would erase it.
    """
    available = passage_ids(record_block)
    return [c for c in citations if c not in available]
