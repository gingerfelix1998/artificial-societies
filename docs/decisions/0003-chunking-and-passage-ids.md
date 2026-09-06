# ADR 0003 — Chunking and passage ids

Date: 2026-09-06
Status: accepted

## Context

`TheoristOpinion.citations` are verified against the block the persona was actually shown,
and `RunRecord.unsupported_citations` reports the ids it invented. That check only means
anything if an id refers to the same text tomorrow as it did today.

Two things follow, and they pull in the same direction:

- **Ids must be derived from content, not position.** A positional id (`chunk 7 of
  Schelling`) shifts the moment a paragraph is inserted upstream, silently repointing every
  stored citation at different text.
- **Chunk boundaries are therefore load-bearing.** Because the id *is* the content,
  re-chunking changes every id. That invalidates every stored citation and, since the
  retrieved block goes into the theorist prompt and the prompt is part of the cache key,
  it also discards the entire response cache. Re-chunking is the most expensive change
  available in this codebase, which is why the scheme is recorded before it is set.

The format is not free either. `llm.PASSAGE_ID` is the regex the backend parses:

```
\[([A-Za-z0-9_]+:[A-Za-z0-9_]+:\d+)\]
```

Three colon-separated segments, and the last must be digits. An id in any other shape is
invisible to the model and can never be cited, so the citation-integrity metric would read
a clean zero from an inert code path — the same class of silent success ADR 0001 dealt with.

## Decision

### Chunking

Split the plaintext extract on `== Section ==` headers, then group whole paragraphs within
each section to a target of roughly 150 words. **A chunk never crosses a section
boundary**, and the section name is prepended to the chunk text.

Paragraphs are not split mid-way. A paragraph longer than the target becomes its own
oversized chunk rather than being cut, because a citation pointing at half an argument is
worse than one pointing at a long one.

Rationale: section boundaries are the document's own semantic joints, so respecting them
costs nothing and keeps a retrieved passage coherent. Carrying the section name means a
persona shown a passage knows whether it came from "Career" or "The threat that leaves
something to chance", which materially changes how it should be used.

### Passage ids

```
[<persona_id>:<source_slug>:<content_key>]
```

- `persona_id` — from the registry. Makes a cross-persona citation visible on inspection.
- `source_slug` — which document, e.g. `wikipedia`.
- `content_key` — the first 12 hex digits of the SHA-256 of the **whitespace-normalised**
  chunk text, rendered as a decimal integer.

Twelve hex digits is 48 bits. At a few hundred chunks per persona the birthday collision
probability is around 10⁻¹¹. Rendering as decimal is forced by the `\d+` in the regex; a
hex digest cannot go in that position.

Normalising whitespace before hashing means reflowing a source file, or a change in line
wrapping, does not silently shift every id.

## Consequences

An id survives a rebuild from identical text, which is the property every stored citation
depends on and is asserted by a test that ingests twice and compares.

Changing the chunk target, the section rule, or the normalisation is a breaking change to
every past record. It requires a new ADR and, in practice, discarding `out/` and `.cache/`
rather than pretending old ids still resolve.

The scheme is source-agnostic. Wikipedia is the first corpus but nothing here assumes it;
a primary-text corpus later uses the same shape with a different `source_slug`, and the two
can coexist in one persona's store.

## Alternatives rejected

**Fixed-size overlapping windows.** Standard, and better for dense retrieval over long
documents. Rejected here because overlap means the same sentence appears under two ids, so
"which passage supports this" stops having one answer — directly at odds with citation
verification being the point.

**Sentence-level chunks.** Finer citations, but a single sentence rarely carries an
argument, and BM25 over very short documents is dominated by length normalisation rather
than by relevance.

**Positional ids with a stored mapping.** Would let chunking change without breaking old
citations, at the cost of a mapping file that must be kept forever and that becomes the
single point of failure for every past record. Content addressing needs no such file.
