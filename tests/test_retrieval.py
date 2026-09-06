"""Ingestion, chunking, content-addressed ids, and BM25 retrieval.

Every test here is offline. Ingestion takes an injected fetcher, so `make test` never
touches the network — the same guarantee tests/conftest.py enforces for model calls.

The invariant most of these protect is the one every stored citation depends on: a passage
id refers to the same text tomorrow as it did today (ADR 0003).
"""

from __future__ import annotations

import json

import pytest

from artsoc.ingest import (
    SOURCE_SLUG,
    build_chunks,
    chunk_text,
    content_key,
    ingest_all,
    ingest_persona,
    split_sections,
)
from artsoc.llm import PASSAGE_ID
from artsoc.personas import Persona
from artsoc.retrieval import (
    CorpusRetriever,
    get_retriever,
    stem,
    tokenise,
    verify_citations,
)

PAGE = """Bernard Brodie was an American military strategist.
He is often called the first nuclear strategist.

== Deterrence ==
Brodie argued that the atomic bomb changed the purpose of armed force.
Thus far the chief purpose of our military establishment has been to win wars.
From now on its chief purpose must be to avert them.

== Escalation ==
He was sceptical of counterforce targeting and of limited nuclear options.
Credibility of a threat depends on the interests genuinely at stake.

== References ==
Some citation apparatus that says nothing and should never be chunked.
"""

OTHER_PAGE = """Thomas Schelling was an American economist.

== Bargaining ==
Schelling treated deterrence as a bargaining problem between adversaries.
The threat that leaves something to chance is his best known device.
"""


def _persona(pid: str = "brodie", title: str = "Bernard Brodie") -> Persona:
    return Persona(persona_id=pid, name="Test Persona", tags=["deterrence"], wikipedia=title)


def _fetcher(text: str):
    def fetch(title: str) -> dict:
        return {"title": title, "revision_id": 12345, "timestamp": "2026-01-01T00:00:00Z",
                "text": text}
    return fetch


# ---------------------------------------------------------------------------
# Chunking and ids. ADR 0003.
# ---------------------------------------------------------------------------


def test_chunks_never_cross_a_section_boundary() -> None:
    """A passage spanning two sections cites text the section name does not describe."""
    for section, body in chunk_text(PAGE):
        assert "==" not in body
        assert section in {"Introduction", "Deterrence", "Escalation"}


def test_reference_apparatus_is_not_chunked() -> None:
    """A bibliography matches query terms while saying nothing, crowding out real passages."""
    sections = {s for s, _ in chunk_text(PAGE)}
    assert "References" not in sections
    assert "References" in {s for s, _ in split_sections(PAGE)}, "the fixture must have one"


def test_every_chunk_carries_its_section_name() -> None:
    """A persona shown a passage must know whether it came from Career or from an argument."""
    for chunk in build_chunks("brodie", PAGE):
        assert chunk["text"].startswith(f"[{chunk['section']}]")


def test_passage_ids_are_stable_across_a_rebuild() -> None:
    """The property every stored citation depends on: same text, same id, forever."""
    first = [c["passage_id"] for c in build_chunks("brodie", PAGE)]
    second = [c["passage_id"] for c in build_chunks("brodie", PAGE)]
    assert first == second
    assert len(set(first)) == len(first), "ids must be unique within a store"


def test_passage_ids_change_when_the_text_changes() -> None:
    """Content addressing means an edited chunk is a different passage, not the same one.

    Only the edited chunk changes: untouched sections keep their ids, which is what makes
    a partial corpus update cheap rather than invalidating every citation in the store.
    """
    before = {c["passage_id"]: c["text"] for c in build_chunks("brodie", PAGE)}
    after = {
        c["passage_id"]: c["text"]
        for c in build_chunks("brodie", PAGE.replace("atomic bomb", "hydrogen bomb"))
    }
    changed = [t for pid, t in before.items() if pid not in after]
    assert len(changed) == 1, "exactly the edited chunk should have a new id"
    assert "atomic bomb" in changed[0]
    assert len(set(before) & set(after)) == len(before) - 1, "untouched chunks keep their ids"


def test_ids_survive_reflowing_the_source() -> None:
    """Whitespace normalisation, or a line-wrap change would shift every id."""
    assert content_key("one   two\n\nthree") == content_key("one two three")


def test_emitted_ids_are_parseable_by_the_backend() -> None:
    """An id the backend cannot match can never be cited, and integrity would read zero."""
    for chunk in build_chunks("lieber_press", PAGE):
        rendered = f"[{chunk['passage_id']}] {chunk['text']}"
        assert PASSAGE_ID.findall(rendered)[0] == chunk["passage_id"]
        assert chunk["passage_id"].split(":")[1] == SOURCE_SLUG


# ---------------------------------------------------------------------------
# Ingestion.
# ---------------------------------------------------------------------------


def test_ingest_writes_a_manifest_with_a_revision_id(tmp_path) -> None:
    """Wikipedia changes; without the revision a run cannot say which text it saw."""
    manifest = ingest_persona(_persona(), tmp_path, _fetcher(PAGE))
    assert manifest["revision_id"] == 12345
    assert manifest["source"] == SOURCE_SLUG
    assert manifest["n_chunks"] > 0
    written = json.loads((tmp_path / "brodie" / "manifest.json").read_text())
    assert written == manifest
    assert "TERTIARY" in written["note"], "the store must say what kind of source it is"


def test_a_persona_with_no_source_is_reported_not_skipped_silently(tmp_path) -> None:
    """A 0% contribution needs to be traceable to a missing page, not read as a finding."""
    bare = Persona(persona_id="nobody", name="No Page", tags=["deterrence"])
    with pytest.raises(ValueError, match="no `wikipedia` title"):
        ingest_persona(bare, tmp_path, _fetcher(PAGE))

    manifests, failures = ingest_all([bare, _persona()], tmp_path, _fetcher(PAGE), delay_s=0)
    assert [m["persona_id"] for m in manifests] == ["brodie"]
    assert failures and failures[0][0] == "nobody"


def test_one_bad_page_does_not_abandon_the_good_ones(tmp_path) -> None:
    """Eleven good fetches should not be lost to one dead link."""

    def flaky(title: str) -> dict:
        if title == "Broken":
            raise ValueError("Wikipedia has no article titled 'Broken'")
        return _fetcher(PAGE)(title)

    personas = [_persona("a", "Broken"), _persona("b", "Fine")]
    manifests, failures = ingest_all(personas, tmp_path, flaky, delay_s=0)
    assert len(manifests) == 1 and len(failures) == 1


# ---------------------------------------------------------------------------
# Retrieval. Invariant 4 lives here.
# ---------------------------------------------------------------------------


def _corpus(tmp_path):
    ingest_persona(_persona("brodie"), tmp_path, _fetcher(PAGE))
    ingest_persona(_persona("schelling", "Thomas Schelling"), tmp_path, _fetcher(OTHER_PAGE))
    return CorpusRetriever(tmp_path, min_terms=2)


def test_a_missing_corpus_raises_rather_than_falling_back(tmp_path) -> None:
    """Invariant 4. A stub run reported as grounded could not be detected afterwards."""
    with pytest.raises(FileNotFoundError, match="artsoc ingest"):
        CorpusRetriever(tmp_path / "nothing-here")


def test_corpus_retrieval_reports_itself_as_grounded(tmp_path) -> None:
    """`grounded` comes from the object that did the retrieving, never from a config."""
    assert _corpus(tmp_path).grounded is True
    assert get_retriever("stub").grounded is False


def test_a_persona_with_no_store_declines_rather_than_erroring(tmp_path) -> None:
    """No documents is a fact about the world; the escape hatch firing is the right answer."""
    retriever = _corpus(tmp_path)
    assert retriever.retrieve(_persona("has_no_store"), "what makes a threat credible") == ""


def test_one_store_per_persona(tmp_path) -> None:
    """Persona A citing persona B's text as its own would destroy the design."""
    retriever = _corpus(tmp_path)
    block = retriever.retrieve(_persona("brodie"), "deterrence and the atomic bomb")
    assert block
    assert "Schelling" not in block
    assert all(pid.startswith("brodie:") for pid in PASSAGE_ID.findall(block))


def test_retrieval_ranks_the_on_topic_passage_first(tmp_path) -> None:
    """Otherwise the threshold is judging a passage that was never the best match."""
    block = _corpus(tmp_path).retrieve(_persona("brodie"), "counterforce targeting credibility")
    assert "counterforce" in block.lower()


def test_an_unrelated_question_retrieves_nothing(tmp_path) -> None:
    """The threshold is what makes out_of_record fire; a retriever that always answers
    means personas extrapolate past their record on every question."""
    retriever = _corpus(tmp_path)
    assert retriever.retrieve(_persona("brodie"), "monetary policy and inflation targets") == ""


def test_the_threshold_is_the_dial_on_the_decline_rate(tmp_path) -> None:
    """Raising min_terms must actually make personas decline more, or it is not a control."""
    ingest_persona(_persona("brodie"), tmp_path, _fetcher(PAGE))
    question = "deterrence"
    lenient = CorpusRetriever(tmp_path, min_terms=1).retrieve(_persona("brodie"), question)
    strict = CorpusRetriever(tmp_path, min_terms=8).retrieve(_persona("brodie"), question)
    assert lenient != ""
    assert strict == ""


def test_citations_verify_against_what_was_actually_shown(tmp_path) -> None:
    """The whole citation-integrity metric rests on this closing the loop."""
    retriever = _corpus(tmp_path)
    block = retriever.retrieve(_persona("brodie"), "deterrence and the atomic bomb")
    shown = PASSAGE_ID.findall(block)
    assert verify_citations(shown, block) == []
    assert verify_citations(["brodie:wikipedia:999999999999"], block) == [
        "brodie:wikipedia:999999999999"
    ]


def test_top_k_bounds_how_much_a_theorist_is_shown(tmp_path) -> None:
    """Context costs tokens, and an unbounded block would grow with the corpus."""
    ingest_persona(_persona("brodie"), tmp_path, _fetcher(PAGE))
    retriever = CorpusRetriever(tmp_path, top_k=1, min_terms=1)
    block = retriever.retrieve(_persona("brodie"), "deterrence")
    assert len(PASSAGE_ID.findall(block)) == 1


def test_stopwords_do_not_swallow_load_bearing_terms() -> None:
    """"control", "first" and "chance" are terms of art here, not noise.

    Compared as stems, since tokenise stems: an over-eager stoplist and an over-eager
    stemmer fail the same way, by quietly deleting the vocabulary that carries the topic.
    """
    tokens = set(tokenise("escalation control first strike leaves something to chance"))
    for term in ("control", "first", "strike", "chance"):
        assert stem(term) in tokens, f"{term!r} was lost"


def test_stemming_unifies_the_vocabulary_of_this_literature() -> None:
    """Without it the questions and the corpus do not meet at all.

    The questions are abstract ("a deterrent threat that is credible") and the corpus is
    encyclopedic ("deterrence", "credibility"). Unstemmed, a question about deterrent
    credibility retrieved nothing from Schelling's page — which would have surfaced as a
    persona declining rather than as a retriever failing to match.
    """
    for a, b in [
        ("deterrence", "deterrent"),
        ("credibility", "credible"),
        ("escalation", "escalatory"),
        ("proliferation", "proliferate"),
        ("signalling", "signal"),
        ("organisational", "organisation"),
    ]:
        assert stem(a) == stem(b), f"{a} and {b} must share a stem"

    # And it must not collapse distinct terms of art into one another.
    assert stem("first") != stem("force")
    assert stem("control") != stem("counterforce")
