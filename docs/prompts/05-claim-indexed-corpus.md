# Claude Code prompt — claim-indexed markdown corpus

Plan-mode prompt. Replaces fetched-Wikipedia retrieval with a committed per-theorist markdown
corpus, and replaces passage-similarity retrieval with a claim index over an evidence store.
Paste everything below the rule.

---

## Context

Read first:

- `CLAUDE.md`. Invariants 1, 4 and 9 all bind this task.
- `docs/decisions/0003-chunking-and-passage-ids.md`. **Do not reopen the id scheme.** Note
  its warning that a change to the section rule is breaking and needs a new ADR.
- `docs/decisions/0004-belief-fallback-and-the-basis-field.md`. This task **partially
  supersedes** it.
- `docs/decisions/0005-no-named-contemporary-events-in-theorist-output.md`.
- `docs/decisions/0006-courses-of-action.md` — for its `SCHEMA_VERSION` reasoning, which
  applies here.
- `src/artsoc/ingest.py`, `src/artsoc/retrieval.py`, `src/artsoc/agents.py`.

Today a persona's corpus is fetched from Wikipedia plus Semantic Scholar abstracts, chunked,
and retrieved by BM25 over passages, with a belief store as fallback when passage retrieval
returns nothing.

Two problems motivate this change.

**The source is tertiary.** `ingest.py`'s docstring says so: an encyclopedia article *about*
a theorist, not that theorist's writing, and it cannot support the held-out-writings check
the approach doc claims as this population's advantage.

**The retrieval granularity is wrong.** ADR 0004 records that grounded runs hit a 100%
out-of-record rate — retrieval succeeded, twelve of twelve pairs returned valid passages, and
the passages were biography. Questions are position-shaped; prose passages are
argument-shaped; BM25 has to bridge that and does it badly. ADR 0004's response was a second
store consulted on failure. This task fixes the index instead, which removes that fallback's
motivation for the personas it covers.

Six markdown documents now exist for four registry personas — two Brodie, two Schelling, one
Kahn, one Wohlstetter. Each has a `---` header block, a `## Argument` section, a
hand-authored `## Claims as stated` list, a `## Verify` section and a `## Source` pointer.
They are project-written summaries, secondary material, each carrying a `confidence` field.

## Task

### 1. File structure — two directories

```
data/corpora-src/<persona_id>/<slug>.md          COMMITTED   — source of record
data/corpora/<persona_id>/                        GITIGNORED  — build artefacts
    chunks.jsonl      evidence passages
    claims.jsonl      the retrieval index          (new)
    manifest.json
```

`.gitignore` lines 5–6 are `data/corpora/*` and `!data/corpora/.gitkeep`. **Do not add
exceptions to that rule** — put the new directory outside it. One is input you wrote; the
other is output the pipeline can rebuild.

`ingest.py:442` already resolves the store as `(corpus_root or CORPUS_ROOT) /
persona.persona_id`, so the per-persona shape mirrors what exists.

### 2. Move and rename the six documents

`PASSAGE_ID` at `llm.py:88` is `\[([A-Za-z0-9_]+:[A-Za-z0-9_]+:\d+)\]`. **Hyphens are not
permitted in a slug.** Derive `source_slug` from the filename stem so the mapping is
inspectable rather than configured — which means stems must be underscore-only. A malformed
id is invisible to the model, can never be cited, and citation integrity would read a clean
zero from an inert path: the silent-success failure ADR 0003 was written against.

Drop the persona prefix from filenames; the directory supplies it.

| From | To |
|---|---|
| `brodie-1946-absolute-weapon.md` | `brodie/absolute_weapon_1946.md` |
| `brodie-1959-strategy-missile-age.md` | `brodie/strategy_missile_age_1959.md` |
| `wohlstetter-1959-delicate-balance.md` | `wohlstetter/delicate_balance_1959.md` |
| `kahn-1960-on-thermonuclear-war.md` | `kahn/on_thermonuclear_war_1960.md` |
| `schelling-1958-reciprocal-fear.md` | `schelling/reciprocal_fear_1958.md` |
| `schelling-1960-strategy-of-conflict.md` | `schelling/strategy_of_conflict_1960.md` |

`_MANIFEST.md` is not a persona document and must not be ingested — move it to
`docs/corpora/theorists-manifest.md`. Add a test asserting every stem under `corpora-src/`
matches `[A-Za-z0-9_]+`.

### 3. Source of record is declared, never inferred

Add `corpus_source: markdown | wikipedia` to each registry persona. Explicit, because
inferring it from directory existence is a silent fallback under another name.

- `markdown` with no files under `corpora-src/<persona_id>/` → **raise**. Not a warning, not
  an empty store, not a fetch. Invariant 4.
- `wikipedia` keeps the current path unchanged.
- Wikipedia and Semantic Scholar fetchers must be **unreachable** from a markdown ingest.
  Assert with a test that injects a fetcher raising on call, runs a markdown ingest, and
  expects success.

Four personas become `markdown` and eight stay `wikipedia`, so a run mixes tiers. That is
acceptable and must be visible — see §7.

### 4. Markdown chunking — new ADR

**Use the next free ADR number. 0001–0006 are taken, so this is 0007** unless another has
landed since; check `docs/decisions/` rather than trusting this line.

Keep unchanged from ADR 0003: the ~150-word target, whole-paragraph grouping, never crossing
a section boundary, never splitting mid-paragraph, whitespace-normalised hashing, the
content-key derivation, and the decimal rendering forced by `PASSAGE_ID`'s `\d+`. Vary only
the header pattern: `^## ` instead of `== Section ==`.

| Part | Goes to | Reason |
|---|---|---|
| `---` header block | chunk metadata, not chunked | A citation to `confidence: general` attests to nothing. `work`, `date`, `type`, `confidence`, `availability_1962` travel with every chunk from that file. |
| `# ` H1 title | document title metadata | |
| `## Argument` | **`chunks.jsonl`** — evidence | The prose a claim rests on. |
| `## Claims as stated` | **`claims.jsonl`** — one claim per list item | Human-authored propositions. The retrieval index. |
| `## Verify` | dropped | Project metadata about doubt. A persona retrieving "Verify: everything above" would produce nonsense and cite it. |
| `## Source` | manifest only | A pointer, not content. |

Because `source_slug` is per-publication rather than `wikipedia`, every id from this path is
new and nothing existing breaks. Say so in the ADR so the next reader is not alarmed by ADR
0003's re-chunking warning.

### 5. The claim index

**One claim per bullet in `## Claims as stated`.** Do not generate claims with a model — they
are already written, with human provenance, and generating over them would replace an
inspectable artefact with an unverifiable one.

Claim record:

```
claim_id      <persona_id>:<source_slug>:<content_key>   same scheme as a passage
text          the bullet, verbatim
source_slug   the publication it came from
supported_by  [passage_id, ...]  evidence from the SAME document only
group         corroboration group id
```

**Evidence edges are derived, not annotated.** The documents carry no per-claim provenance,
so for each claim take the top-k BM25 matches among `chunks.jsonl` entries **from the same
`source_slug`**. Same-publication scoping is a hard constraint: a claim from Brodie 1946 must
not draw evidence from Brodie 1959, or the claim is supported by prose the persona wrote
thirteen years later. Record k and the scoring in the manifest so the edges are reproducible
and inspectable.

**Grouping is deterministic for now.** Claims stating the same position across publications
belong in one group so corroboration depth is readable. Use normalised-token Jaccard above a
threshold recorded in the manifest. **Do not merge claim text** — merging rewrites text,
which changes the content key, which breaks ADR 0003's guarantee. Keep every claim's own id
and add the `group` field. Members are what gets cited; the group is only an organising
handle, so its id need not be content-addressed.

A model-assisted merge pass is a later option and is out of scope. Say in the plan what
recall you expect Jaccard alone to achieve.

### 6. Retrieval

Two stages, replacing passage-similarity retrieval for `markdown` personas:

```
question
  → BM25 over claims.jsonl → top-k claim groups above threshold
  → no hit → decline (out_of_record)
  → hit → hydrate: claim text + each supported_by passage's text
  → prompt receives the claim and its evidence, nothing else
  → persona must cite ≥1 id; verification checks against exactly what was shown
```

Two consequences to implement deliberately:

**The decline decision changes meaning.** It stops being "no passage shared enough terms with
the question" and becomes "this theorist argued nothing relevant." That is the escape hatch
ADR 0004 was reaching for. Retire `retrieval_belief_min_terms` for these personas and add a
claim-match threshold; keep the existing knobs for `wikipedia` personas.

**Citation verification must accept both id types.** A persona may cite the claim or the
evidence. `retrieval._STORE_FILES` at line 333 is `("chunks.jsonl", "beliefs.jsonl")` and
needs `claims.jsonl` added, since a citation names an id without saying which store it came
from.

### 7. No belief generation for markdown personas

Skip it entirely. The claims list is hand-authored, inspectable without running the system,
and already proposition-shaped. A generated belief store would be strictly worse.

`basis` gains a `claims` value. For markdown personas it is `claims` or `none`, never
`beliefs`. ADR 0004's fallback stays intact for `wikipedia` personas.

**ADR 0004's diagnostic needs replacing for these personas.** Its warning is a low decline
rate together with most positions resting on beliefs rather than sources — meaningless when
every claim has evidence by construction. The replacement is **corroboration depth**: how
many distinct `source_slug`s appear in the matched claim's group. Single-source claims are
weaker than claims a theorist argued across three works. Surface it in `metrics`.

The new ADR must state plainly which parts of 0004 it supersedes and which remain in force.

### 8. `corpus_tier` on the record

`RunRecord.grounded` currently goes true for a Wikipedia run and would go true for two
different source kinds in one run after this change. Add `corpus_tier`, taken from the
retriever that produced the text, per invariant 9:

`primary` (nothing produces this yet) · `summary` (markdown) · `encyclopedia` (Wikipedia) ·
`belief` · `stub` · `mixed` · `none`

Surface it in `metrics` beside `grounded`, and in the frontend `ProvenanceBanner`. A reviewer
reading `grounded: true` must be able to tell what it was grounded in without opening the
manifest.

### 9. `SCHEMA_VERSION` → 1.2.0

ADR 0006 bumped to 1.1.0 on the reasoning that changing the mechanism generating `action`
warrants a bump while additive observability fields do not. This changes what the theorist
sees, which changes opinions, the brief, the COAs and therefore the action. Bump, and say why
in the ADR.

### 10. Generalise the marker-unwrap guard

Marker syntax has now leaked back from the model twice — `[[WHO:...]]` in `Advisor.select`,
then `[[OPINION:...]]` and `[[ACTION:...]]` in COA citations, the second found by live
verification rather than by the suite. Two independent occurrences of one defect class is a
pattern.

This task introduces new marker-wrapped content (claims and their evidence). Apply
`_unwrap_marker` and `_strip_inline_markers` from `agents.py` to whatever comes back from any
prompt that shows a `[[X:...]]` wrapper, as a shared guard rather than per-site. Add a mock
response that echoes a marker, so the suite reproduces the failure mode that only live
running has caught so far.

## Hard constraints

- **Never edit an existing test to make a change pass.** 335 pass and 2 skip; the number
  should only go up.
- **No silent fallback of any kind** — not markdown to Wikipedia, not markdown to stub, not
  markdown to beliefs, not a claim to a bare passage search.
- **Do not reopen ADR 0003's id scheme**, content-key derivation, or decimal rendering.
- **Do not merge claim text.**
- **Do not weaken the access matrix.** Theorists get a decontextualised question and their own
  record. ADR 0006's rule that the Advisor cites by id and never quotes a theorist still
  holds.
- **Do not touch `schema.RUNG`**, the action space, or the rung path.
- **Never commit primary text.** These are summaries. A primary-text corpus, if added later,
  stays gitignored and its licensing is checked first.
- **Placeholders keep declaring themselves.** Every `confidence` field is accurate. Do not
  upgrade one and do not fill a Verify section.
- **ADR 0005 applies** to any model call this task introduces.

## Ask before

- Any dependency. In particular: no embedding model. BM25 stays, and dense retrieval is a
  later arm to be measured, not assumed.
- Any change to `schema.py` beyond `corpus_tier`, the `basis` value and the version bump.
- Any change to `PASSAGE_ID` or the id format.
- A model-assisted claim merge pass.
- Rewriting the content of the six documents. They are inputs, not code.

## Out of scope

Dimension coding and the codebook — under design, not settled. This task builds the claim
index; positions on dimensions come later, and the claims must not be coded onto a scheme
now, because the agreed sequence is open extraction, then codebook construction from what the
extraction finds, then frozen application.

Also out: the ExComm 1962 persona set; idea-ablation arms; embeddings; batches 2 and 3 of the
corpus manifest; removing Wikipedia from the eight personas still using it.

## Deliverable for this turn

A plan only. No files written.

1. File-by-file changes, marked new, moved or modified.
2. The ADR draft, at the next free number, recording the section rule, the chunked-parts
   table, the claim record shape, the evidence-edge derivation, and exactly which parts of
   ADR 0004 are superseded.
3. How `corpus_source: markdown` is prevented from reaching a fetcher, and the test that
   asserts it.
4. Expected recall of Jaccard-only grouping, and what it will miss.
5. New tests, each stated as the invariant it protects — including one that a claim's
   `supported_by` never crosses `source_slug`.
6. Anything in this specification you think is wrong — flagged, not changed.
7. Whether `retrieval` can read `claims.jsonl` through the existing `_STORE_FILES` path with
   only that tuple changed, or what else has to move.
8. Open questions.

Order the work so `make test` passes at every intermediate commit. Say so if that is not
achievable and why.