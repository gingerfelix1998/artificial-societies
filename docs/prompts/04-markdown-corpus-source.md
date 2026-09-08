# Claude Code prompt — markdown corpus source and ingest

Plan-mode prompt. Adds a committed per-theorist markdown corpus as a source of record, and
an ingest path that reads it instead of Wikipedia. Paste everything below the rule.

---

## Context

Read first:

- `CLAUDE.md`. Invariant 4 (no silent fallback from grounded to ungrounded) and invariant 9
  (provenance comes from what happened, not what was asked for) both bind this task.
- `docs/decisions/0003-chunking-and-passage-ids.md`. **Do not reopen the id scheme.** Note
  its warning that changing the section rule is a breaking change requiring a new ADR.
- `docs/decisions/0004-belief-fallback-and-the-basis-field.md`.
- `docs/decisions/0005-no-named-contemporary-events-in-theorist-output.md`.
- `src/artsoc/ingest.py`, `src/artsoc/retrieval.py`, `data/corpora/README.md`.

Today every persona's corpus comes from Wikipedia via `fetch_wikipedia`, plus Semantic
Scholar abstracts. `ingest.py`'s docstring states correctly that Wikipedia is a tertiary
source — an article *about* a theorist, not that theorist's writing — and cannot support the
held-out-writings check the approach doc claims as this population's advantage.

Six markdown documents now exist covering four of the twelve registry personas: two Brodie,
two Schelling, one Kahn, one Wohlstetter. They are project-written summaries of specific
publications, with a header block, an Argument section, a hand-authored `Claims as stated`
list, a Verify section and a Source pointer. They are secondary material, not primary text,
and each carries a `confidence` field saying so.

This task makes those documents a real corpus source. It does not build the claim index or
the codebook — see Out of scope.

## Task

### 1. Two directories, not one

```
data/corpora-src/<persona_id>/<slug>.md      COMMITTED   — source of record
data/corpora/<persona_id>/{chunks,beliefs}.jsonl, manifest.json   GITIGNORED — artefacts
```

`.gitignore` currently has `data/corpora/*` with only `.gitkeep` exempted. Do not add
exceptions to that rule — add the new directory outside it. One directory is input you
wrote; the other is output the pipeline can rebuild.

`ingest.py:442` already resolves the store as `(corpus_root or CORPUS_ROOT) / persona.persona_id`,
so the per-persona shape mirrors what exists.

### 2. Move and rename the six documents

`PASSAGE_ID` in `llm.py:88` is `\[([A-Za-z0-9_]+:[A-Za-z0-9_]+:\d+)\]`. **Hyphens are not
permitted in the slug.** Derive `source_slug` from the filename stem so the mapping is
inspectable rather than configured, which means the stems must be underscore-only. A
malformed id is invisible to the model, can never be cited, and citation integrity would
read a clean zero from an inert path — the silent-success failure ADR 0003 was written
against.

Drop the persona prefix from filenames; the directory supplies it. Otherwise the persona
appears twice in every id.

| From | To |
|---|---|
| `brodie-1946-absolute-weapon.md` | `brodie/absolute_weapon_1946.md` |
| `brodie-1959-strategy-missile-age.md` | `brodie/strategy_missile_age_1959.md` |
| `wohlstetter-1959-delicate-balance.md` | `wohlstetter/delicate_balance_1959.md` |
| `kahn-1960-on-thermonuclear-war.md` | `kahn/on_thermonuclear_war_1960.md` |
| `schelling-1958-reciprocal-fear.md` | `schelling/reciprocal_fear_1958.md` |
| `schelling-1960-strategy-of-conflict.md` | `schelling/strategy_of_conflict_1960.md` |

`_MANIFEST.md` is not a persona document and must not be ingested. Move it to
`docs/corpora/theorists-manifest.md`.

Add a validation test asserting every stem under `corpora-src/` matches `[A-Za-z0-9_]+`.

### 3. Source of record is declared, never inferred

Add `corpus_source: markdown | wikipedia` to each registry persona. Explicit, because
inferring it from directory existence is a silent fallback by another name.

- `markdown` with no files under `corpora-src/<persona_id>/` → **raise**. Not a warning,
  not an empty store, not a Wikipedia fetch. Invariant 4.
- `wikipedia` keeps the current path unchanged.
- The Wikipedia and Semantic Scholar fetchers must be **unreachable** from a markdown
  ingest. Assert it with a test that injects a fetcher raising on call, runs a markdown
  ingest, and expects success.

After this change four personas are `markdown` and eight are `wikipedia`, so a single run
mixes tiers. That is acceptable and must be visible — see 5.

### 4. Markdown section rule — ADR 0006

**ADR 0005 is taken.** This is 0006.

Keep unchanged from ADR 0003: the ~150-word target, whole-paragraph grouping, never
crossing a section boundary, never splitting mid-paragraph, whitespace-normalised hashing,
the content-key derivation, and the decimal rendering forced by `PASSAGE_ID`'s `\d+`.

Vary only the header pattern: `^## ` instead of `== Section ==`.

**Which parts are chunked, decided:**

| Part | Chunked | Reason |
|---|---|---|
| `---` header block | No — carried as chunk metadata | A citation to `confidence: general` attests to nothing. `date`, `confidence`, `work`, `type` and `availability_1962` travel with every chunk from the file so provenance is available without being citable. |
| `# ` H1 title | No — document title metadata | |
| `## Argument` | **Yes**, as prose | The retrievable substance. |
| `## Claims as stated` | **Yes**, own chunk(s), section name retained | Human-authored propositions. Proposition-shaped text matches proposition-shaped questions, which mitigates BM25's vocabulary-mismatch weakness. The section name must reach the prompt via `format_passage` so a persona citing one knows it is citing a claims list, not an argued passage. |
| `## Verify` | No | Project metadata about doubt. A persona retrieving "Verify: everything above" would produce nonsense and cite it. |
| `## Source` | No — retained in the manifest | A pointer, not content. |

Because `source_slug` is per-publication rather than `wikipedia`, all ids from this path are
new and nothing existing breaks. Say so in the ADR so the next reader is not alarmed by ADR
0003's re-chunking warning.

### 5. `corpus_tier` on the record

`RunRecord.grounded` currently goes true for a Wikipedia run. After this change it goes true
for two different kinds of source in the same run, so it no longer distinguishes them.

Add `corpus_tier`, taken from the retriever that produced the text, per invariant 9:

| Value | Meaning |
|---|---|
| `primary` | the subject's own writing. Nothing produces this yet. |
| `summary` | project-written summaries (`corpora-src` markdown) |
| `encyclopedia` | Wikipedia |
| `belief` | ADR 0004 belief store only |
| `stub` | registry `corpus_notes` |
| `mixed` | more than one tier contributed to a run |
| `none` | no retrieval |

Surface it in `metrics` beside `grounded`, and in the frontend `ProvenanceBanner`. A
reviewer reading `grounded: true` must be able to tell what it was grounded in without
opening the manifest.

### 6. No belief generation for markdown personas

Skip it. `## Claims as stated` is a hand-authored proposition list and is better than a
model-generated belief store on every axis that matters: it has human provenance, it is
inspectable without running the system, and it is already proposition-shaped so it retrieves
on position vocabulary.

Consequences to accept and document: `basis` will never be `beliefs` for these four
personas, and their decline rate may be higher than the Wikipedia personas'. Both are
honest. Do not add a belief store to close the gap.

ADR 0004's fallback stays in place for the `wikipedia` personas, unchanged.

Note in ADR 0006 that this pre-figures a claim-index design under consideration, and that
the claims section is deliberately chunked separately so that design can index it later
without re-chunking. Do not build that design now.

## Hard constraints

- **Never edit an existing test to make a change pass.** 283 pass and 2 skip; the number
  should only go up.
- **No silent fallback of any kind** — not markdown to Wikipedia, not markdown to stub, not
  markdown to beliefs.
- **Do not reopen ADR 0003's id scheme**, content-key derivation, or decimal rendering.
- **Do not touch `schema.RUNG`**, the action space, or the rung path.
- **Do not weaken the access matrix.** Theorists get a decontextualised question and their
  own record.
- **Never commit primary text.** These documents are summaries. A primary-text corpus, if
  added later, stays gitignored and its licensing is checked first.
- **Placeholders keep declaring themselves.** Every document's `confidence` field is
  accurate. Do not upgrade one, and do not fill a Verify section.
- **ADR 0005 applies** to any model call this task introduces.

## Ask before

- Any dependency.
- Any change to `schema.py` or `RunRecord` beyond adding `corpus_tier`.
- Any change to `PASSAGE_ID` or the id format.
- Rewriting the content of the six documents. They are inputs, not code.

## Out of scope

The claim index and the codebook — both under design, neither settled. The ExComm 1962
persona set. Ablation arms over ideas. Embeddings or any retrieval-mode change; BM25 stays.
Batches 2 and 3 of the manifest. Removing Wikipedia from the eight personas that still use
it.

## Deliverable for this turn

A plan only. No files written.

1. File-by-file changes, marked new, moved or modified.
2. The ADR 0006 draft recording the section rule and the chunked-parts table above as
   decisions. Flag disagreement in the plan rather than varying silently.
3. How `corpus_source: markdown` is prevented from reaching a fetcher, and the exact test
   that asserts it.
4. Where the no-belief-generation decision is documented for a future reader.
5. New tests, each stated as the invariant it protects.
6. Anything in this specification you think is wrong — flagged, not changed.
7. Confirmation that `chunks.jsonl` from a markdown ingest is readable by the existing
   `retrieval._STORE_FILES` path without changes, or what has to change if not.
8. Open questions.

Order the work so `make test` passes at every intermediate commit. Say so if that is not
achievable and why.