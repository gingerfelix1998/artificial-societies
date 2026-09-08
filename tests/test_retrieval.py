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
    ABSTRACT_SLUG,
    BELIEF_INSTRUCTION,
    BELIEF_SLUG,
    SOURCE_SLUG,
    build_abstract_chunks,
    build_belief_chunks,
    build_chunks,
    chunk_text,
    content_key,
    generate_beliefs,
    ingest_all,
    ingest_persona,
    load_manifest,
    regenerate_beliefs,
    split_sections,
)
from artsoc.llm import PASSAGE_ID
from artsoc.personas import (
    _SHARED_INSTRUCTION,
    NO_RECORD_MARKER,
    Persona,
    build_identity_prompt,
    build_question_prompt,
)
from artsoc.retrieval import (
    CorpusRetriever,
    get_retriever,
    resolve_passages,
    stem,
    tokenise,
    verify_citations,
)
from artsoc.schema import AnalyticalQuestion

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
    question = "what makes a threat credible"
    assert retriever.retrieve(_persona("has_no_store"), question) == ("", "none")


def test_one_store_per_persona(tmp_path) -> None:
    """Persona A citing persona B's text as its own would destroy the design."""
    retriever = _corpus(tmp_path)
    block, basis = retriever.retrieve(_persona("brodie"), "deterrence and the atomic bomb")
    assert block and basis == "sources"
    assert "Schelling" not in block
    assert all(pid.startswith("brodie:") for pid in PASSAGE_ID.findall(block))


def test_retrieval_ranks_the_on_topic_passage_first(tmp_path) -> None:
    """Otherwise the threshold is judging a passage that was never the best match."""
    block, _ = _corpus(tmp_path).retrieve(_persona("brodie"), "counterforce targeting credibility")
    assert "counterforce" in block.lower()


def test_an_unrelated_question_retrieves_nothing(tmp_path) -> None:
    """The threshold is what makes out_of_record fire; a retriever that always answers
    means personas extrapolate past their record on every question."""
    retriever = _corpus(tmp_path)
    unrelated = "monetary policy and inflation targets"
    assert retriever.retrieve(_persona("brodie"), unrelated) == ("", "none")


def test_the_threshold_is_the_dial_on_the_decline_rate(tmp_path) -> None:
    """Raising min_terms must actually make personas decline more, or it is not a control."""
    ingest_persona(_persona("brodie"), tmp_path, _fetcher(PAGE))
    question = "deterrence"
    lenient, _ = CorpusRetriever(tmp_path, min_terms=1).retrieve(_persona("brodie"), question)
    strict, strict_basis = CorpusRetriever(tmp_path, min_terms=8).retrieve(
        _persona("brodie"), question
    )
    assert lenient != ""
    assert (strict, strict_basis) == ("", "none")


def test_citations_verify_against_what_was_actually_shown(tmp_path) -> None:
    """The whole citation-integrity metric rests on this closing the loop."""
    retriever = _corpus(tmp_path)
    block, _ = retriever.retrieve(_persona("brodie"), "deterrence and the atomic bomb")
    shown = PASSAGE_ID.findall(block)
    assert verify_citations(shown, block) == []
    assert verify_citations(["brodie:wikipedia:999999999999"], block) == [
        "brodie:wikipedia:999999999999"
    ]


def test_top_k_bounds_how_much_a_theorist_is_shown(tmp_path) -> None:
    """Context costs tokens, and an unbounded block would grow with the corpus."""
    ingest_persona(_persona("brodie"), tmp_path, _fetcher(PAGE))
    retriever = CorpusRetriever(tmp_path, top_k=1, min_terms=1)
    block, _ = retriever.retrieve(_persona("brodie"), "deterrence")
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


# ---------------------------------------------------------------------------
# The belief fallback. ADR 0004.
# ---------------------------------------------------------------------------

BELIEFS = [
    "Deterrence rests on the survivability of second-strike forces, not on their size.",
    "The chief purpose of a military establishment after the atomic bomb is to avert war.",
]


def _with_beliefs(tmp_path, beliefs=BELIEFS):
    ingest_persona(_persona("brodie"), tmp_path, _fetcher(PAGE))
    (tmp_path / "brodie" / "beliefs.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in build_belief_chunks("brodie", beliefs)),
        encoding="utf-8",
    )
    return CorpusRetriever(tmp_path, min_terms=2)


def test_sources_are_preferred_over_beliefs(tmp_path) -> None:
    """A persona whose corpus covers the question must reason from the corpus.

    Beliefs are a fallback, not an overlay. If they took precedence the panel would assert
    positions even where it had citable evidence, which is the opposite of grounding.
    """
    block, basis = _with_beliefs(tmp_path).retrieve(
        _persona("brodie"), "the atomic bomb changed the purpose of armed force"
    )
    assert basis == "sources"
    assert ":wikipedia:" in block and ":belief:" not in block


def test_beliefs_answer_only_where_the_corpus_does_not(tmp_path) -> None:
    """The point of the fallback: a position the sources do not cover but the theorist held."""
    # Deliberately worded from the belief and not from the page: the fixture never
    # mentions survivability or second-strike forces, so sources cannot match it.
    block, basis = _with_beliefs(tmp_path).retrieve(
        _persona("brodie"), "what does survivability require of second-strike forces"
    )
    assert basis == "beliefs"
    assert ":belief:" in block


def test_a_question_overlapping_no_belief_still_declines(tmp_path) -> None:
    """The scoping requirement, asserted.

    Beliefs must be narrow enough that a question outside them retrieves nothing. A broad
    creed would match everything, drive the decline rate to zero, and defeat the escape
    hatch entirely — which is exactly what ADR 0004 refuses.
    """
    assert _with_beliefs(tmp_path).retrieve(
        _persona("brodie"), "monetary policy and inflation targeting in emerging markets"
    ) == ("", "none")


def test_a_broad_belief_would_defeat_the_hatch(tmp_path) -> None:
    """Documents why narrowness is enforced in the generation prompt rather than assumed.

    A belief mentioning everything matches everything. This is the failure mode the
    instruction guards against, demonstrated so the reason is not lost.
    """
    broad = ["This theorist thought about nuclear strategy, deterrence, escalation, "
             "policy, war, peace, weapons, states, threats and risk."]
    block, basis = _with_beliefs(tmp_path, broad).retrieve(
        _persona("brodie"), "what does escalation risk imply for policy"
    )
    assert basis == "beliefs", "a broad belief answers a question it has no business on"


def test_belief_ids_are_content_addressed_and_verifiable(tmp_path) -> None:
    """A persona must not be able to cite a belief it was never shown, as with any passage."""
    first = build_belief_chunks("brodie", BELIEFS)
    assert [c["passage_id"] for c in first] == [
        c["passage_id"] for c in build_belief_chunks("brodie", BELIEFS)
    ]
    for chunk in first:
        assert chunk["passage_id"].split(":")[1] == BELIEF_SLUG
        rendered = f"[{chunk['passage_id']}] {chunk['text']}"
        assert PASSAGE_ID.findall(rendered)[0] == chunk["passage_id"]

    block, _ = _with_beliefs(tmp_path).retrieve(
        _persona("brodie"), "survivability of second-strike forces"
    )
    assert verify_citations(PASSAGE_ID.findall(block), block) == []
    assert verify_citations(["brodie:belief:111111111111"], block) == ["brodie:belief:111111111111"]


def test_abstracts_are_distinguishable_from_encyclopedia_text(tmp_path) -> None:
    """A citation should say which store it came from; the two are not equal evidence."""
    works = [{"title": "The Absolute Weapon", "year": 1946,
              "abstract": "Argues that the atomic bomb makes averting war the purpose of force.",
              "source": "semantic_scholar"}]
    chunks = build_abstract_chunks("brodie", works)
    assert chunks and chunks[0]["passage_id"].split(":")[1] == ABSTRACT_SLUG
    assert "The Absolute Weapon (1946)" in chunks[0]["text"]


def test_a_work_with_no_abstract_is_recorded_as_a_miss(tmp_path) -> None:
    """Coverage is patchy by nature; a thin store must be traceable to missing abstracts."""
    persona = Persona(
        persona_id="brodie", name="Test", tags=["deterrence"],
        wikipedia="Bernard Brodie", key_works=["A Work With No Abstract Anywhere"],
    )
    manifest = ingest_persona(
        persona, tmp_path, _fetcher(PAGE),
        abstract_fetcher=lambda t: {"title": t, "abstract": "", "source": "none"},
        abstract_delay_s=0,
    )
    assert manifest["abstract_misses"] == ["A Work With No Abstract Anywhere"]
    assert manifest["abstracts"] == []


def test_a_belief_block_is_framed_as_a_position_not_a_record() -> None:
    """A persona told to "answer from your written record and cite passage ids" declines
    when handed a belief, because a position is not a record and has no source behind it.

    That is not hypothetical: retrieval supplied beliefs to three of twenty-four theorists
    and every one still declined until the framing was separated. With it, all three stated
    a position and cited the belief id. Beliefs are reasoned from directly (ADR 0004).
    """
    question = AnalyticalQuestion(question_id="q0", text="MOCK: question", tags=["deterrence"])
    block = "[brodie:belief:123] Deterrence rests on survivable second-strike forces."

    as_belief = build_question_prompt(question, block, "m2", basis="beliefs")
    assert "YOUR STATED POSITIONS" in as_belief
    assert "need no source to support them" in as_belief
    assert "RECORD:" not in as_belief

    as_source = build_question_prompt(question, block, "m2", basis="sources")
    assert "RECORD:" in as_source
    assert "YOUR STATED POSITIONS" not in as_source

    # An empty block still declares itself empty, whichever basis is claimed.
    assert NO_RECORD_MARKER in build_question_prompt(question, "", "m2", basis="beliefs")


# ---------------------------------------------------------------------------
# Ingest is idempotent. The corpus is written to disk so it need not be fetched twice.
# ---------------------------------------------------------------------------


class _CountingFetcher:
    """Records how often it was called, so a reuse can be proved rather than assumed."""

    def __init__(self, text: str = PAGE) -> None:
        self.calls = 0

    def __call__(self, title: str) -> dict:
        self.calls += 1
        return _fetcher(PAGE)(title)


def _one(pid: str = "brodie"):
    return [_persona(pid)]


def test_a_complete_store_is_reused_rather_than_refetched(tmp_path) -> None:
    """A full pass is ~26 minutes, almost all of it rate-limiting three public APIs.

    Refetching bytes already on disk is the cost this avoids; the assertion is on the
    fetcher call count, so a regression cannot hide behind a fast local test.
    """
    fetcher = _CountingFetcher()
    kw = {"abstract_fetcher": lambda t: {"title": t, "abstract": "", "source": "none"},
          "abstract_delay_s": 0}

    first, _ = ingest_all(_one(), tmp_path, fetcher, delay_s=0, **kw)
    assert fetcher.calls == 1
    assert first[0]["reused"] is False

    second, _ = ingest_all(_one(), tmp_path, fetcher, delay_s=0, **kw)
    assert fetcher.calls == 1, "a complete store must not be fetched again"
    assert second[0]["reused"] is True
    assert second[0]["n_chunks"] == first[0]["n_chunks"]


def test_refresh_forces_a_refetch(tmp_path) -> None:
    """Reuse must be the default, not the only behaviour."""
    fetcher = _CountingFetcher()
    kw = {"abstract_fetcher": lambda t: {"title": t, "abstract": "", "source": "none"},
          "abstract_delay_s": 0}
    ingest_all(_one(), tmp_path, fetcher, delay_s=0, **kw)
    manifests, _ = ingest_all(_one(), tmp_path, fetcher, delay_s=0, refresh=True, **kw)
    assert fetcher.calls == 2
    assert manifests[0]["reused"] is False


def test_an_interrupted_store_is_refetched_not_half_used(tmp_path) -> None:
    """A directory left behind by a killed ingest would otherwise pass as complete,
    silently giving that persona a truncated corpus."""
    fetcher = _CountingFetcher()
    kw = {"abstract_fetcher": lambda t: {"title": t, "abstract": "", "source": "none"},
          "abstract_delay_s": 0}
    ingest_all(_one(), tmp_path, fetcher, delay_s=0, **kw)

    (tmp_path / "brodie" / "beliefs.jsonl").unlink()
    assert load_manifest("brodie", tmp_path) is None
    ingest_all(_one(), tmp_path, fetcher, delay_s=0, **kw)
    assert fetcher.calls == 2, "an incomplete store must be rebuilt"


def test_an_unreadable_manifest_is_not_trusted(tmp_path) -> None:
    """A manifest that cannot be parsed is not a manifest."""
    fetcher = _CountingFetcher()
    kw = {"abstract_fetcher": lambda t: {"title": t, "abstract": "", "source": "none"},
          "abstract_delay_s": 0}
    ingest_all(_one(), tmp_path, fetcher, delay_s=0, **kw)
    (tmp_path / "brodie" / "manifest.json").write_text("{ truncated", encoding="utf-8")
    assert load_manifest("brodie", tmp_path) is None


def test_reuse_does_not_pause_between_personas(tmp_path) -> None:
    """Sleeping before a reuse would make a no-op pass as slow as a real one."""
    import time as _time

    fetcher = _CountingFetcher()
    kw = {"abstract_fetcher": lambda t: {"title": t, "abstract": "", "source": "none"},
          "abstract_delay_s": 0}
    personas = [_persona("a"), _persona("b"), _persona("c")]
    ingest_all(personas, tmp_path, fetcher, delay_s=0, **kw)

    started = _time.perf_counter()
    manifests, _ = ingest_all(personas, tmp_path, fetcher, delay_s=5.0, **kw)
    assert _time.perf_counter() - started < 1.0, "reuse must not sleep"
    assert all(m["reused"] for m in manifests)


# ---------------------------------------------------------------------------
# Resolving cited ids back to their text. Analyst-facing, and deliberately outside the
# retrieval path: a citation is only checkable against its claim if it can be read.
# ---------------------------------------------------------------------------


def test_a_cited_id_resolves_to_the_text_it_points_at(tmp_path) -> None:
    ingest_persona(_persona(), tmp_path, _fetcher(PAGE))
    chunks = [
        json.loads(line)
        for line in (tmp_path / "brodie" / "chunks.jsonl").read_text().splitlines()
        if line.strip()
    ]
    wanted = chunks[0]["passage_id"]

    found = resolve_passages("brodie", [wanted], tmp_path)
    assert found[wanted]["text"] == chunks[0]["text"]
    assert found[wanted]["section"] == chunks[0]["section"]
    assert found[wanted]["source"] == SOURCE_SLUG


def test_an_invented_id_does_not_resolve_and_is_not_filled_in(tmp_path) -> None:
    """The rate of invented citations is a finding about the method. Returning a
    placeholder for one would erase exactly what `unsupported_citations` records."""
    ingest_persona(_persona(), tmp_path, _fetcher(PAGE))
    assert resolve_passages("brodie", ["brodie:wikipedia:99999999"], tmp_path) == {}


def test_ids_resolve_only_against_the_persona_who_owns_them(tmp_path) -> None:
    """One store per persona, the same rule `CorpusRetriever` holds: persona A must not be
    able to show persona B's text as its own, in the reader any more than in the loop."""
    ingest_persona(_persona("brodie"), tmp_path, _fetcher(PAGE))
    ingest_persona(_persona("schelling", "Thomas Schelling"), tmp_path, _fetcher(OTHER_PAGE))
    schelling = [
        json.loads(line)["passage_id"]
        for line in (tmp_path / "schelling" / "chunks.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert resolve_passages("brodie", schelling, tmp_path) == {}


def test_beliefs_and_source_chunks_both_resolve(tmp_path) -> None:
    """A citation names a passage without saying which file it came from, and an analyst
    reading one should not have to know which store to look in."""
    store = tmp_path / "brodie"
    store.mkdir(parents=True)
    (store / "chunks.jsonl").write_text(
        json.dumps(
            {"passage_id": f"brodie:{SOURCE_SLUG}:11", "section": "Deterrence", "text": "src"}
        )
        + "\n",
        encoding="utf-8",
    )
    (store / "beliefs.jsonl").write_text(
        json.dumps(
            {"passage_id": f"brodie:{BELIEF_SLUG}:22", "section": "belief", "text": "blf"}
        )
        + "\n",
        encoding="utf-8",
    )

    ids = [f"brodie:{SOURCE_SLUG}:11", f"brodie:{BELIEF_SLUG}:22"]
    found = resolve_passages("brodie", ids, tmp_path)
    assert {p["source"] for p in found.values()} == {SOURCE_SLUG, BELIEF_SLUG}
    assert found[f"brodie:{BELIEF_SLUG}:22"]["text"] == "blf"


def test_a_persona_with_no_store_resolves_nothing_rather_than_raising(tmp_path) -> None:
    """A persona with no corpus is a fact about the world, not a broken configuration —
    the same distinction CorpusRetriever draws."""
    assert resolve_passages("nobody", ["nobody:wikipedia:1"], tmp_path) == {}


def test_resolving_passages_is_not_a_retrieval_path(tmp_path) -> None:
    """It returns what ids point at; it never selects, ranks or assembles a block. A
    function that could build a block would be a second, untested way into a prompt."""
    import inspect

    import artsoc.retrieval as retrieval_module

    source = inspect.getsource(retrieval_module.resolve_passages)
    assert "_select" not in source
    assert "_rank" not in source
    assert "format_passage" not in source


# ---------------------------------------------------------------------------
# ADR 0005 — no named real-world contemporary events in theorist output. Found live: the
# Posen persona justified a position with "as shown by Ukraine's 2022 posture", traced to
# a belief that faithfully summarised his real 2025 paper on the 2022 invasion. Not a
# hallucination — the belief-generation prompt had nothing telling it to abstract away the
# real case it was accurately citing.
# ---------------------------------------------------------------------------


def test_the_shared_instruction_forbids_naming_a_real_contemporary_event() -> None:
    """Reached by every theorist call through `build_identity_prompt`, any method or
    basis — the one point of leverage that covers both the sources path and the beliefs
    path without a separate rule for each."""
    lowered = _SHARED_INSTRUCTION.lower()
    assert "real country" in lowered or "specific real" in lowered
    assert "dated contemporary event" in lowered
    assert "underlying mechanism" in lowered

    persona = Persona(persona_id="posen", name="Barry Posen", tags=["organisational"])
    for method in ("m1", "m2", "m3"):
        assert "dated contemporary event" in build_identity_prompt(persona, method).lower()


def test_the_belief_generation_instruction_forbids_the_same() -> None:
    """New beliefs should come out already abstract rather than needing to be caught
    afterwards — the fix at the source, not only at the point of answering."""
    lowered = BELIEF_INSTRUCTION.lower()
    assert "timeless theoretical claim" in lowered
    assert "drop the case name" in lowered


class _CapturingBackend:
    """Records the prompt it was sent and returns a canned beliefs payload.

    What this proves is that `BELIEF_INSTRUCTION` — including the new rule — actually
    reaches the prompt sent to the model. It cannot prove a live model complies with it;
    that is a live-run check (see ADR 0005's Verification section), not something testable
    offline.
    """

    def __init__(self) -> None:
        self.last_prompt: str = ""

    def complete(self, *, role, system, prompt, cacheable=True):  # noqa: ANN001, ARG002
        self.last_prompt = prompt
        return json.dumps({"beliefs": ["A reinforcement force sized to the defender's own "
                                        "territorial requirement is a credible deterrent."]})


def test_belief_generation_sends_the_no_named_events_rule_to_the_model() -> None:
    """Wiring, not compliance: the instruction must reach the prompt `generate_beliefs`
    actually sends, or fixing the constant would be fixing nothing that is ever read."""
    persona = Persona(persona_id="posen", name="Barry Posen", tags=["organisational"])
    backend = _CapturingBackend()
    beliefs = generate_beliefs(persona, ["Some fetched source material."], backend)

    assert "drop the case name" in backend.last_prompt.lower()
    assert beliefs and "reinforcement force" in beliefs[0]


def test_regenerate_beliefs_rewrites_the_store_without_refetching(tmp_path) -> None:
    """The actual mechanism used to fix Posen's corpus.

    `ingest_all(..., refresh=True)` would re-fetch Wikipedia and every abstract to pick up
    a changed belief-generation prompt — a ~26-minute pass hitting Semantic Scholar's rate
    limit for source text that has not changed at all. This reads the chunks already on
    disk instead, so a fetcher that raises must never be reached.
    """

    def _must_not_fetch(title: str) -> dict:  # noqa: ARG001
        raise AssertionError("regenerate_beliefs must not fetch anything")

    persona = _persona("brodie")
    ingest_persona(persona, tmp_path, _fetcher(PAGE))

    backend = _CapturingBackend()
    n = regenerate_beliefs(persona, backend, tmp_path)

    assert n == 1
    assert "drop the case name" in backend.last_prompt.lower()
    rewritten = [
        json.loads(line)["text"]
        for line in (tmp_path / "brodie" / "beliefs.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert rewritten and "reinforcement force" in rewritten[0]

    manifest = json.loads((tmp_path / "brodie" / "manifest.json").read_text())
    assert manifest["n_beliefs"] == 1
    # chunks.jsonl and the source text are untouched by a belief-only regeneration.
    assert manifest["n_chunks"] > 0


def test_regenerate_beliefs_requires_an_ingested_store(tmp_path) -> None:
    """Nothing to regenerate from is a different fact from "no beliefs supported"."""
    with pytest.raises(FileNotFoundError):
        regenerate_beliefs(_persona("nobody"), _CapturingBackend(), tmp_path)


def test_posens_regenerated_beliefs_no_longer_name_ukraine() -> None:
    """The actual defect this ADR fixes, checked directly against the live corpus.

    Skipped rather than failed when the corpus has not been ingested on this machine —
    `make test` must still pass on a fresh clone with nothing in `data/corpora/`. Where the
    corpus IS present, this is the regression test naming the real thing that went wrong.
    """
    from artsoc.retrieval import CORPUS_ROOT

    path = CORPUS_ROOT / "posen" / "beliefs.jsonl"
    if not path.exists():
        pytest.skip("data/corpora/posen not ingested on this machine")

    texts = [json.loads(line)["text"] for line in path.read_text().splitlines() if line.strip()]
    assert texts, "posen has no beliefs; the assertion below would be vacuous"
    for text in texts:
        assert "ukraine" not in text.lower(), f"still names Ukraine: {text!r}"
        assert "2022" not in text, f"still names a dated event: {text!r}"
