# `data/corpora-src/` — the committed source of record

One directory per persona, named by `persona_id`, holding project-written markdown
documents about that theorist's specific publications.

**This directory is committed. `data/corpora/` is not.** One is input somebody wrote; the
other is output `artsoc ingest` can rebuild from it. That is why the new directory sits
outside `.gitignore`'s `data/corpora/*` rule rather than adding an exception to it.

## What may go here

**Project-written summaries only. Never primary text.** These documents are secondary
material: our account of what a publication argued, not the publication. A primary-text
corpus, if one is ever added, stays gitignored and has its licensing checked first.

Every document states its own `confidence`, and that field is accurate. Do not upgrade one,
and do not fill in a `## Verify` section that is still open.

## Filenames

The filename stem becomes the `source_slug` in every passage and claim id from that
document, so the mapping from file to citation is inspectable rather than configured.

**Stems must match `[A-Za-z0-9_]+`.** `llm.PASSAGE_ID` permits no hyphens, and a malformed
id is invisible to the model, can never be cited, and would let citation integrity read a
clean zero off a path nothing could ever cite. `artsoc ingest` refuses a bad stem, and a
test asserts the rule over this whole directory.

Do not repeat the persona in the filename — the directory already supplies it:

```
data/corpora-src/brodie/absolute_weapon_1946.md
data/corpora-src/brodie/strategy_missile_age_1959.md
```

## Document structure

```markdown
---
work: The Absolute Weapon
date: 1946
type: book_chapter
confidence: general
availability_1962: published
---

# Brodie 1946 — The Absolute Weapon

## Argument

Prose. Chunked into evidence passages at ~150 words, whole paragraphs only, split on
blank lines. This is what a claim below rests on.

## Claims as stated

- One hand-authored proposition per bullet, verbatim.
- These are the retrieval index. They are never model-generated: generating over them
  would replace an inspectable artefact with an unverifiable one.

## Verify

What is still open. **Dropped at ingest** — a persona retrieving "Verify: everything
above" would produce nonsense and cite it.

## Source

A pointer. Reaches the manifest only, never a chunk, so it cannot be cited as evidence.
```

Where each part goes, and why, is ADR 0007. The header block travels with every chunk and
claim as metadata rather than as citable text: a citation to `confidence: general` would
attest to nothing.

## Building from it

Declare the persona in `data/theorists/registry.yaml`:

```yaml
corpus_source: markdown
```

then `artsoc ingest`. Declaring `markdown` with no documents here raises rather than
falling back to a fetch or to an empty store (invariant 4).
