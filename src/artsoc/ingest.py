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

from artsoc.personas import Persona
from artsoc.retrieval import CORPUS_ROOT, format_passage

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


def chunk_text(text: str) -> list[tuple[str, str]]:
    """Chunk an extract into `(section_name, chunk_text)` pairs, per ADR 0003.

    Paragraphs are grouped to roughly `TARGET_WORDS` and never cross a section boundary.
    A paragraph longer than the target becomes its own oversized chunk rather than being
    split: a citation pointing at half an argument is worse than one pointing at a long one.
    """
    chunks: list[tuple[str, str]] = []
    for section, body in split_sections(text):
        if section.strip().lower() in SKIP_SECTIONS:
            continue
        current: list[str] = []
        count = 0
        for para in (p.strip() for p in body.split("\n") if p.strip()):
            words = len(para.split())
            if current and count + words > TARGET_WORDS:
                chunks.append((section, "\n".join(current)))
                current, count = [], 0
            current.append(para)
            count += words
        if current:
            chunks.append((section, "\n".join(current)))
    return chunks


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

Rules, and the third is the one that matters most:

1. Each belief is a distinct claim this person advanced, phrased as they would state it.
2. Ground every belief in the material. If it does not support one, list fewer. Never
   supply a position from general knowledge of the field.
3. KEEP EACH BELIEF NARROW. A belief about "nuclear strategy" or "the importance of
   deterrence" is useless: it matches every question, so this persona would answer
   everything and never decline. Name the specific mechanism, condition or claim.

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


def ingest_persona(
    persona: Persona,
    corpus_root: Path | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_wikipedia,
    *,
    client: Any = None,
    abstract_fetcher: Callable[[str], dict[str, Any]] = fetch_work_abstract,
    author_fetcher: Callable[[str, int], list[dict[str, Any]]] = fetch_author_papers,
    delay_s: float = API_DELAY_S,
) -> dict[str, Any]:
    """Fetch, chunk and write one persona's store. Returns its manifest.

    Every fetcher is injected so the tests exercise chunking, ids, beliefs and the manifest
    without touching the network — `make test` must keep running on a disconnected machine.
    """
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
        if delay_s:
            time.sleep(delay_s)

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


def ingest_all(
    personas: list[Persona],
    corpus_root: Path | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_wikipedia,
    delay_s: float = FETCH_DELAY_S,
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Ingest every persona that declares a source. Returns (manifests, failures).

    Failures are collected rather than raised, so one dead page does not abandon eleven
    good fetches — but they are returned, not swallowed, and the caller reports them.
    """
    manifests: list[dict[str, Any]] = []
    failures: list[tuple[str, str]] = []
    for i, persona in enumerate(personas):
        if not persona.wikipedia:
            failures.append((persona.persona_id, "no `wikipedia` title in the registry"))
            continue
        try:
            manifests.append(ingest_persona(persona, corpus_root, fetcher, **kwargs))
        except (ValueError, OSError) as exc:
            failures.append((persona.persona_id, str(exc)))
        if delay_s and i < len(personas) - 1:
            time.sleep(delay_s)
    return manifests, failures




__all__ = [
    "ABSTRACT_SLUG",
    "BELIEF_SLUG",
    "SOURCE_SLUG",
    "build_abstract_chunks",
    "build_belief_chunks",
    "build_chunks",
    "chunk_text",
    "content_key",
    "fetch_author_papers",
    "fetch_wikipedia",
    "fetch_work_abstract",
    "format_passage",
    "generate_beliefs",
    "ingest_all",
    "ingest_persona",
    "split_sections",
]
