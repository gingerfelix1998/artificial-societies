# ADR 0001 — Split persona identity from the question prompt

Date: 2026-09-06
Status: accepted

## Context

`personas.build_persona_prompt` returned a single string containing the persona's
identity, the shared instruction, and — for M2 — the retrieved RECORD block. That string
was used as the **system** prompt for a theorist call.

`llm.MockBackend.complete` dispatches to a per-role handler passing only the **user**
prompt. `_theorist` looks in that user prompt for two things: `NO_RECORD_MARKER`
(`[[CORPUS:none]]`), which tells it nothing was retrieved, and `PASSAGE_ID` matches, which
are the ids it may cite. Neither was ever present, because both lived in the system prompt.

The consequences were silent, not loud:

- The `out_of_record` escape hatch would never fire. `TheoristOpinion.out_of_record` exists
  precisely so that "X held this" stays distinguishable from "a model impersonating X
  generated this", and a rate pinned at zero is the failure mode `CLAUDE.md` warns about:
  *a near-zero out-of-record rate is a warning, not a success*.
- No opinion would ever carry a citation, so the citation-integrity metric would report a
  clean zero — reading as a perfect result rather than as an inert code path.

Both would have passed every test in the suite at the time.

`llm.py`'s module docstring already states the rule this violated:

> Where it needs a structured hint — how many questions to produce, whether a corpus block
> was retrieved — that hint is a marker inside the prompt, not a side channel argument.

## Decision

Split the single builder into two:

- `build_identity_prompt(persona, method)` → the **system** prompt. Who the persona is and
  how it must answer. No record, no question.
- `build_question_prompt(question, record_block, method)` → the **user** prompt. The
  decontextualised question, then the RECORD block with passage ids, or
  `NO_RECORD_MARKER` when retrieval returned nothing.

## Consequences

The access matrix is unchanged. Neither function takes the scenario, the intelligence
brief, or peer opinions, and there is still no parameter through which they could. What
moved is which of the two prompts carries the record, not who may see it.

Caching is unchanged in effect and better in shape. `LLMClient._key` hashes system and
prompt together, so the key still covers identity, question and record. But identity is
now stable across every question a persona answers, which is the natural unit to keep
fixed, while the varying part is isolated in the user prompt.

Two tests in `tests/test_invariants.py` move to the new functions:
`test_m2_without_a_record_signals_the_escape_hatch` and
`test_m1_offers_no_escape_hatch_and_no_record`. Neither invariant changes and neither is
weakened — empty retrieval must still surface the hatch, and M1 must still offer no record
and no hatch. Per `CLAUDE.md`, the commit making this change does nothing else.

## Alternatives rejected

**Make the mock read the system prompt too.** This would avoid touching any test, but it
contradicts `llm.py`'s stated design and would let a future backend disagree with the mock
about where structured hints live. The bug was in the caller, not in the backend.

**Leave it and fix it when real retrieval lands.** Rejected because the two symptoms — no
declines, no citations — both look like success from the outside. A defect that reports
itself as a clean metric should not be left in place.
