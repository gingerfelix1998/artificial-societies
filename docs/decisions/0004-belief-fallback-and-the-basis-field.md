# ADR 0004 — The belief fallback, and what replaces the out-of-record diagnostic

Date: 2026-09-06
Status: accepted — superseded in practice by ADR 0007

> **Status update, 2026-09-10.** ADR 0007 introduced the claim index for `markdown`
> personas, and all twelve personas have since been moved to `markdown`. The belief
> fallback described below is therefore not exercised by any persona: `basis` is never
> `beliefs`, `beliefs_share` is structurally zero, and the `POSITIONS REST ON BELIEF`
> warning cannot fire. The belief-store code, `_BELIEF_FRAMING`,
> `retrieval_belief_min_terms` and this diagnostic all remain in place for a persona moved
> back to the `wikipedia` pipeline. The live diagnostic is now corroboration depth (ADR
> 0007). The `basis` field and its provenance-from-the-retriever rule are unchanged.

## Context

Grounded runs against Wikipedia corpora produced a **100% out-of-record rate**. Retrieval
was working — twelve of twelve persona-question pairs returned real passages with valid ids
— but the passages were biography. Shown a genuine paragraph from *Arms and Influence*,
the Schelling persona judged it insufficient to state a position, which is the correct
judgement about that text.

A panel where every member declines contributes nothing to the decision. The requirement is
that personas reason from the positions they actually argued, while still declining on
questions outside them.

`CLAUDE.md` constrains how that can be done:

> **A near-zero out-of-record rate is a warning, not a success.** It means the escape hatch
> is not firing and personas are extrapolating past their record.

Anything that lets a persona answer without a source lowers the decline rate by design.
The diagnostic therefore has to be redefined deliberately rather than quietly broken.

## Decision

### A belief store, used only as a fallback

Each persona gets a small set of discrete positions it actually argued, generated at ingest
from that persona's fetched sources and stored in `beliefs.jsonl` with content-addressed
ids (`<persona_id>:belief:<content_key>`, per ADR 0003).

Retrieval consults them **only when source retrieval returns nothing**. A persona with
relevant sources still reasons from sources; the beliefs are what it falls back on when the
corpus does not cover the question.

### Beliefs are scoped, and matched, not asserted

Beliefs are **not** a general worldview injected into every prompt. They are specific
claims, and **the same relevance filter applies to them as to source passages**. A question
that overlaps none of a persona's beliefs retrieves nothing from the belief store either,
and the persona declines.

This is the load-bearing part. A broad creed — "Schelling thought carefully about nuclear
strategy" — would match every question and drive declines to zero. Narrow claims match
narrowly, which is what keeps the escape hatch alive. The generation prompt says so
explicitly, and the tests assert that a non-overlapping question still declines.

### `basis` is recorded on every opinion

`TheoristOpinion.basis` takes `sources`, `beliefs`, or `none`. `out_of_record` keeps its
existing meaning: the persona stated no position.

**The diagnostic that replaces "near-zero declines is a warning" is the combination**: a
low decline rate *together with* most positions resting on `beliefs` rather than `sources`.
That is the condition that actually matters — a panel asserting ideology where it has no
evidence — and it is what `metrics` now warns on. A low decline rate with most positions
resting on sources is a well-grounded panel and should not be warned about.

## Consequences

Citation integrity is unchanged in mechanism and narrower in meaning. `verify_citations`
still refuses any id the persona was not shown, and belief ids are verifiable the same way,
but a citation to a belief attests to a position rather than to a source. `basis` is what
distinguishes them, so it must be read alongside the citation rate.

Ingestion now requires a model. It uses the same backend path as a run, so a mock ingest
produces obviously-fake beliefs and cannot be mistaken for a real one; `tests/conftest.py`
already refuses to construct a live backend, so the suite never generates beliefs over the
network.

The `m1_ungrounded` contrast gets harder to interpret, not easier. M1 personas have no
record and no beliefs, so `baseline` vs `m1_ungrounded` now measures sources *and* beliefs
together against a bare name. Separating them would need a beliefs-only arm, which is not
built here.

## Alternatives rejected

**Always-present creed.** Simplest, and what was first proposed. Rejected because a creed
in every prompt makes the persona answer everything, the decline rate collapses to zero,
and the panel stops being an elicitation of a bounded record at all.

**No `basis` field.** Also simpler, and it would leave the decline rate uninformative: an
answer grounded in a cited passage and one asserted from ideology would be indistinguishable
in the record. That is the failure this project guards against everywhere else.
