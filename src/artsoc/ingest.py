"""Building a per-persona corpus: fetch, chunk, assign ids, write a manifest.

Separate from `retrieval.py` on purpose. Retrieval reads a store and knows nothing about
where it came from; ingestion writes one and knows nothing about how it will be searched.
A primary-text corpus later reuses everything below the fetch.

**Wikipedia is a tertiary source.** It is an encyclopedia article *about* a theorist, not
that theorist's writing. It exists here to prove the retrieval pipeline against text a
model must actually read, and to calibrate the decline threshold — the stub produced a 90%
out-of-record rate, which measures the stub rather than the personas. It cannot support the
held-out-writings check the approach doc claims as this population's advantage.

**Chunking and ids follow ADR 0003 and must not be changed casually.** Passage ids are
content-addressed, so re-chunking changes every id, invalidating every stored citation and
the whole response cache along with it.

Fetching uses `urllib` from the standard library. A dependency for one HTTP GET would be
the wrong trade, and the offline guarantee is easier to keep when there is nothing to keep
offline.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from artsoc.personas import Persona
from artsoc.retrieval import BM25_B, BM25_K1, CORPUS_ROOT, bm25_rank, format_passage, tokenise

#: Repo root, resolved the same way `world.py`, `personas.py` and `retrieval.py` do it.
REPO_ROOT = Path(__file__).resolve().parents[2]

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"

#: Wikimedia asks for a descriptive User-Agent that identifies the client.
USER_AGENT = "artsoc/0.1 (academic research; https://github.com/; contact via repository)"

#: Seconds between requests. Politeness, not a rate limit we are near.
FETCH_DELAY_S = 1.0

#: Target words per chunk (ADR 0003). Paragraphs are never split, so a single long
#: paragraph may exceed this rather than being cut mid-argument.
TARGET_WORDS = 150

#: Slug identifying the source document within a persona's store.
SOURCE_SLUG = "wikipedia"

_SECTION = re.compile(r"^==+\s*(.+?)\s*==+$", re.MULTILINE)

#: Sections that are reference apparatus rather than content. Chunking them would fill a
#: persona's store with bibliography that matches query terms without saying anything.
SKIP_SECTIONS = frozenset(
    {
        "references",
        "further reading",
        "external links",
        "see also",
        "notes",
        "sources",
        "works cited",
    }
)


def content_key(text: str) -> int:
    """A stable, content-addressed key for one chunk.

    Whitespace-normalised before hashing, so reflowing a source file does not silently
    shift every id. Twelve hex digits of SHA-256 is 48 bits; at a few hundred chunks per
    persona the collision probability is around 1e-11. Rendered as an integer because
    `llm.PASSAGE_ID` requires the final segment to be digits — a hex digest cannot go there.
    """
    normalised = " ".join(text.split())
    return int(hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:12], 16)


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split a plaintext Wikipedia extract into `(section_name, body)` pairs."""
    matches = list(_SECTION.finditer(text))
    if not matches:
        return [("Introduction", text)]

    sections = [("Introduction", text[: matches[0].start()])]
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((match.group(1), text[match.end() : end]))
    return [(name, body) for name, body in sections if body.strip()]


def group_paragraphs(section: str, paragraphs: list[str]) -> list[tuple[str, str]]:
    """Group whole paragraphs into ~`TARGET_WORDS` chunks within one section, per ADR 0003.

    **The one implementation of the grouping rule.** Both source pipelines call it, so
    "never crosses a section boundary" and "never splits mid-paragraph" cannot drift apart
    between them. What differs per source is only how a body is cut into paragraphs, which
    is the caller's job — a Wikipedia `explaintext` extract puts one paragraph per line,
    hand-written markdown separates them with a blank line.

    A paragraph longer than the target becomes its own oversized chunk rather than being
    split: a citation pointing at half an argument is worse than one pointing at a long one.
    """
    chunks: list[tuple[str, str]] = []
    current: list[str] = []
    count = 0
    for para in paragraphs:
        words = len(para.split())
        if current and count + words > TARGET_WORDS:
            chunks.append((section, "\n".join(current)))
            current, count = [], 0
        current.append(para)
        count += words
    if current:
        chunks.append((section, "\n".join(current)))
    return chunks


def chunk_text(text: str) -> list[tuple[str, str]]:
    """Chunk a Wikipedia extract into `(section_name, chunk_text)` pairs, per ADR 0003."""
    chunks: list[tuple[str, str]] = []
    for section, body in split_sections(text):
        if section.strip().lower() in SKIP_SECTIONS:
            continue
        # One paragraph per line: what `explaintext` returns.
        paragraphs = [p.strip() for p in body.split("\n") if p.strip()]
        chunks += group_paragraphs(section, paragraphs)
    return chunks


# ---------------------------------------------------------------------------
# The committed markdown corpus (ADR 0007).
# ---------------------------------------------------------------------------

#: Where the committed per-theorist documents live. Deliberately outside `data/corpora/`,
#: which is gitignored: one directory is input somebody wrote, the other is output this
#: module can rebuild. It is defined here and never in `retrieval.py`, because retrieval
#: must have no route to the source of record.
CORPUS_SRC_ROOT = REPO_ROOT / "data" / "corpora-src"

#: The markdown section header. The only thing ADR 0007 varies from ADR 0003's rule.
#: The trailing class is `[ \t]` rather than `\s`, which would match newlines and silently
#: swallow the blank line separating the heading from its first paragraph.
_MD_SECTION = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)

#: A `- ` or `* ` list item opening a claim.
_MD_BULLET = re.compile(r"^\s*[-*]\s+(.*)$")

#: Section names, lowercased, and what each is for. `Verify` is dropped rather than
#: chunked: it is project metadata about doubt, and a persona retrieving "Verify:
#: everything above" would produce nonsense and cite it. `Source` is a pointer, not
#: content, so it reaches the manifest only.
MARKDOWN_SLUG = "markdown"
ARGUMENT_SECTION = "argument"
CLAIMS_SECTION = "claims as stated"
SOURCE_SECTION = "source"

#: Header-block fields that travel with every chunk and claim from a document. A citation
#: to `confidence: general` would attest to nothing, so these are metadata rather than
#: citable text — but a reader resolving an id still needs to know what it came from.
DOC_META_FIELDS = ("work", "date", "type", "confidence", "availability_1962")

#: Stems must be citable. `llm.PASSAGE_ID` permits no hyphens in a source slug, and a
#: malformed id is invisible to the model, can never be cited, and would let citation
#: integrity read a clean zero off an inert path.
SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_]+$")

#: The `section` a claim record carries, so an analyst resolving a cited id can see that it
#: names a stated position rather than a passage of argument.
CLAIM_SECTION_NAME = "claim"

#: How many evidence passages a claim may carry, and how alike two claims must be to share
#: a corroboration group.
#:
#: Module constants rather than `RunConfig` fields, on the same reasoning as `TARGET_WORDS`:
#: they are baked into the artefact, and changing either requires a re-ingest rather than a
#: different arm. Both are recorded in the manifest so the edges stay reproducible.
CLAIM_EVIDENCE_K = 3
CLAIM_GROUP_JACCARD = 0.45


def parse_markdown(text: str) -> dict[str, Any]:
    """Parse one corpus document into its header block, title and `## ` sections.

    Returns `{"header": {...}, "title": str, "sections": {name: body}}`. Section names keep
    the case they were written in; lookups are by lowercase.

    The `---` block is metadata, not content, and `work` and `confidence` are required:
    every document declares how much it can be trusted, and one that does not say is not
    ingestable rather than assumed good.
    """
    header: dict[str, Any] = {}
    body = text
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        _, _, rest = stripped.partition("---")
        block, sep, rest = rest.partition("\n---")
        if not sep:
            raise ValueError("the `---` header block is opened but never closed")
        try:
            header = yaml.safe_load(block) or {}
        except yaml.YAMLError as exc:
            # Named rather than re-raised, because the overwhelmingly likely cause is a
            # colon in a title — half the works in this literature are "Title: Subtitle" —
            # and a raw scanner traceback does not say to quote the value.
            raise ValueError(
                f"the `---` header block is not valid YAML: {exc}. A value containing a "
                "colon must be quoted, e.g. work: 'The Absolute Weapon: Atomic Power and "
                "World Order'"
            ) from exc
        body = rest.partition("\n")[2]

    missing = [field for field in ("work", "confidence") if not header.get(field)]
    if missing:
        raise ValueError(
            f"the header block is missing {missing}; every document states which work it "
            "summarises and how far it can be trusted, and one that does not say is not "
            "ingested rather than assumed good"
        )

    title = ""
    for line in body.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    sections: dict[str, str] = {}
    matches = list(_MD_SECTION.finditer(body))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[match.group(1)] = body[match.end() : end]
    return {"header": header, "title": title, "sections": sections}


def _section_body(doc: dict[str, Any], wanted: str) -> str:
    for name, body in doc["sections"].items():
        if name.strip().lower() == wanted:
            return body
    return ""


def chunk_markdown(doc: dict[str, Any]) -> list[tuple[str, str]]:
    """Chunk a document's `## Argument` prose, per ADR 0003's rule and ADR 0007's headers.

    Paragraphs are split on blank lines rather than on single newlines. That is a departure
    from `chunk_text`'s splitter and it exists to *preserve* ADR 0003's rule: hand-written
    markdown is hard-wrapped, so splitting on single newlines would treat every wrapped
    line as a paragraph and let a group boundary fall mid-paragraph.
    """
    body = _section_body(doc, ARGUMENT_SECTION)
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", body) if p.strip()]
    return group_paragraphs("Argument", paragraphs)


def build_markdown_chunks(
    persona_id: str, source_slug: str, doc: dict[str, Any]
) -> list[dict[str, Any]]:
    """Evidence-passage records for one document, each with its content-addressed id.

    The id scheme is ADR 0003's, unchanged. `source_slug` is the publication rather than
    `wikipedia`, so every id from this path is new and no existing citation is invalidated.
    """
    meta = {field: doc["header"].get(field) for field in DOC_META_FIELDS}
    records = []
    for section, chunk in chunk_markdown(doc):
        passage = f"[{section}] {chunk}"
        records.append(
            {
                "passage_id": f"{persona_id}:{source_slug}:{content_key(passage)}",
                "section": section,
                "text": passage,
                "source_slug": source_slug,
                **meta,
            }
        )
    return records


def parse_claims(doc: dict[str, Any]) -> list[str]:
    """The bullets of `## Claims as stated`, verbatim, one claim each.

    Never model-generated. These are hand-authored propositions with human provenance;
    generating over them would replace an inspectable artefact with an unverifiable one.
    A wrapped bullet's continuation lines are joined, and whitespace is normalised so that
    reflowing a source file does not shift every id (ADR 0003).
    """
    claims: list[str] = []
    for line in _section_body(doc, CLAIMS_SECTION).splitlines():
        bullet = _MD_BULLET.match(line)
        if bullet:
            claims.append(bullet.group(1).strip())
        elif line.strip() and claims:
            claims[-1] = f"{claims[-1]} {line.strip()}"
    return [" ".join(c.split()) for c in claims if c.strip()]


def build_claims(
    persona_id: str, source_slug: str, doc: dict[str, Any], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Claim records for one document, with their evidence edges derived from its own prose.

    **The on-disk key is `passage_id`, not `claim_id`.** `retrieval.resolve_passages` reads
    that key, so a claim stored under a different name would resolve to nothing and every
    cited claim would render to an analyst as unresolved — read as a hallucinated citation
    when it was a real one. `claim_id` is the name in the ADR; this is the name on disk.

    **Evidence edges are derived, not annotated.** The documents carry no per-claim
    provenance, so each claim takes the best-scoring passages from its own publication.
    Same-publication scoping is a hard constraint rather than a default: a claim from a 1946
    work supported by prose from a 1959 one is a claim supported by an argument its author
    had not yet made.
    """
    meta = {field: doc["header"].get(field) for field in DOC_META_FIELDS}
    same_source = [c for c in chunks if c["source_slug"] == source_slug]
    tokenised = [tokenise(c["text"]) for c in same_source]

    records = []
    for text in parse_claims(doc):
        ranked = bm25_rank(tokenised, tokenise(text))
        supported_by = [
            same_source[i]["passage_id"]
            for score, i in ranked[:CLAIM_EVIDENCE_K]
            if score > 0
        ]
        records.append(
            {
                "passage_id": f"{persona_id}:{source_slug}:{content_key(text)}",
                "section": CLAIM_SECTION_NAME,
                "text": text,
                "source_slug": source_slug,
                "supported_by": supported_by,
                **meta,
            }
        )
    return records


def group_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign a corroboration group to every claim. Returns the same records, with `group`.

    **Claim text is never merged.** Merging would rewrite text, which changes the content
    key, which breaks ADR 0003's guarantee that the same text yields the same id forever.
    Every claim keeps its own id and its own wording; the group is an organising handle over
    them, so its id need not be content-addressed.

    Single-link connected components over normalised-token Jaccard, using the same
    tokeniser retrieval uses, so stemming and the stoplist apply. Iterated in sorted id
    order, and group ids numbered by each component's smallest member, so a rebuild produces
    the same assignment.

    **A group asserts vocabulary overlap, not agreement.** Jaccard is negation-blind: "a
    posture deters" and "a posture does not deter" share every content token. On a corpus
    made entirely of position statements that is the live risk, and it is why corroboration
    depth is reported as a diagnostic rather than as evidence (ADR 0007).
    """
    ordered = sorted(claims, key=lambda c: c["passage_id"])
    tokens = [set(tokenise(c["text"])) for c in ordered]

    parent = list(range(len(ordered)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(ordered)):
        for j in range(i + 1, len(ordered)):
            union = tokens[i] | tokens[j]
            if union and len(tokens[i] & tokens[j]) / len(union) >= CLAIM_GROUP_JACCARD:
                parent[find(j)] = find(i)

    labels: dict[int, str] = {}
    for i in range(len(ordered)):
        root = find(i)
        if root not in labels:
            labels[root] = f"g{len(labels):02d}"
        ordered[i]["group"] = labels[root]
    return ordered


def build_chunks(persona_id: str, text: str) -> list[dict[str, Any]]:
    """Chunk records ready to be written, each with its content-addressed passage id.

    The section name is prepended to the passage text so a persona shown a passage knows
    whether it came from "Career" or from a section about its actual argument.
    """
    records = []
    for section, body in chunk_text(text):
        passage = f"[{section}] {body}"
        records.append(
            {
                "passage_id": f"{persona_id}:{SOURCE_SLUG}:{content_key(passage)}",
                "section": section,
                "text": passage,
            }
        )
    return records


def fetch_wikipedia(title: str) -> dict[str, Any]:
    """Fetch one page's plaintext extract and its revision id.

    The revision id is what makes a run reproducible: Wikipedia pages change, and without
    it a record cannot state which text a persona actually saw.
    """
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "extracts|revisions",
            "explaintext": "1",
            "exlimit": "max",
            "rvprop": "ids|timestamp",
            "format": "json",
            "redirects": "1",
            "titles": title,
        }
    )
    request = urllib.request.Request(
        f"{WIKIPEDIA_API}?{params}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        payload = json.load(response)

    pages = payload.get("query", {}).get("pages", {})
    if not pages:
        raise ValueError(f"no page data returned for {title!r}")
    page = next(iter(pages.values()))
    if "missing" in page:
        raise ValueError(f"Wikipedia has no article titled {title!r}")

    extract = page.get("extract", "")
    if not extract.strip():
        raise ValueError(f"{title!r} returned an empty extract")

    revisions = page.get("revisions") or [{}]
    return {
        "title": page.get("title", title),
        "revision_id": revisions[0].get("revid"),
        "timestamp": revisions[0].get("timestamp"),
        "text": extract,
    }





# ---------------------------------------------------------------------------
# Publication abstracts. Patchy by nature: most of this literature predates the
# convention of publishing one, and a work with no abstract anywhere is recorded as a
# miss rather than filled in with something invented.
# ---------------------------------------------------------------------------

SEMANTIC_SCHOLAR = "https://api.semanticscholar.org/graph/v1"
OPENALEX = "https://api.openalex.org/works"

#: Semantic Scholar rate-limits unauthenticated clients aggressively — several calls in a
#: row return 429 — so requests are spaced and retried rather than hammered.
API_DELAY_S = 4.0
API_RETRIES = 3

ABSTRACT_SLUG = "abstract"
BELIEF_SLUG = "belief"


def _get_json(url: str) -> dict[str, Any]:
    """One GET with retries, for APIs that rate-limit rather than fail outright."""
    last: Exception | None = None
    for attempt in range(API_RETRIES):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(API_DELAY_S * (attempt + 2))
    raise ValueError(f"request failed after {API_RETRIES} attempts: {last}")


def _openalex_abstract(entry: dict[str, Any]) -> str:
    """OpenAlex stores abstracts as an inverted index; rebuild the text."""
    index = entry.get("abstract_inverted_index") or {}
    if not index:
        return ""
    positions: list[tuple[int, str]] = [
        (pos, word) for word, spots in index.items() for pos in spots
    ]
    positions.sort()
    return " ".join(word for _, word in positions)


def fetch_work_abstract(title: str) -> dict[str, Any]:
    """An abstract for one titled work, from whichever source has one.

    Title lookup rather than author lookup on purpose: it sidesteps author disambiguation
    entirely, which is what produced a pharmacologist when searching for Bernard Brodie.

    Returns an empty abstract rather than raising when nothing has one. A missing abstract
    is a fact about the literature, not an error, and it is recorded as a miss.
    """
    query = urllib.parse.urlencode(
        {"query": title, "fields": "title,year,abstract,citationCount", "limit": 3}
    )
    try:
        results = _get_json(f"{SEMANTIC_SCHOLAR}/paper/search?{query}").get("data", [])
        for paper in results:
            if paper.get("abstract"):
                return {
                    "title": paper.get("title") or title,
                    "year": paper.get("year"),
                    "abstract": paper["abstract"],
                    "source": "semantic_scholar",
                }
    except ValueError:
        pass

    time.sleep(API_DELAY_S)
    try:
        query = urllib.parse.urlencode({"search": title, "per-page": 3})
        for entry in _get_json(f"{OPENALEX}?{query}").get("results", []):
            abstract = _openalex_abstract(entry)
            if abstract:
                return {
                    "title": entry.get("display_name") or title,
                    "year": entry.get("publication_year"),
                    "abstract": abstract,
                    "source": "openalex",
                }
    except ValueError:
        pass

    return {"title": title, "year": None, "abstract": "", "source": "none"}


def fetch_author_papers(author_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Top-cited papers with abstracts for a VERIFIED author id.

    Only ever called with an id checked against that author's real papers. The registry
    stores None where verification failed, and this is not called at all in that case.
    """
    query = urllib.parse.urlencode(
        {"fields": "title,year,abstract,citationCount", "limit": 100}
    )
    papers = _get_json(f"{SEMANTIC_SCHOLAR}/author/{author_id}/papers?{query}").get("data", [])
    with_abstracts = [p for p in papers if p.get("abstract")]
    with_abstracts.sort(key=lambda p: -(p.get("citationCount") or 0))
    return [
        {
            "title": p.get("title") or "untitled",
            "year": p.get("year"),
            "abstract": p["abstract"],
            "source": "semantic_scholar",
        }
        for p in with_abstracts[:limit]
    ]


def build_abstract_chunks(persona_id: str, works: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One chunk per abstract. Abstracts are already the right size; splitting one would
    cut an argument in half, which is exactly what ADR 0003 avoids for paragraphs."""
    records = []
    for work in works:
        if not work.get("abstract"):
            continue
        label = f"{work['title']}" + (f" ({work['year']})" if work.get("year") else "")
        passage = f"[{label}] {work['abstract']}"
        records.append(
            {
                "passage_id": f"{persona_id}:{ABSTRACT_SLUG}:{content_key(passage)}",
                "section": label,
                "text": passage,
            }
        )
    return records


BELIEF_SYSTEM = (
    "You summarise what one scholar actually argued, from material about their work. "
    "You state only positions the material supports."
)

BELIEF_INSTRUCTION = """From the material below, list the specific positions {name} argued for.

Rules, and 3 and 4 are the ones that matter most:

1. Each belief is a distinct claim this person advanced, phrased as they would state it.
2. Ground every belief in the material. If it does not support one, list fewer. Never
   supply a position from general knowledge of the field.
3. KEEP EACH BELIEF NARROW. A belief about "nuclear strategy" or "the importance of
   deterrence" is useless: it matches every question, so this persona would answer
   everything and never decline. Name the specific mechanism, condition or claim.
4. PHRASE EACH BELIEF AS A TIMELESS THEORETICAL CLAIM. If the material illustrates the
   claim with a specific real country, war, or dated event, extract the general mechanism
   and drop the case name from the belief — never the reverse. "A reinforcement force
   sized to the defender's own territorial requirement is a more credible deterrent than
   a power-projection force" is a belief; naming which real war showed this is not.

Between three and eight beliefs. Produce JSON with key `beliefs`, a list of strings."""


def generate_beliefs(persona: Persona, sources: list[str], client: Any) -> list[str]:
    """Ask a model for the positions this persona actually argued, from its own sources.

    Generated rather than hand-authored so the beliefs trace to fetched text with recorded
    revision ids, and regenerate when the corpus changes. Hand-writing them would be one
    person's recollection of what a theorist thought, which is the placeholder problem
    `CLAUDE.md` warns about.

    Narrowness is the load-bearing property and is why the instruction labours it. A broad
    belief matches every question, which would drive the decline rate to zero and defeat
    the escape hatch entirely (ADR 0004).
    """
    from artsoc.llm import Role, role_marker

    material = "\n\n".join(sources)[:40000]
    system = f"{role_marker(Role.THEORIST)} {BELIEF_SYSTEM}"
    prompt = (
        BELIEF_INSTRUCTION.format(name=persona.name)
        + "\n\nMATERIAL:\n"
        + material
        + "\n\nRespond with a single JSON object and nothing else."
    )
    raw = client.complete(role=Role.THEORIST, system=system, prompt=prompt, cacheable=True)
    payload = json.loads(raw)
    beliefs = payload.get("beliefs", [])
    return [str(b).strip() for b in beliefs if str(b).strip()]


def build_belief_chunks(persona_id: str, beliefs: list[str]) -> list[dict[str, Any]]:
    """One chunk per belief, content-addressed like any other passage (ADR 0003)."""
    return [
        {
            "passage_id": f"{persona_id}:{BELIEF_SLUG}:{content_key(text)}",
            "section": "belief",
            "text": text,
        }
        for text in beliefs
    ]


def source_documents(persona_id: str, src_root: Path | None = None) -> list[tuple[str, Path]]:
    """This persona's committed documents as `(source_slug, path)`, slug-ordered.

    The slug is the filename stem, so the mapping from file to citable id is inspectable
    rather than configured. A stem that cannot appear in a passage id is refused here: a
    malformed id is invisible to the model, can never be cited, and citation integrity
    would read a clean zero off a path nothing could ever cite (ADR 0003).
    """
    directory = (src_root or CORPUS_SRC_ROOT) / persona_id
    found = sorted(directory.glob("*.md")) if directory.is_dir() else []
    documents = []
    for path in found:
        if not SLUG_PATTERN.match(path.stem):
            raise ValueError(
                f"{path} has a stem that cannot appear in a passage id; "
                f"`llm.PASSAGE_ID` allows only [A-Za-z0-9_] in a source slug, so a "
                "hyphenated or spaced stem produces passages nothing can ever cite"
            )
        documents.append((path.stem, path))
    return documents


def ingest_markdown_persona(
    persona: Persona,
    corpus_root: Path | None = None,
    src_root: Path | None = None,
) -> dict[str, Any]:
    """Build one persona's store from its committed markdown documents. Returns its manifest.

    **This function takes no fetcher and no model client, and that is the point.** A
    markdown ingest must be unable to reach Wikipedia, Semantic Scholar or a belief
    generator — not merely arranged so it does not. Reaching one would require adding a
    parameter and a call, rather than forgetting a guard, which is the same reason
    `PerceivedEvent` has no `ground_truth_detail` field.

    Declared `markdown` with no documents raises. Not a warning, not an empty store, and
    above all not a fetch: invariant 4, and an ungrounded run wearing a grounded label is
    the failure that cannot be detected afterwards.
    """
    documents = source_documents(persona.persona_id, src_root)
    if not documents:
        raise ValueError(
            f"{persona.persona_id} declares corpus_source='markdown' but "
            f"{(src_root or CORPUS_SRC_ROOT) / persona.persona_id} holds no .md documents. "
            "This raises rather than falling back to a fetch or to an empty store: either "
            "would produce a corpus the record could not distinguish from this one."
        )

    chunks: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    described: list[dict[str, Any]] = []
    for source_slug, path in documents:
        doc = parse_markdown(path.read_text(encoding="utf-8"))
        doc_chunks = build_markdown_chunks(persona.persona_id, source_slug, doc)
        if not doc_chunks:
            raise ValueError(f"{path} has no `## Argument` prose to chunk")
        doc_claims = build_claims(persona.persona_id, source_slug, doc, doc_chunks)
        if not doc_claims:
            raise ValueError(f"{path} has no `## Claims as stated` bullets to index")
        chunks += doc_chunks
        claims += doc_claims
        described.append(
            {
                "source_slug": source_slug,
                "title": doc["title"],
                **{field: doc["header"].get(field) for field in DOC_META_FIELDS},
                # A pointer, not content: the `## Source` section reaches the manifest and
                # never a chunk, so it cannot be retrieved or cited as evidence.
                "source_pointer": " ".join(_section_body(doc, SOURCE_SECTION).split()),
                "n_chunks": len(doc_chunks),
                "n_claims": len(doc_claims),
            }
        )

    # Reported together rather than one at a time: a claim its own document cannot support
    # is an authoring problem, and the author wants the whole list, not the first one.
    unsupported = [c["text"] for c in claims if not c["supported_by"]]
    if unsupported:
        raise ValueError(
            f"{persona.persona_id}: {len(unsupported)} claim(s) have no supporting passage "
            f"in their own document: {unsupported}. Every claim is shown with the prose that "
            "argues it, so a claim with no evidence would be presented as grounded when it "
            "is not."
        )

    claims = group_claims(claims)

    store = (corpus_root or CORPUS_ROOT) / persona.persona_id
    store.mkdir(parents=True, exist_ok=True)
    (store / "chunks.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8"
    )
    (store / "claims.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in claims), encoding="utf-8"
    )

    manifest = {
        "persona_id": persona.persona_id,
        "source": MARKDOWN_SLUG,
        "corpus_source": "markdown",
        "corpus_tier": "summary",
        "documents": described,
        "n_chunks": len(chunks),
        "n_claims": len(claims),
        "n_groups": len({c["group"] for c in claims}),
        # Recorded so the edges are reproducible and inspectable without re-deriving them.
        "claim_evidence": {
            "k": CLAIM_EVIDENCE_K,
            "min_score": 0.0,
            "scoring": (
                f"BM25 k1={BM25_K1} b={BM25_B} over the same source_slug's Argument chunks, "
                "stemmed tokens, stopwords dropped"
            ),
        },
        "claim_grouping": {
            "method": "normalised-token Jaccard, single-link connected components",
            "threshold": CLAIM_GROUP_JACCARD,
            "note": (
                "A group asserts vocabulary overlap, not agreement. Jaccard is "
                "negation-blind, so corroboration depth is a diagnostic, not evidence."
            ),
        },
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        # No belief store: `## Claims as stated` is hand-authored, inspectable without
        # running the system, and already proposition-shaped, so a generated belief store
        # would be worse on every axis that matters (ADR 0007 §7).
        "n_beliefs": 0,
        "beliefs_from": None,
        "note": (
            "PROJECT-WRITTEN SUMMARY. Secondary material about specific publications, not "
            "the theorist's own writing. Each document states its own `confidence`."
        ),
    }
    (store / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def ingest_persona(
    persona: Persona,
    corpus_root: Path | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_wikipedia,
    *,
    client: Any = None,
    abstract_fetcher: Callable[[str], dict[str, Any]] = fetch_work_abstract,
    author_fetcher: Callable[[str, int], list[dict[str, Any]]] = fetch_author_papers,
    abstract_delay_s: float = API_DELAY_S,
    src_root: Path | None = None,
) -> dict[str, Any]:
    """Fetch, chunk and write one persona's store. Returns its manifest.

    Dispatches on the persona's declared source before touching anything else. Every
    fetcher is injected so the tests exercise chunking, ids, beliefs and the manifest
    without touching the network — `make test` must keep running on a disconnected machine.
    """
    if persona.corpus_source == "markdown":
        return ingest_markdown_persona(persona, corpus_root, src_root)

    if not persona.wikipedia:
        raise ValueError(
            f"{persona.persona_id} has no `wikipedia` title in the registry; a persona "
            "with no source has no corpus and will decline every question"
        )

    fetched = fetcher(persona.wikipedia)
    chunks = build_chunks(persona.persona_id, fetched["text"])

    # Abstracts, by title. Title lookup rather than author lookup sidesteps the
    # disambiguation that resolved "Bernard Brodie" to a pharmacologist.
    works: list[dict[str, Any]] = []
    misses: list[str] = []
    for title in persona.key_works:
        try:
            work = abstract_fetcher(title)
        except (ValueError, OSError):
            work = {"title": title, "abstract": "", "source": "none"}
        if work.get("abstract"):
            works.append(work)
        else:
            # Recorded, never invented. A work with no abstract anywhere is a fact about
            # the literature and an analyst reading a thin store should see why it is thin.
            misses.append(title)
        if abstract_delay_s:
            time.sleep(abstract_delay_s)

    if persona.semantic_scholar:
        try:
            works.extend(author_fetcher(persona.semantic_scholar, 8))
        except (ValueError, OSError):
            misses.append(f"author:{persona.semantic_scholar}")

    # Deduplicate on title: a key work is often also a top-cited paper.
    seen: set[str] = set()
    unique = [w for w in works if not (w["title"].lower() in seen or seen.add(w["title"].lower()))]
    chunks += build_abstract_chunks(persona.persona_id, unique)

    if not chunks:
        raise ValueError(f"{persona.persona_id}: {fetched['title']!r} produced no chunks")

    beliefs: list[str] = []
    if client is not None:
        beliefs = generate_beliefs(
            persona, [c["text"] for c in chunks], client
        )

    store = (corpus_root or CORPUS_ROOT) / persona.persona_id
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{SOURCE_SLUG}.txt").write_text(fetched["text"], encoding="utf-8")
    (store / "chunks.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8"
    )
    (store / "beliefs.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in build_belief_chunks(persona.persona_id, beliefs)),
        encoding="utf-8",
    )

    manifest = {
        "persona_id": persona.persona_id,
        "source": SOURCE_SLUG,
        #: What actually built this store, and what tier of source it is. Recorded here so
        #: the retriever can check the registry's declaration against what happened rather
        #: than trusting it (invariant 9).
        "corpus_source": "wikipedia",
        "corpus_tier": "encyclopedia",
        "title": fetched["title"],
        # Reproducibility hook. A run cannot state which text it saw without this.
        "revision_id": fetched["revision_id"],
        "revision_timestamp": fetched["timestamp"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "licence": "CC BY-SA 4.0",
        "n_chunks": len(chunks),
        "n_chars": len(fetched["text"]),
        "abstracts": [
            {"title": w["title"], "year": w.get("year"), "source": w["source"]} for w in unique
        ],
        "abstract_misses": misses,
        "n_beliefs": len(beliefs),
        "beliefs_from": "model over the fetched sources above",
        # Recorded in the store itself so nobody reading a corpus can mistake it for the
        # theorist's own writing.
        "note": (
            "TERTIARY SOURCE. An encyclopedia article about this theorist plus abstracts "
            "of their work, not their writing. Cannot support the held-out-writings check."
        ),
    }
    (store / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def regenerate_beliefs(persona: Persona, client: Any, corpus_root: Path | None = None) -> int:
    """Rewrite one persona's belief store from its already-fetched chunks. No refetch.

    For when the belief-generation *prompt* changes and the sources it should run over are
    already sitting on disk — ADR 0005's fix, for instance. `ingest_all(..., refresh=True)`
    would re-fetch Wikipedia and every abstract to get there, which is a ~26-minute pass
    hitting Semantic Scholar's rate limit for text that has not changed. This reads the
    existing `chunks.jsonl` instead and only touches `beliefs.jsonl` and the manifest's
    belief count.

    Raises if the store has no `chunks.jsonl` — there is nothing to regenerate from, and
    silently producing an empty belief store would look like "no beliefs supported" rather
    than "not ingested yet". Returns the number of beliefs written.
    """
    store = (corpus_root or CORPUS_ROOT) / persona.persona_id
    chunks_path = store / "chunks.jsonl"
    if not chunks_path.exists():
        raise FileNotFoundError(
            f"no chunks.jsonl for {persona.persona_id} at {store}; run ingestion first"
        )
    sources = [
        json.loads(line)["text"] for line in chunks_path.read_text().splitlines() if line.strip()
    ]
    beliefs = generate_beliefs(persona, sources, client)

    (store / "beliefs.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in build_belief_chunks(persona.persona_id, beliefs)),
        encoding="utf-8",
    )

    manifest_path = store / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        manifest["n_beliefs"] = len(beliefs)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return len(beliefs)


#: Files a complete store must have. A store missing any of them was interrupted
#: part-way and is refetched rather than half-used.
STORE_FILES = ("manifest.json", "chunks.jsonl", "beliefs.jsonl")

#: A markdown store's equivalent. It has no belief store by design, so checking for one
#: would make every markdown store look permanently interrupted and refetch forever.
MARKDOWN_STORE_FILES = ("manifest.json", "chunks.jsonl", "claims.jsonl")


def load_manifest(persona_id: str, corpus_root: Path | None = None) -> dict[str, Any] | None:
    """A persona's manifest if its store is complete and readable, else None.

    Completeness is checked against the files and the manifest's own chunk count, not
    against the directory merely existing: an ingest killed part-way leaves a directory
    behind, and treating that as done would silently give a persona a truncated corpus.

    Which files count depends on what the manifest says built the store, read from the
    store itself rather than from the registry: this answers "is what is on disk finished",
    which is a question about the disk.
    """
    store = (corpus_root or CORPUS_ROOT) / persona_id
    try:
        manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    expected = (
        MARKDOWN_STORE_FILES
        if manifest.get("corpus_source") == "markdown"
        else STORE_FILES
    )
    if not all((store / name).exists() for name in expected):
        return None
    return manifest if manifest.get("n_chunks") else None


def ingest_all(
    personas: list[Persona],
    corpus_root: Path | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_wikipedia,
    delay_s: float = FETCH_DELAY_S,
    *,
    refresh: bool = False,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Ingest every persona that declares a source. Returns (manifests, failures).

    **A complete store is reused, not refetched.** The corpus is written to disk precisely
    so it does not have to be fetched again: a full pass is around twenty-six minutes,
    almost entirely Semantic Scholar rate-limiting, and repeating it hammers three public
    APIs to rebuild bytes that are already there. Reused manifests are marked `reused` so
    the caller can say which were fetched.

    To refetch one persona, delete its directory; to refetch everything, delete
    `data/corpora/`. That is deliberate rather than a `--force` flag: re-ingesting rewrites
    passage ids if any source text has changed, which invalidates stored citations (ADR
    0003), so it should take an explicit act rather than a keystroke.

    Failures are collected rather than raised, so one dead page does not abandon eleven
    good fetches — but they are returned, not swallowed, and the caller reports them.
    """
    manifests: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    fetched = 0
    for persona in personas:
        if persona.corpus_source == "markdown":
            # Always rebuilt. A markdown ingest touches no network and no model, so the
            # reuse path exists to avoid a cost this branch does not have — and rebuilding
            # means an edited document can never be silently served from a stale store.
            try:
                manifests.append(
                    {
                        **ingest_markdown_persona(
                            persona, corpus_root, kwargs.get("src_root")
                        ),
                        "reused": False,
                    }
                )
            except (ValueError, OSError) as exc:
                failures.append((persona.persona_id, str(exc)))
            continue

        if not persona.wikipedia:
            failures.append((persona.persona_id, "no `wikipedia` title in the registry"))
            continue

        if not refresh:
            existing = load_manifest(persona.persona_id, corpus_root)
            if existing is not None:
                manifests.append({**existing, "reused": True})
                continue

        # Only pause between calls that actually happen. Sleeping before a reuse would
        # make a no-op pass as slow as a real one.
        if fetched and delay_s:
            time.sleep(delay_s)
        try:
            manifests.append({**ingest_persona(persona, corpus_root, fetcher, **kwargs),
                              "reused": False})
            fetched += 1
        except (ValueError, OSError) as exc:
            failures.append((persona.persona_id, str(exc)))
    return manifests, failures




__all__ = [
    "ABSTRACT_SLUG",
    "BELIEF_INSTRUCTION",
    "BELIEF_SLUG",
    "CLAIM_EVIDENCE_K",
    "CLAIM_GROUP_JACCARD",
    "CLAIM_SECTION_NAME",
    "CORPUS_SRC_ROOT",
    "MARKDOWN_SLUG",
    "SLUG_PATTERN",
    "SOURCE_SLUG",
    "build_abstract_chunks",
    "build_belief_chunks",
    "build_chunks",
    "build_claims",
    "build_markdown_chunks",
    "chunk_markdown",
    "chunk_text",
    "content_key",
    "fetch_author_papers",
    "fetch_wikipedia",
    "fetch_work_abstract",
    "format_passage",
    "generate_beliefs",
    "group_claims",
    "group_paragraphs",
    "ingest_all",
    "ingest_markdown_persona",
    "ingest_persona",
    "load_manifest",
    "parse_claims",
    "parse_markdown",
    "regenerate_beliefs",
    "source_documents",
    "split_sections",
]
