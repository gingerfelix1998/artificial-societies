"""The committed markdown corpus: parsing, chunking, the claim index, and its retrieval.

Every test here runs against fixture documents in a temporary directory. Nothing reads
`data/corpora-src/`, nothing reaches a network, and nothing constructs a model client —
a markdown ingest structurally cannot do any of those, which is itself asserted below.

ADR 0007 is what these tests hold in place; ADR 0003's id scheme is inherited unchanged.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re

import pytest

from artsoc import ingest as ingest_module
from artsoc import retrieval as retrieval_module
from artsoc.ingest import (
    SLUG_PATTERN,
    TARGET_WORDS,
    build_markdown_chunks,
    chunk_markdown,
    content_key,
    ingest_markdown_persona,
    load_manifest,
    parse_claims,
    parse_markdown,
    source_documents,
)
from artsoc.llm import PASSAGE_ID
from artsoc.personas import Persona

# ---------------------------------------------------------------------------
# Fixture documents. Deliberately hard-wrapped, because that is what a hand-written
# document looks like and it is what the paragraph splitter has to cope with.
# ---------------------------------------------------------------------------

DOC_EARLY = """---
work: Fixture Work One
date: 1946
type: book_chapter
confidence: general
availability_1962: published
---

# Fixture One — the absolute weapon

## Argument

The arrival of a weapon of this destructive scale changes what an armed establishment
is for. Where the object of military preparation had been to win a war once it began,
the object now becomes to avert the war altogether, because no plausible political aim
survives the exchange that would follow. This is not a claim about restraint or about
the good intentions of statesmen. It is a claim about arithmetic: the destruction
available to both sides so far exceeds anything either could gain that the traditional
calculation of profit and loss no longer produces an answer a government could act on.
The consequence is that preparation continues, but its purpose inverts, and the forces
maintained are maintained in order never to be used, which is a condition military
organisations find difficult to hold in view for long. Nothing in that inversion is
comfortable, and nothing in it is optional either, because the alternative is a posture
built on a calculation that no longer returns a usable number to the government relying
on it.

Retaliation is what makes the threat operate. A force that could be removed by the first
blow deters nothing, because the adversary contemplating that blow is contemplating a
world in which no retaliation follows.

## Claims as stated

- The purpose of a military establishment shifts from winning wars to averting them.
- Deterrence rests on a retaliatory force that survives the adversary's first blow.

## Verify

FIXTUREVERIFY this section is project metadata about doubt and must never be chunked.

## Source

FIXTURESOURCE a pointer to the publication, never content.
"""

DOC_LATE = """---
work: Fixture Work Two
date: 1959
type: book
confidence: general
availability_1962: published
---

# Fixture Two — strategy in the missile age

## Argument

Survivability is the whole of the problem once delivery becomes fast. A force that
must be launched on warning is a force whose commander is asked to decide in minutes,
and the shorter that decision window the more the posture rests on the quality of
warning rather than on the judgement of the person warned.

Averting a war remains the object, and the establishment maintained to avert it is
larger than the one that would be maintained to win. Nothing in the missile age
reverses the inversion; it only raises the price of holding to it.

## Claims as stated

- The purpose of a military establishment shifts from winning wars to averting them.
- A force that must be launched on warning rests on warning rather than on judgement.

## Verify

FIXTUREVERIFY this section is project metadata about doubt and must never be chunked.

## Source

FIXTURESOURCE a pointer to the publication, never content.
"""


def _persona(persona_id: str = "brodie", corpus_source: str = "markdown") -> Persona:
    return Persona(
        persona_id=persona_id,
        name="Fixture Theorist",
        corpus_source=corpus_source,
        tags=["deterrence"],
    )


def _src(tmp_path: pathlib.Path, docs: dict[str, str], persona_id: str = "brodie"):
    """Write fixture documents to a `corpora-src` layout and return the root."""
    root = tmp_path / "corpora-src"
    (root / persona_id).mkdir(parents=True, exist_ok=True)
    for slug, text in docs.items():
        (root / persona_id / f"{slug}.md").write_text(text, encoding="utf-8")
    return root


def _both(tmp_path: pathlib.Path, persona_id: str = "brodie"):
    return _src(
        tmp_path,
        {"fixture_work_one_1946": DOC_EARLY, "fixture_work_two_1959": DOC_LATE},
        persona_id,
    )


def _ingest(tmp_path: pathlib.Path, persona_id: str = "brodie") -> dict:
    return ingest_markdown_persona(
        _persona(persona_id), tmp_path / "corpora", _both(tmp_path, persona_id)
    )


def _records(tmp_path: pathlib.Path, filename: str, persona_id: str = "brodie") -> list[dict]:
    path = tmp_path / "corpora" / persona_id / filename
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# Parsing. The header block is metadata; three of the five sections are not evidence.
# ---------------------------------------------------------------------------


def test_the_header_block_is_metadata_and_never_content() -> None:
    """A citation to `confidence: general` would attest to nothing.

    The fields travel with every chunk so a reader resolving an id can see what it came
    from, but they are not themselves retrievable or citable.
    """
    doc = parse_markdown(DOC_EARLY)
    assert doc["header"]["work"] == "Fixture Work One"
    assert doc["header"]["confidence"] == "general"
    assert doc["title"] == "Fixture One — the absolute weapon"
    assert "confidence" not in " ".join(doc["sections"].values())


def test_a_document_that_does_not_state_its_confidence_is_not_ingested() -> None:
    """Placeholders keep declaring themselves. One that does not say is refused, not
    assumed good — the whole corpus is secondary material and has to keep saying so."""
    with pytest.raises(ValueError, match="confidence"):
        parse_markdown("---\nwork: Something\n---\n\n# T\n\n## Argument\n\nprose\n")


def test_verify_and_source_never_become_evidence() -> None:
    """A persona retrieving "Verify: everything above" would produce nonsense and cite it.

    `Source` is a pointer rather than content, so it reaches the manifest only. Both are
    checked by a token that appears nowhere else in the fixture.
    """
    doc = parse_markdown(DOC_EARLY)
    chunks = build_markdown_chunks("brodie", "fixture_work_one_1946", doc)
    claims = parse_claims(doc)
    for token in ("FIXTUREVERIFY", "FIXTURESOURCE"):
        assert all(token not in c["text"] for c in chunks), f"{token} reached a passage"
        assert all(token not in claim for claim in claims), f"{token} reached a claim"
    assert any("FIXTUREVERIFY" in body for body in doc["sections"].values()), (
        "the fixture must actually contain the token, or this test proves nothing"
    )


def test_claims_are_read_verbatim_one_per_bullet() -> None:
    """They are hand-authored propositions with human provenance. Generating over them
    would replace an inspectable artefact with an unverifiable one."""
    claims = parse_claims(parse_markdown(DOC_EARLY))
    assert claims == [
        "The purpose of a military establishment shifts from winning wars to averting them.",
        "Deterrence rests on a retaliatory force that survives the adversary's first blow.",
    ]


# ---------------------------------------------------------------------------
# Chunking. ADR 0003's rule, ADR 0007's headers, and the splitter that keeps them agreeing.
# ---------------------------------------------------------------------------


def test_only_the_argument_section_becomes_evidence() -> None:
    """The retrievable substance is the prose a claim rests on, and nothing else."""
    chunks = chunk_markdown(parse_markdown(DOC_EARLY))
    assert chunks, "the Argument section must produce passages"
    assert {section for section, _ in chunks} == {"Argument"}


def test_a_hard_wrapped_paragraph_is_never_split() -> None:
    """ADR 0003's rule survives a source that wraps its lines.

    `chunk_text` splits paragraphs on single newlines because a Wikipedia extract puts one
    paragraph per line. Applying that splitter to hand-written markdown would treat every
    wrapped line as a paragraph and let a group boundary fall mid-sentence, which is the
    rule inverted rather than kept. This fixture's first paragraph is deliberately longer
    than the target, so a wrong splitter shows up as two chunks instead of one.
    """
    first = re.split(r"\n\s*\n", parse_markdown(DOC_EARLY)["sections"]["Argument"])[1]
    assert len(first.split()) > TARGET_WORDS, "the fixture paragraph must exceed the target"

    chunks = chunk_markdown(parse_markdown(DOC_EARLY))
    holding = [text for _, text in chunks if "arithmetic" in text]
    assert len(holding) == 1, "one oversized chunk, not a paragraph cut in half"
    assert holding[0].rstrip().endswith("the government relying on it.")
    assert "Retaliation is what makes" not in holding[0], "and not merged with the next one"


def test_both_pipelines_group_paragraphs_through_one_implementation() -> None:
    """Two copies of the grouping rule would drift, and the drift would be invisible.

    Only the paragraph splitter is allowed to differ between sources; the rule about what
    a group may contain is one function that both call.
    """
    for name in ("chunk_text", "chunk_markdown"):
        source = inspect.getsource(getattr(ingest_module, name))
        assert "group_paragraphs(" in source, f"{name} must not reimplement the rule"


def test_passage_ids_from_markdown_are_content_addressed_and_citable() -> None:
    """ADR 0003, unchanged. The id is derived from the text, so the same text yields the
    same id forever — and it must parse as an id the backend can see."""
    doc = parse_markdown(DOC_EARLY)
    first = build_markdown_chunks("brodie", "fixture_work_one_1946", doc)
    again = build_markdown_chunks("brodie", "fixture_work_one_1946", doc)
    assert [c["passage_id"] for c in first] == [c["passage_id"] for c in again]

    for chunk in first:
        rendered = f"[{chunk['passage_id']}] {chunk['text']}"
        assert PASSAGE_ID.findall(rendered) == [chunk["passage_id"]]
        assert chunk["passage_id"].split(":")[1] == "fixture_work_one_1946"


def test_markdown_ids_do_not_collide_with_the_wikipedia_path() -> None:
    """`source_slug` is per-publication rather than `wikipedia`, so every id from this
    path is new. Nothing existing breaks, and ADR 0003's re-chunking warning does not
    apply to adding this source."""
    doc = parse_markdown(DOC_EARLY)
    slugs = {
        c["passage_id"].split(":")[1]
        for c in build_markdown_chunks("brodie", "fixture_work_one_1946", doc)
    }
    assert slugs == {"fixture_work_one_1946"}
    assert "wikipedia" not in slugs


def test_reflowing_a_document_does_not_move_its_ids() -> None:
    """Whitespace-normalised hashing, per ADR 0003. Rewrapping a source file is an editing
    decision and must not invalidate every stored citation."""
    rewrapped = DOC_EARLY.replace(
        "what an armed establishment\nis for", "what an armed\nestablishment is for"
    )
    assert rewrapped != DOC_EARLY
    original = build_markdown_chunks("b", "s", parse_markdown(DOC_EARLY))
    reflowed = build_markdown_chunks("b", "s", parse_markdown(rewrapped))
    assert [c["passage_id"] for c in original] == [c["passage_id"] for c in reflowed]


def test_editing_one_passage_moves_only_that_id() -> None:
    """Content-addressed means locally content-addressed: an edit invalidates the citations
    that pointed at what changed, and leaves the rest alone."""
    edited = DOC_EARLY.replace("Retaliation is what makes", "Reprisal is what makes")
    before = build_markdown_chunks("b", "s", parse_markdown(DOC_EARLY))
    after = build_markdown_chunks("b", "s", parse_markdown(edited))
    moved = {c["passage_id"] for c in before} ^ {c["passage_id"] for c in after}
    assert len(moved) == 2, "exactly one id replaced by exactly one other"


def test_every_chunk_carries_the_document_it_came_from() -> None:
    """`work`, `date` and `confidence` travel with the passage so provenance is available
    to a reader resolving an id, without ever being citable text."""
    chunk = build_markdown_chunks("brodie", "fixture_work_one_1946", parse_markdown(DOC_EARLY))[0]
    assert chunk["source_slug"] == "fixture_work_one_1946"
    assert chunk["work"] == "Fixture Work One"
    assert chunk["confidence"] == "general"
    assert chunk["date"] == 1946


# ---------------------------------------------------------------------------
# Slugs. A slug that cannot appear in a passage id is not a slug.
# ---------------------------------------------------------------------------


def test_a_stem_that_cannot_be_cited_is_refused(tmp_path) -> None:
    """`PASSAGE_ID` permits no hyphens. A malformed id is invisible to the model, can never
    be cited, and citation integrity would read a clean zero off an inert path — the
    silent-success failure ADR 0003 was written against."""
    root = _src(tmp_path, {"fixture_work_one_1946": DOC_EARLY})
    (root / "brodie" / "brodie-1946-absolute-weapon.md").write_text(DOC_EARLY, encoding="utf-8")
    with pytest.raises(ValueError, match="cannot appear in a passage id"):
        source_documents("brodie", root)


def test_every_committed_document_has_a_citable_stem() -> None:
    """The same rule over the real directory, so a document added later cannot slip in with
    a stem nothing can cite."""
    root = ingest_module.CORPUS_SRC_ROOT
    offenders = [
        str(path)
        for path in sorted(root.rglob("*.md"))
        if path.parent != root and not SLUG_PATTERN.match(path.stem)
    ]
    assert offenders == [], f"these stems cannot appear in a passage id: {offenders}"


def test_the_slug_is_the_filename_so_the_mapping_is_inspectable(tmp_path) -> None:
    """Derived from the stem rather than configured: a reader holding a citation can find
    the document it came from without consulting a mapping table."""
    found = source_documents("brodie", _both(tmp_path))
    assert [slug for slug, _ in found] == ["fixture_work_one_1946", "fixture_work_two_1959"]


# ---------------------------------------------------------------------------
# The ingest itself, and what it structurally cannot reach.
# ---------------------------------------------------------------------------


def test_a_markdown_ingest_cannot_reach_a_fetcher(tmp_path, monkeypatch) -> None:
    """Invariant 4. Every fetcher raises on call, and the ingest succeeds anyway.

    Patched on the module rather than passed as arguments, because what must not reach a
    fetcher is the dispatch — a test that only declined to pass one would prove nothing
    about what `ingest_persona` does with its own defaults.
    """

    def explode(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("a markdown ingest reached the network")

    for name in ("fetch_wikipedia", "fetch_work_abstract", "fetch_author_papers"):
        monkeypatch.setattr(ingest_module, name, explode)

    manifest = ingest_module.ingest_persona(
        _persona(), tmp_path / "corpora", src_root=_both(tmp_path)
    )
    assert manifest["n_chunks"] > 0
    assert manifest["corpus_source"] == "markdown"


def test_a_markdown_ingest_needs_no_model_client(tmp_path) -> None:
    """No belief generation, so no model call, so no cost and nothing for ADR 0005 to
    constrain. The claims list is hand-authored and already proposition-shaped."""

    class Explode:
        def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("a markdown ingest called a model")

    manifest = ingest_module.ingest_persona(
        _persona(), tmp_path / "corpora", client=Explode(), src_root=_both(tmp_path)
    )
    assert manifest["n_beliefs"] == 0


def test_a_markdown_ingest_cannot_grow_a_fetcher_later() -> None:
    """Structural, not a matter of statement ordering.

    Reaching a fetcher would require adding a parameter and a call, rather than forgetting
    a guard — the same shape as `PerceivedEvent` having no `ground_truth_detail` field.
    Asserted over the signature and the source, the idiom
    `test_resolving_passages_is_not_a_retrieval_path` already uses.
    """
    params = inspect.signature(ingest_markdown_persona).parameters
    assert not [p for p in params if "fetch" in p or p == "client"], (
        f"a markdown ingest must take no fetcher and no model client; got {list(params)}"
    )
    source = inspect.getsource(ingest_markdown_persona)
    for forbidden in (
        "fetch_wikipedia",
        "fetch_work_abstract",
        "fetch_author_papers",
        "generate_beliefs",
    ):
        assert forbidden not in source, f"{forbidden} is reachable from a markdown ingest"


def test_declaring_markdown_with_no_documents_raises(tmp_path) -> None:
    """Not a warning, not an empty store, and above all not a fetch. Invariant 4."""
    (tmp_path / "corpora-src" / "brodie").mkdir(parents=True)
    with pytest.raises(ValueError, match="holds no .md documents"):
        ingest_markdown_persona(_persona(), tmp_path / "corpora", tmp_path / "corpora-src")


def test_the_store_declares_what_built_it(tmp_path) -> None:
    """Invariant 9. A record that cannot say what produced its numbers is not a record."""
    manifest = _ingest(tmp_path)
    assert manifest["corpus_source"] == "markdown"
    assert manifest["corpus_tier"] == "summary"
    assert "PROJECT-WRITTEN SUMMARY" in manifest["note"]
    assert manifest["n_beliefs"] == 0 and manifest["beliefs_from"] is None


def test_the_manifest_keeps_the_source_pointer_out_of_the_evidence(tmp_path) -> None:
    """`## Source` is a pointer, not content: recorded where an analyst can read it, and
    absent from anything a persona could retrieve and cite."""
    manifest = _ingest(tmp_path)
    pointers = [doc["source_pointer"] for doc in manifest["documents"]]
    assert all("FIXTURESOURCE" in pointer for pointer in pointers)
    assert all("FIXTURESOURCE" not in c["text"] for c in _records(tmp_path, "chunks.jsonl"))


def test_a_markdown_store_is_complete_without_a_belief_store(tmp_path) -> None:
    """It has none by design, so checking for one would make every markdown store look
    permanently interrupted and rebuild it forever."""
    _ingest(tmp_path)
    assert not (tmp_path / "corpora" / "brodie" / "beliefs.jsonl").exists()
    assert load_manifest("brodie", tmp_path / "corpora") is not None


def test_a_rebuild_produces_a_byte_identical_store(tmp_path) -> None:
    """Ids are content-addressed, so ingest is a pure function of the documents. A rebuild
    that moved an id would invalidate every stored citation silently."""
    _ingest(tmp_path)
    first = (tmp_path / "corpora" / "brodie" / "chunks.jsonl").read_text(encoding="utf-8")
    _ingest(tmp_path)
    assert (tmp_path / "corpora" / "brodie" / "chunks.jsonl").read_text(encoding="utf-8") == first


def test_retrieval_has_no_route_to_the_source_of_record() -> None:
    """`corpora-src` is ingest's input. Retrieval reads a built store and knows nothing
    about where it came from, which is what lets a different source be added without
    touching the retrieval path."""
    source = pathlib.Path(retrieval_module.__file__).read_text(encoding="utf-8")
    assert "corpora-src" not in source
    assert "CORPUS_SRC_ROOT" not in source


# ---------------------------------------------------------------------------
# The claim index: evidence edges, same-publication scoping, and grouping.
# ---------------------------------------------------------------------------


def test_a_claims_evidence_never_crosses_a_publication(tmp_path) -> None:
    """A claim from a 1946 work supported by prose from a 1959 one is a claim supported by
    an argument its author had not yet made.

    Non-vacuous by construction: the two fixtures state the *same* claim, and the 1946
    passage outscores the 1959 one for it (2.56 against 1.19). Drop the scoping and the
    1959 claim's evidence moves to the 1946 document, so this test fails the moment the
    constraint becomes a preference.
    """
    _ingest(tmp_path)
    claims = _records(tmp_path, "claims.jsonl")
    assert len({c["source_slug"] for c in claims}) == 2, "both documents must be indexed"

    for claim in claims:
        assert claim["supported_by"], "every claim carries evidence"
        for passage_id in claim["supported_by"]:
            assert passage_id.split(":")[1] == claim["source_slug"], (
                f"{claim['passage_id']} draws evidence from another publication"
            )


def test_evidence_ids_point_at_passages_that_exist(tmp_path) -> None:
    """An edge to an id nothing holds would hydrate to nothing and be indistinguishable
    from a claim with no evidence at all."""
    _ingest(tmp_path)
    passages = {c["passage_id"] for c in _records(tmp_path, "chunks.jsonl")}
    for claim in _records(tmp_path, "claims.jsonl"):
        assert set(claim["supported_by"]) <= passages


def test_a_claim_its_own_document_cannot_support_is_refused(tmp_path) -> None:
    """Every claim is shown with the prose that argues it, so a claim with no evidence
    would be presented as grounded when it is not. Raised at ingest, naming the claim."""
    orphan = DOC_EARLY.replace(
        "- Deterrence rests on a retaliatory force that survives the adversary's first blow.",
        "- Zebras nightingales bicycles.",
    )
    with pytest.raises(ValueError, match="no supporting passage"):
        ingest_markdown_persona(
            _persona(),
            tmp_path / "corpora",
            _src(tmp_path, {"fixture_work_one_1946": orphan}),
        )


def test_the_same_position_in_two_works_shares_a_group_without_merging(tmp_path) -> None:
    """Corroboration is readable, and ADR 0003 survives it.

    Merging the two statements into one would rewrite text, which changes the content key,
    which breaks the guarantee that the same text yields the same id forever. So both keep
    their own id and wording, and the group is an organising handle over them.
    """
    _ingest(tmp_path)
    claims = _records(tmp_path, "claims.jsonl")
    shared = [c for c in claims if c["text"].startswith("The purpose of a military")]

    assert len(shared) == 2, "the fixture states the same position in both works"
    assert len({c["group"] for c in shared}) == 1, "one group"
    assert len({c["passage_id"] for c in shared}) == 2, "two ids, never merged"
    assert len({c["source_slug"] for c in shared}) == 2, "corroboration depth 2"


def test_distinct_positions_do_not_share_a_group(tmp_path) -> None:
    """A grouping that swept everything together would report corroboration everywhere and
    mean nothing — the same way a broad belief defeats the escape hatch."""
    _ingest(tmp_path)
    by_group: dict[str, set[str]] = {}
    for claim in _records(tmp_path, "claims.jsonl"):
        by_group.setdefault(claim["group"], set()).add(claim["text"])
    assert len(by_group) > 1, "four claims stating three positions is not one group"


def test_grouping_is_deterministic(tmp_path) -> None:
    """Ids are content-addressed and the group assignment must be too, or the same corpus
    would read as differently corroborated on different days."""
    _ingest(tmp_path)
    first = (tmp_path / "corpora" / "brodie" / "claims.jsonl").read_text(encoding="utf-8")
    _ingest(tmp_path)
    assert (tmp_path / "corpora" / "brodie" / "claims.jsonl").read_text(
        encoding="utf-8"
    ) == first


def test_a_claim_record_is_shaped_like_a_passage(tmp_path) -> None:
    """The on-disk key is `passage_id`, not `claim_id`.

    `retrieval.resolve_passages` reads `passage_id`, `section` and `text`. A claim stored
    under a different key would resolve to nothing and render to an analyst as a
    hallucinated citation when it was a real one — the silent-success failure ADR 0003 was
    written against, reached by a different route.
    """
    _ingest(tmp_path)
    claim = _records(tmp_path, "claims.jsonl")[0]
    assert {"passage_id", "section", "text"} <= set(claim)
    assert "claim_id" not in claim
    assert claim["section"] == "claim"
    assert PASSAGE_ID.findall(f"[{claim['passage_id']}] {claim['text']}") == [
        claim["passage_id"]
    ]


def test_claim_ids_are_content_addressed_like_every_other_id(tmp_path) -> None:
    """ADR 0003 is not reopened for a new kind of record."""
    _ingest(tmp_path)
    for claim in _records(tmp_path, "claims.jsonl"):
        expected = content_key(claim["text"])
        assert claim["passage_id"].endswith(f":{expected}")


def test_the_manifest_records_how_the_edges_were_derived(tmp_path) -> None:
    """The edges are derived rather than annotated, so the derivation has to be recorded or
    they cannot be reproduced or argued with."""
    manifest = _ingest(tmp_path)
    assert manifest["claim_evidence"]["k"] > 0
    assert "BM25" in manifest["claim_evidence"]["scoring"]
    assert manifest["claim_grouping"]["threshold"] > 0
    assert "vocabulary overlap, not agreement" in manifest["claim_grouping"]["note"]
    assert manifest["n_claims"] == 4 and manifest["n_groups"] == 3


def test_claims_are_never_generated_by_a_model() -> None:
    """They are already written, with human provenance. Generating over them would replace
    an inspectable artefact with an unverifiable one, and there would be nothing left to
    check the generation against."""
    source = inspect.getsource(ingest_module.build_claims)
    for forbidden in ("client", "complete(", "generate_"):
        assert forbidden not in source
    assert "parse_claims(doc)" in source, "the bullets as written are the index"


def test_the_content_key_is_shared_with_the_wikipedia_path() -> None:
    """ADR 0003's derivation is not reopened: one hash, one normalisation, one rendering."""
    assert content_key("one   two\n\nthree") == content_key("one two three")
    assert str(content_key("anything")).isdigit(), "the final segment must be decimal"
