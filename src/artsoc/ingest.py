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
        "bibliography",
        "sources",
        "works cited",
        "selected bibliography",
        "publications",
        "selected publications",
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


def ingest_persona(
    persona: Persona,
    corpus_root: Path | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_wikipedia,
) -> dict[str, Any]:
    """Fetch, chunk and write one persona's store. Returns its manifest.

    `fetcher` is injected so the tests exercise chunking, ids and the manifest without
    touching the network — `make test` must keep running on a disconnected machine.
    """
    if not persona.wikipedia:
        raise ValueError(
            f"{persona.persona_id} has no `wikipedia` title in the registry; a persona "
            "with no source has no corpus and will decline every question"
        )

    fetched = fetcher(persona.wikipedia)
    chunks = build_chunks(persona.persona_id, fetched["text"])
    if not chunks:
        raise ValueError(f"{persona.persona_id}: {fetched['title']!r} produced no chunks")

    store = (corpus_root or CORPUS_ROOT) / persona.persona_id
    store.mkdir(parents=True, exist_ok=True)
    (store / f"{SOURCE_SLUG}.txt").write_text(fetched["text"], encoding="utf-8")
    (store / "chunks.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in chunks), encoding="utf-8"
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
        # Recorded in the store itself so nobody reading a corpus can mistake it for the
        # theorist's own writing.
        "note": (
            "TERTIARY SOURCE. An encyclopedia article about this theorist, not their "
            "writing. Cannot support the held-out-writings check."
        ),
    }
    (store / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def ingest_all(
    personas: list[Persona],
    corpus_root: Path | None = None,
    fetcher: Callable[[str], dict[str, Any]] = fetch_wikipedia,
    delay_s: float = FETCH_DELAY_S,
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
            manifests.append(ingest_persona(persona, corpus_root, fetcher))
        except (ValueError, OSError) as exc:
            failures.append((persona.persona_id, str(exc)))
        if delay_s and i < len(personas) - 1:
            time.sleep(delay_s)
    return manifests, failures


__all__ = [
    "SOURCE_SLUG",
    "build_chunks",
    "chunk_text",
    "content_key",
    "fetch_wikipedia",
    "format_passage",
    "ingest_all",
    "ingest_persona",
    "split_sections",
]
