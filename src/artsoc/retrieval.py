"""The M2 grounding interface, and the boundary between grounded and ungrounded runs.

Invariant 4 is the reason this module exists as a module rather than as a function inside
`agents.py`: **a real retriever must raise rather than degrade to `StubRetriever`.** A
silent fallback is the one failure that would let an ungrounded run be written up as
corpus-grounded, and no test downstream could detect it after the fact — the output record
would look identical to a real one.

So `grounded` is a property of the retriever, not a flag the caller sets. Whatever ends up
in `RunRecord.grounded` comes from the object that actually produced the text, and the only
way to get `True` is to construct a `CorpusRetriever`, which requires an ingested corpus on
disk and raises without one.

**One store per persona.** `retrieve` is handed a single `Persona` and has no access to the
registry, so persona A structurally cannot retrieve persona B's text and cite it as its
own. That is a property of the signature, not of the implementation being careful.

**Passage ids are content-addressed, not positional.** `TheoristOpinion.citations` are
verified against the block the persona was shown, so an id that shifts when an index is
rebuilt makes every past record unverifiable. The stub's ids are trivially stable because
there is one passage per persona; `ingest.content_key` derives the real ones from a hash of
the chunk text, per ADR 0003.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

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

    def retrieve(self, persona: Persona, question_text: str) -> tuple[str, str]: ...


def format_passage(persona_id: str, source: str, index: int, text: str) -> str:
    """Render one passage with a citable id.

    The id format is what `llm.PASSAGE_ID` matches; a passage rendered any other way is
    invisible to the backend and can never be cited, so both ends use this one function.
    """
    return f"[{persona_id}:{source}:{index}] {text}"


def bm25_rank(docs: list[list[str]], query: list[str]) -> list[tuple[float, int]]:
    """BM25 scores over one candidate set, highest first, as `(score, index)` pairs.

    **One scorer, used at both ends.** Retrieval ranks passages and claims with it; ingest
    ranks a claim's own document to derive its evidence edges. Two implementations would
    let the edges recorded at build time disagree with the ranking applied at run time,
    and the disagreement would be invisible in the output.

    Ties break on index, so a rebuild produces the same order from the same input.
    """
    lengths = [len(d) for d in docs]
    avg_len = sum(lengths) / len(lengths) if lengths else 0.0
    n = len(docs)

    scored: list[tuple[float, int]] = []
    for i, doc in enumerate(docs):
        counts: dict[str, int] = {}
        for token in doc:
            counts[token] = counts.get(token, 0) + 1
        score = 0.0
        for term in set(query):
            freq = counts.get(term, 0)
            if not freq:
                continue
            containing = sum(1 for d in docs if term in d)
            idf = math.log(1 + (n - containing + 0.5) / (containing + 0.5))
            denom = freq + BM25_K1 * (1 - BM25_B + BM25_B * lengths[i] / (avg_len or 1))
            score += idf * freq * (BM25_K1 + 1) / denom
        scored.append((score, i))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    return scored


class StubRetriever:
    """A one-line paraphrase from the registry. Never grounded, and says so.

    This exists so the loop runs end to end without a corpus. The text it returns is a
    `corpus_notes` placeholder — not a quotation, not evidence, and not something any claim
    of grounding may rest on. `grounded` is `False` and there is no constructor argument
    that can change it.
    """

    mode = "stub"
    grounded = False

    def retrieve(self, persona: Persona, question_text: str) -> tuple[str, str]:
        # question_text is accepted and deliberately unused: the stub does no relevance
        # selection at all. A stub that appeared to select would invite the reader to
        # interpret which passages came back, and there is nothing there to interpret.
        if not persona.corpus_notes.strip():
            # No note for this persona, so nothing was "retrieved". Returning empty is the
            # mechanism that makes out_of_record fire, which is the honest outcome here.
            return "", "none"
        block = format_passage(persona.persona_id, "notes", 0, persona.corpus_notes.strip())
        return block, "sources"


#: Words carrying no topical signal. Kept deliberately short: an aggressive stoplist would
#: strip terms like "control" or "first" that are load-bearing in this literature.
STOPWORDS: frozenset[str] = frozenset(
    """a an and are as at be been by can could do does for from had has have how in into
    is it its may might must of on or should than that the their there these they this
    to under was were what when which who why will with would you your
    make makes making made does did done use used using such other others same
    also very more most much many some any each both either neither""".split()
)

_WORD = re.compile(r"[a-z0-9]+")
_VOWEL = re.compile(r"[aeiouy]")

#: Suffixes stripped to unify morphological variants, longest first.
#:
#: Stemming is not optional here, it is the difference between working and not. The
#: questions are abstract ("what makes a deterrent threat credible") and the corpus is
#: encyclopedic prose ("deterrence", "credibility"). Without stemming those do not match at
#: all: a question about deterrent credibility retrieved *nothing* from Schelling's page,
#: which would have shown up as a persona declining rather than as a retriever failing.
#:
#: A hand-rolled stripper rather than a dependency, and deliberately conservative: it
#: unifies 16 of 18 checked pairs from this literature's vocabulary while leaving terms of
#: art like "first", "control", "chance" and "risk" untouched.
_SUFFIXES = (
    "ationally", "ational", "fulness", "ousness", "iveness", "ility", "ality",
    "atory", "itory", "ities", "ivity", "aliti", "biliti",
    "ation", "ative", "ingly", "ently", "antly", "ence", "ance", "ency", "ancy",
    "ment", "ness", "ical", "ible", "able", "ions", "ives", "ized", "ised", "izes",
    "ises", "ing", "ion", "ive", "ity", "ous", "ful", "ise", "ize", "ies", "ent",
    "ant", "ism", "ist", "ate", "le", "ed", "es", "ly", "al", "ic", "er", "or",
    "y", "s", "e",
)


def stem(word: str) -> str:
    """Strip one suffix, longest match first.

    A single pass, not repeated: stripping twice turns "organisation" into "organ" while
    "organisational" becomes "organis", which is worse than not stemming at all. Short
    suffixes need a longer surviving stem so that "signal" does not become "sign".
    """
    for suffix in _SUFFIXES:
        if not word.endswith(suffix):
            continue
        candidate = word[: -len(suffix)]
        floor = 5 if len(suffix) <= 4 else 4
        if len(candidate) >= floor and _VOWEL.search(candidate):
            word = candidate
            break
    # "signall" -> "signal", "deterr" -> "deter".
    if len(word) > 4 and word[-1] == word[-2]:
        word = word[:-1]
    return word

#: Okapi BM25 parameters. Standard values; not tuned, and not tunable per arm, because the
#: threshold below is what actually decides the decline rate.
BM25_K1 = 1.5
BM25_B = 0.75


def tokenise(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, stopwords removed, stemmed."""
    return [
        stem(w) for w in _WORD.findall(text.lower()) if w not in STOPWORDS and len(w) > 1
    ]


class CorpusRetriever:
    """Per-persona BM25 retrieval over an ingested corpus.

    **One store per persona is structural.** `retrieve` is handed a single `Persona` and
    has no access to the registry, so persona A cannot retrieve persona B's text and cite
    it as its own. IDF is computed within that persona's own store for the same reason.

    **Two failure modes, deliberately different:**

    * A missing corpus *root* raises. Nothing has been ingested, which is misconfiguration,
      and invariant 4 forbids degrading to the stub — a silent fallback would let an
      ungrounded run be written up as grounded.
    * A persona with *no store* returns `""`. That persona genuinely has no documents, so
      declining is the correct answer and the escape hatch firing is the honest outcome.
      This is a fact about the world, not a broken configuration.

    **The threshold is corpus-independent.** BM25 scores are unbounded and collection-
    relative, so an absolute cutoff would not transfer between a 3,000-word page and a
    32,000-word one. Requiring the top passage to match a minimum number of distinct
    content terms from the question does transfer, and is interpretable: it says the
    passage is about what was asked, rather than merely scoring well among poor options.
    """

    mode = "corpus"
    grounded = True

    def __init__(
        self,
        corpus_root: Path | None = None,
        *,
        top_k: int = 3,
        min_terms: int = 1,
        belief_min_terms: int | None = None,
    ) -> None:
        self.root = corpus_root or CORPUS_ROOT
        if not self.root.is_dir():
            raise FileNotFoundError(
                f"no corpus at {self.root}; run `artsoc ingest` first. This raises rather "
                "than falling back to StubRetriever: a run that quietly used placeholder "
                "text while reporting grounded=true could not be detected afterwards."
            )
        self.top_k = top_k
        self.min_terms = min_terms
        # Beliefs need their own, lower bar. The same absolute count applied to a 150-word
        # source chunk and a one-sentence belief is not the same test: a short statement
        # cannot contain that many distinct query terms, so beliefs failed whenever sources
        # did and the fallback never fired once across 84 persona-question pairs.
        self.belief_min_terms = (
            belief_min_terms if belief_min_terms is not None else max(1, min_terms - 1)
        )
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._manifests: dict[str, dict[str, Any]] = {}

    def _manifest(self, persona_id: str) -> dict[str, Any]:
        """This persona's ingest manifest, or `{}` if it has no store."""
        if persona_id not in self._manifests:
            path = self.root / persona_id / "manifest.json"
            try:
                self._manifests[persona_id] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._manifests[persona_id] = {}
        return self._manifests[persona_id]

    def _confirmed_source(self, persona: Persona) -> str:
        """What built this persona's store, checked against what the registry declares.

        The registry declares and the manifest confirms. A disagreement raises rather than
        picking one: a persona declared `markdown` whose store was built from an
        encyclopedia article would answer from biography while the record said otherwise,
        and no test downstream could detect it afterwards.

        A persona declared `markdown` with nothing ingested reaches this with an empty
        manifest, so it raises here too — which is exactly the required behaviour, arrived
        at structurally rather than by a separate existence check.
        """
        # Manifests written before schema 1.2.0 carry no `corpus_source`. Reading those as
        # `wikipedia` is not an inference: no code that could write a markdown store existed
        # before the key did, so every keyless store is a Wikipedia one by construction.
        built = self._manifest(persona.persona_id).get("corpus_source", "wikipedia")
        if persona.corpus_source != built:
            raise ValueError(
                f"{persona.persona_id}: the registry declares corpus_source="
                f"{persona.corpus_source!r} but the store at {self.root / persona.persona_id} "
                f"was built as {built!r}. Run `artsoc ingest` to rebuild it. This raises "
                "rather than serving whichever is present, because a run answering from an "
                "encyclopedia article while reporting a summary corpus could not be detected "
                "afterwards."
            )
        return built

    def _load(self, persona_id: str, filename: str = "chunks.jsonl") -> list[dict[str, Any]]:
        """One of this persona's stores, or an empty list if it has none."""
        key = f"{persona_id}/{filename}"
        if key not in self._cache:
            path = self.root / persona_id / filename
            if not path.exists():
                self._cache[key] = []
            else:
                self._cache[key] = [
                    json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
        return self._cache[key]

    def _select(
        self, chunks: list[dict[str, Any]], query: list[str], min_terms: int | None = None
    ) -> str:
        """Filter for relevance, then rank, then render. Empty when nothing is relevant.

        Filtering before ranking matters: for a question about deterrent credibility,
        Schelling's top-scoring chunk was his global-warming work, matching only "threat",
        while the chunk that mentioned credibility ranked third. A passage has to be about
        what was asked before its score means anything.
        """
        if not chunks:
            return ""
        wanted = set(query)
        floor = self.min_terms if min_terms is None else min_terms
        eligible = [
            c for c in chunks if len(wanted & set(tokenise(c["text"]))) >= floor
        ]
        if not eligible:
            return ""
        ranked = self._rank(eligible, query)
        selected = [eligible[i] for score, i in ranked[: self.top_k] if score > 0]
        if not selected:
            return ""
        return "\n\n".join(f"[{c['passage_id']}] {c['text']}" for c in selected)

    def _rank(self, chunks: list[dict[str, Any]], query: list[str]) -> list[tuple[float, int]]:
        """BM25 scores over one persona's store, highest first."""
        return bm25_rank([tokenise(c["text"]) for c in chunks], query)

    def retrieve(self, persona: Persona, question_text: str) -> tuple[str, str]:
        """Return `(block, basis)` — sources first, beliefs only as a fallback.

        The order is the whole design (ADR 0004). A persona whose corpus covers the
        question reasons from the corpus; beliefs are what it falls back on when the corpus
        does not. And beliefs are filtered by the *same* relevance test, so a question that
        overlaps none of them retrieves nothing and the persona declines — which is what
        stops the out-of-record rate collapsing to zero.
        """
        self._confirmed_source(persona)
        query = tokenise(question_text)
        if not query:
            return "", "none"

        block = self._select(self._load(persona.persona_id), query)
        if block:
            return block, "sources"

        block = self._select(
            self._load(persona.persona_id, "beliefs.jsonl"), query, self.belief_min_terms
        )
        if block:
            return block, "beliefs"

        return "", "none"


def get_retriever(mode: str, **kwargs: Any) -> Retriever:
    """Resolve a retriever by name.

    Mirrors `llm.get_backend`. There is no default and no fallback: an unknown mode is an
    error, and asking for the corpus you do not have is an error, because both alternatives
    end with an ungrounded run wearing a grounded label.
    """
    if mode == "stub":
        return StubRetriever()
    if mode == "corpus":
        return CorpusRetriever(**kwargs)  # type: ignore[arg-type]
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


#: The stores a persona's passages can live in, and what each one is.
#:
#: `wikipedia` and `abstract` ids are in `chunks.jsonl`; `belief` ids are in
#: `beliefs.jsonl`. Both are read here because a citation names a passage without saying
#: which file it came from, and an analyst reading a citation should not have to know.
_STORE_FILES = ("chunks.jsonl", "beliefs.jsonl")


def resolve_passages(
    persona_id: str, ids: list[str], corpus_root: Path | None = None
) -> dict[str, dict[str, str]]:
    """Look up the text behind cited passage ids, for reading rather than for retrieval.

    **This is an analyst-facing lookup and is not part of the retrieval path.** It takes ids
    that are already in a `RunRecord` and returns what they point at, so a citation can be
    checked against the claim it was attached to. It never selects, ranks or assembles a
    block, and nothing it returns can reach a prompt: `Theorist.opine` goes through
    `Retriever.retrieve` and has no route to this function.

    **An unresolvable id is left out rather than filled in.** That is the whole point of the
    citation-integrity metric — an id the store does not contain was invented, and returning
    a placeholder for it would erase exactly the finding `unsupported_citations` records.
    The caller sees which ids came back and which did not.

    Ids are only read from the named persona's own store, mirroring the one-store-per-persona
    rule in `CorpusRetriever`: an id whose prefix names someone else is not resolved here.
    """
    root = corpus_root or CORPUS_ROOT
    wanted = {i for i in ids if i.split(":", 1)[0] == persona_id}
    if not wanted:
        return {}

    found: dict[str, dict[str, str]] = {}
    for filename in _STORE_FILES:
        path = root / persona_id / filename
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            passage_id = record.get("passage_id")
            if passage_id in wanted and passage_id not in found:
                found[passage_id] = {
                    "passage_id": passage_id,
                    "section": record.get("section", ""),
                    "text": record.get("text", ""),
                    # The middle segment of the id says what kind of source this is:
                    # a tertiary encyclopedia article, a publication abstract, or a
                    # belief generated from that persona's own fetched sources.
                    "source": passage_id.split(":")[1] if ":" in passage_id else "",
                }
    return found
