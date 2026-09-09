# ADR 0007 — A claim-indexed markdown corpus, and what replaces the belief fallback

Date: 2026-09-09
Status: accepted
Partially supersedes: 0004 — see "What of ADR 0004 stands" below. No previous ADR has
carried supersession metadata; this one does because the change it records is confined to
one class of persona and it would otherwise be impossible to tell which of 0004's rules
still apply to which run.

## Context

Two problems motivated this change, and they are the same problem seen from opposite ends.

**The source was tertiary.** `ingest.py`'s docstring already said so: an encyclopedia
article *about* a theorist, not that theorist's writing. It cannot support the
held-out-writings check `docs/approach/` claims as this population's advantage.

**The retrieval granularity was wrong.** ADR 0004 records a grounded run hitting a 100%
out-of-record rate with retrieval working perfectly — twelve of twelve persona-question
pairs returned real passages with valid ids, and the passages were biography. Questions are
position-shaped. Prose passages are argument-shaped. BM25 was being asked to bridge that
gap and did it badly.

ADR 0004's answer was a second store, consulted when the first returned nothing. That was
the right move given a passage index, but it treated the symptom: it added somewhere else to
look rather than making the first place look right. This change fixes the index instead,
which removes that fallback's motivation for the personas it covers.

The new source of record is a committed set of project-written markdown documents, one per
publication, each carrying a hand-authored `## Claims as stated` list. Those claims are the
retrieval index; the `## Argument` prose is the evidence hydrated beneath whichever claim
matched.

**These documents are secondary material and say so.** They are our account of what a
publication argued, not the publication. Every one carries a `confidence` field and that
field is accurate. This is a better tier than an encyclopedia article about the author; it
is not primary text, and no claim resting on it may be described as though it were.

## Decision

### The section rule, and the one splitter that had to change

`^## ` replaces `== Section ==`. Everything else from ADR 0003 is unchanged and is not
reopened: the ~150-word target, whole-paragraph grouping, never crossing a section boundary,
never splitting mid-paragraph, whitespace-normalised hashing, the content-key derivation,
and the decimal rendering forced by `PASSAGE_ID`'s `\d+`.

**The paragraph splitter differs, in order to preserve the rule rather than to vary it.**
`chunk_text` splits on a single `\n`, because a Wikipedia `explaintext` extract puts one
paragraph per line. Hand-written markdown is hard-wrapped, so applying that splitter to it
would treat every wrapped line as a paragraph and let a group boundary fall mid-sentence —
which is ADR 0003's rule inverted, not kept. `chunk_markdown` therefore splits on blank
lines. The rule about what a chunk may contain lives in one function, `group_paragraphs`,
which both pipelines call; only the splitters differ, and a test asserts neither pipeline
reimplements the rule.

### Which parts of a document become what

| Part | Goes to | Reason |
|---|---|---|
| `---` header block | chunk and claim metadata, never content | A citation to `confidence: general` attests to nothing. `work`, `date`, `type`, `confidence` and `availability_1962` travel with every record from that file so provenance is available without being citable. |
| `# ` H1 title | document title in the manifest | |
| `## Argument` | `chunks.jsonl` — evidence | The prose a claim rests on. |
| `## Claims as stated` | `claims.jsonl` — the retrieval index | Hand-authored propositions, one per bullet. |
| `## Verify` | dropped | Project metadata about doubt. A persona retrieving "Verify: everything above" would produce nonsense and cite it. |
| `## Source` | manifest only | A pointer, not content, so it can never be retrieved or cited as evidence. |

**Every id from this path is new, and nothing existing breaks.** `source_slug` is the
publication rather than `wikipedia`, so no id this pipeline emits can collide with one
already stored. ADR 0003's warning that re-chunking invalidates every citation and the whole
response cache is about re-chunking an existing source; it does not apply to adding one.

`source_slug` is the filename stem, so the mapping from file to citation is inspectable
rather than configured. Stems must match `[A-Za-z0-9_]+`, because `PASSAGE_ID` permits no
hyphens: a malformed id is invisible to the model, can never be cited, and citation
integrity would read a clean zero off a path nothing could ever cite. `artsoc ingest`
refuses a bad stem and a test asserts the rule over the whole directory.

### The claim record

```
passage_id    <persona_id>:<source_slug>:<content_key>   ADR 0003's scheme, unchanged
section       "claim"
text          the bullet, verbatim, whitespace-normalised
source_slug   the publication it came from
supported_by  [passage_id, ...]  evidence from the SAME document only
group         corroboration group id
```

**The on-disk key is `passage_id` and not `claim_id`, deliberately.**
`retrieval.resolve_passages` reads `passage_id`, `section` and `text`. A claim stored under
a different key would resolve to nothing, and every cited claim would render to an analyst
as unresolvable — read as a hallucinated citation when it was a real one. That is exactly
the silent-success failure ADR 0003 was written against, reached by a different route.
`claim_id` is the name in this document; `passage_id` is the name on disk. Adding
`claims.jsonl` to `retrieval._STORE_FILES` was then the only change resolution needed.

**Claims are never generated by a model.** They are already written, with human provenance,
and generating over them would replace an inspectable artefact with an unverifiable one —
with nothing left to check the generation against. ADR 0005's constraint on model calls
therefore does not arise on this path: it makes none.

### Evidence edges are derived, not annotated

The documents carry no per-claim provenance, so each claim takes the top-3 BM25 matches
among the `## Argument` chunks **of its own publication**. `k`, the scoring and the floor
are recorded in the manifest so the edges are reproducible and arguable-with.

**Same-publication scoping is a hard constraint, not a default.** A claim from a 1946 work
supported by prose from a 1959 one is a claim supported by an argument its author had not
yet made. The test that holds this is non-vacuous by construction: the fixtures state the
same claim in two works and the earlier passage outscores the later one for it, so dropping
the scoping moves the edge and the test fails.

A claim its own document cannot support raises at ingest, naming every offender at once. A
claim is shown to a persona together with the prose arguing it, so a claim with no evidence
would be presented as grounded when it is not.

`bm25_rank` is now one function shared by ingest and retrieval. Two implementations would
let the edges recorded at build time disagree with the ranking applied at run time, and the
disagreement would be invisible in the output.

### Grouping is deterministic, and text is never merged

Normalised-token Jaccard at 0.45, single-link connected components, iterated in sorted id
order with group ids numbered by each component's smallest member. The threshold is in the
manifest.

**Claim text is never merged.** Merging would rewrite text, which changes the content key,
which breaks ADR 0003's guarantee that the same text yields the same id forever. Every claim
keeps its own id and its own wording. The group is an organising handle over them, so its id
need not be content-addressed; the members are what gets cited.

**A group asserts vocabulary overlap, not agreement.** Jaccard is negation-blind: "a
posture deters" and "a posture does not deter" share every content token and would land in
one group. On a corpus made entirely of position statements that is the live risk, and it is
why corroboration depth is reported as a diagnostic and never as evidence. A model-assisted
merge pass would address it and is deliberately out of scope: it would replace a rule anyone
can check by hand with one nobody can.

### Retrieval: match a position, then hydrate the argument

```
question
  → BM25 over claims.jsonl, filtered by shared content terms
  → top-k claim GROUPS above the floor
  → no hit → decline (out_of_record)
  → hit → every member claim, each followed by its supported_by passages
  → persona cites the claim, the evidence, or both
```

Selection is over groups rather than claims so that a position argued in two publications is
one hit, and every member of a selected group is rendered. That is what makes corroboration
visible to the persona and citable by it rather than merely counted by the host. All ids are
single-bracketed, so `PASSAGE_ID` finds both kinds and `verify_citations` — which checks
against the rendered block, not a store — needed no change.

**The decline changes meaning.** It stops being "no passage shared enough terms with the
question" and becomes "this theorist argued nothing relevant." That is the escape hatch ADR
0004 was reaching for.

The block gets its own framing, distinct from both existing ones. A belief was a position
with nothing behind it; a source passage was prose with no position attached. A claim is
neither, and the instruction has to say both ids are citable — otherwise a persona cites
only the evidence and the position it actually answered from goes unrecorded.

`retrieval_claim_min_terms` and `retrieval_claim_top_k` are arm-configurable, per invariant
5. `CLAIM_EVIDENCE_K` and `CLAIM_GROUP_JACCARD` are not: they are baked into the artefact
and changing either requires a re-ingest rather than a different arm, exactly like
`TARGET_WORDS`. Both are recorded in the manifest.

**The thresholds are reasoned, not calibrated.** `base.yaml`'s existing table came from a
live sweep over the real corpora. There is no equivalent for the claim index yet, and
`base.yaml` says so: no decline rate from this path is comparable with that table until
there is.

### No belief generation for markdown personas

Skipped entirely. `## Claims as stated` is hand-authored, inspectable without running the
system, and already proposition-shaped. A generated belief store would be worse on every
axis that matters, and consulting one as a fallback would mean a run resting on generated
text while reporting a hand-authored index.

`basis` gains `claims`. For a markdown persona it is `claims` or `none`, never `beliefs`. A
markdown store with no `claims.jsonl` raises rather than degrading to a bare passage search:
a claim-indexed run and a passage-indexed one answer different questions, and the record
could not tell them apart afterwards.

### The source of record is declared, never inferred

`corpus_source: markdown | wikipedia` on every registry persona. Inferring it from whether a
source directory happens to exist is a silent fallback under another name — a persona whose
documents had not been added yet would quietly be built from an encyclopedia article and
still reported as grounded.

The registry declares and the manifest confirms. `CorpusRetriever` checks one against the
other and raises on disagreement, so a store built from something other than what is
declared cannot serve. A persona declared `markdown` with nothing ingested has no manifest
to confirm it and raises through the same check, which is invariant 4's required behaviour
reached structurally rather than by a separate existence test. Manifests written before this
key existed read as `wikipedia`, which is not an inference: no code that could write any
other kind of store existed before the key did.

`ingest_markdown_persona` takes no fetcher and no model client at all. Reaching one requires
adding a parameter and a call rather than forgetting a guard — the same shape as
`PerceivedEvent` having no `ground_truth_detail` field.

### `corpus_tier` on the record

`RunRecord.grounded` went true for two different kinds of source the moment one panel could
mix them, so it stopped distinguishing them. `corpus_tier` is taken from the retriever that
produced the text, per invariant 9: `primary` (nothing produces this yet) · `summary` ·
`encyclopedia` · `belief` · `stub` · `mixed` · `none`. A reviewer reading `grounded: true`
must be able to tell what it was grounded in without opening a manifest.

It cannot be a class attribute the way `grounded` is, because a run is a fact rather than a
declaration: the retriever accumulates what it actually served and reduces it. `sim.run_once`
builds a retriever per replication, so nothing bleeds between records.

**Known imprecision:** Semantic Scholar and OpenAlex abstracts live in `chunks.jsonl`
alongside the encyclopedia article and are folded into `encyclopedia`. An abstract of the
theorist's own paper is not really an encyclopedia entry. Separating them needs a tier value
this ADR does not define, so it is recorded here rather than guessed at.

### Corroboration depth replaces ADR 0004's diagnostic, for these personas

ADR 0004's warning is a low decline rate together with most positions resting on beliefs.
That is meaningless where every claim carries evidence by construction: `beliefs_share` goes
to zero for a markdown panel whatever the panel is doing.

The replacement is **corroboration depth** — how many distinct publications the matched
claim's group spans. A position found in one work is weaker than one a theorist argued
across three. `TheoristOpinion.corroboration` records it, from the retriever and never from
the model, and `metrics` warns `SINGLE-SOURCE POSITIONS` when most claim-based positions
rest on one publication.

**It is a diagnostic about the corpus before it is one about the panel, and at present
mostly the former.** With one or two documents per theorist almost every group is a
singleton, so a depth near 1.0 says the corpus is thin, not that the theorists were
unsupported. Combined with negation-blindness above, this number must not be presented as
evidence of agreement. It becomes informative as the corpus grows past its first batch.

### `SCHEMA_VERSION` → 1.2.0

Bumped on ADR 0006's reasoning rather than treated as the additive change `corpus_tier` and
`corroboration` resemble. What a theorist is shown changes, which changes its opinion, which
changes the brief and the courses of action, and therefore `action`. A record from before
this version cannot be reproduced by re-running the same config and seed against current
code. Both new fields are defaulted, so records already in `out/` still load — a bump that
orphaned prior records would make the bump itself unauditable.

## What of ADR 0004 stands

**Superseded, for `markdown` personas only:**

- The belief store as a fallback. Not consulted, not written, not generated.
- The `beliefs` basis value, which cannot occur on this path.
- The replacement diagnostic, which becomes corroboration depth for the reason above.

**In force, unchanged, for the eight `wikipedia` personas:** the sources-then-beliefs
fallback order, the shared relevance filter, `retrieval_belief_min_terms` and its derivation,
`_BELIEF_FRAMING`, and the `POSITIONS REST ON BELIEF` warning. None of that code changed.

**In force for both:** `basis` is recorded on every opinion and comes from the retriever
rather than the model; `out_of_record` keeps its meaning of "the persona stated no
position"; and a passage's relevance is decided by shared content terms before its score
means anything.

## Consequences

A run now mixes tiers — four markdown personas beside eight Wikipedia ones, once the
documents land. That is acceptable and is visible in `corpus_tier`, but a contrast between
two arms is only clean if both mixed them the same way, which `MIXED CORPUS TIERS` warns
about. Moving the remaining eight is separate work.

Ingest for a markdown persona costs nothing: no network, no model, no rate limiting. It is
therefore always rebuilt rather than reused, which also means an edited document can never
be silently served from a stale store. `load_manifest` checks markdown stores for
`claims.jsonl` instead of `beliefs.jsonl`, which they never have — without that branch every
markdown store would look permanently interrupted.

The marker-unwrap guard was generalised in the same body of work. This change shows
marker-wrapped content to a model in a new place, and the defect had already occurred twice
at two sites, each fixed where it was found. It is now one guard applied at every parse
site, with the shared mock echoing markers at a low rate so the ordinary suite is exposed to
the failure mode that had only ever been caught by live running.

## Alternatives rejected

**Model-generated claims.** Replaces an inspectable artefact with an unverifiable one, and
leaves nothing to check the generation against. The claims are already written by hand,
which is the whole reason they are trustworthy as an index.

**Merging claim text across publications.** Rewrites text, changes the content key, breaks
ADR 0003. The group carries the corroboration instead, and both statements keep their ids.

**Cross-publication evidence edges.** Would let a claim be supported by prose its author
wrote thirteen years later, which is a stronger-looking claim about a weaker-supported one.

**Embeddings for the claim match.** A later arm to be measured, not an assumption to build
in. BM25 stays, and any dense retriever is a contrast to run rather than a default to adopt.

**Inferring `corpus_source` from directory existence.** A silent fallback under another
name, and the one this project is least able to detect afterwards.

**Keeping the belief fallback behind the claim index.** Would mean a run resting on
generated text while reporting a hand-authored index, and the record could not distinguish
them. If a claim index does not cover a question, declining is the correct answer and is now
the informative one.
