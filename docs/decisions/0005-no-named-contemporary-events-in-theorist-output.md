# ADR 0005 — No named real-world contemporary events in theorist output

Date: 2026-09-08
Status: accepted

## Context

A live run produced this from the Posen persona:

> "Defensive reinforcement becomes credible when it demonstrates capability matching to
> specific territorial defense (as shown by Ukraine's 2022 posture) rather than
> power-projection capacity."

Traced to source. Not a hallucination: Posen is a real, currently-active scholar who
published *"Putin's Preventive War: The 2022 Invasion of Ukraine"* in *International
Security* in 2025, and `ingest.generate_beliefs` faithfully summarised his genuine recent
argument — including the real case he used as his own evidence — into two of his twelve
stored beliefs:

```
"The Russian invasion of Ukraine in 2022 was a preventive war aimed at forestalling
NATO membership and the placement of nuclear-armed missiles near Russian territory."

"A NATO force of ten brigades reinforcing Poland's fourteen brigades would create a
deterrent comparable to Ukraine's successful defensive posture in 2022."
```

A scan of every other persona's stored beliefs (`data/corpora/*/beliefs.jsonl`) found
nothing else. Four other apparent year matches (george, jervis, sagan, wohlstetter) were
confirmed to be coincidental digits inside content-hash passage ids, not real content. The
defect is isolated to Posen today.

It is not isolated in mechanism. Several personas in the panel are real, currently-active
scholars — Sagan, Tannenwald, Blair and Freedman all publish today — and their belief
stores are built from whatever Semantic Scholar returns as their most-cited recent papers.
Nothing stopped this before Posen and nothing stops it happening again on the next
`refresh=True` re-ingest for any of them.

### Why this is a defect and not merely an oddity

The scenario is anonymised on purpose — "Nation A" and "Nation B" — specifically so a
theorist's answer stays at the level of abstract theory (`docs/framework/design.md`). A
theorist naming a real, dated conflict as its evidence breaks that fiction the moment the
sentence reaches the Advisor's brief and the President's decision: a reader can map the
fictional scenario onto the named real one, which is exactly the historical-outcome
leakage the anonymisation exists to prevent. `docs/prompts/improvements-log.md` already
named this territory as backlog #9, "parametric leakage" — this is that concern arriving
early and concretely rather than staying theoretical.

## Decision

**Theorist output must stay at the level of theoretical mechanism.** No answer may name a
specific real country, war, or dated contemporary event as its evidence, whether the
position rests on a cited source passage or an ungrounded belief. What is preserved is the
argument itself — "a reinforcement force sized to the defender's own territorial
requirement is a more credible deterrent than a power-projection force" is real, grounded
content and stays exactly as strong; only the real-world proper-noun anchor is stripped.

**The constraint covers both the sources path and the beliefs path, not just beliefs.** A
citation to Posen's real, attributed 2025 paper is defensible on its own terms — it is an
accurate representation of published work with a verifiable id. But the scenario's fiction
breaks the same way once the sentence is inside the President's brief regardless of which
path produced it, so one instruction applies everywhere rather than two separate policies
that would need to stay in sync.

**Enforcement is a prompt instruction, fixed at the source, with no output scanning.**
Added in two places:

- `personas._SHARED_INSTRUCTION`, reached by every theorist call through
  `build_identity_prompt` regardless of method or basis. One point of leverage covering
  both paths, because both route through the same identity prompt.
- `ingest.BELIEF_INSTRUCTION`, so newly generated beliefs come out already abstract rather
  than needing to be caught afterwards.

No blocklist and no retry loop. `President.query` already has a bounded-retry guard
(`assert_decontextualised`) against a comparable failure, but that guard works because
`forbidden_tokens` is derived from the actual scenario — a small, enumerable, checkable
list. There is no equivalent finite list of "every real contemporary conflict a model might
reach for"; a blocklist attempting one would be a second, weaker mechanism doing the job a
clear instruction already does, and would need constant maintenance as new events occur.

**Posen's two contaminated beliefs are regenerated**, along with the rest of the panel's,
so the fix is confirmed against every currently-active scholar in the panel rather than
patched by hand for one persona.

## Consequences

Regenerating a belief changes its content-addressed id (ADR 0003): a rebuild from different
text is, correctly, a different passage. Any past citation to Posen's two old belief ids
becomes unverifiable. Accepted here because `out/` and `.cache/` hold only smoke-test
records to date and nothing depends on the old ids. Recorded so the next time a
regeneration is needed for a similar reason, the trade-off is a deliberate, named pattern
rather than a surprise discovered mid-change.

The instruction is advisory, not enforced. A model that ignores it produces the same class
of defect this ADR fixes, undetected until read. That gap is real and is why backlog #9
proposes a leakage probe; this change does not build one, per the decision to enforce at
the prompt only.

## Alternatives rejected

**Restrict the constraint to ungrounded beliefs only, leaving cited sources alone.**
Rejected because the scenario's fiction is broken by the sentence reaching the President's
brief, not by whether the sentence happened to carry a citation. Two policies that both
need to prevent the same outcome is more to keep in sync than one.

**A blocklist-and-retry scan over opinion text**, mirroring `assert_decontextualised`.
Declined for this change. `forbidden_tokens` works because the scenario supplies a finite,
derivable list; there is no equivalent source for "every real contemporary event," so a
blocklist would always be incomplete and would need ongoing maintenance the other guards in
this project do not require. Left as the natural next step if the prompt instruction proves
insufficient in practice.

**Regenerate only Posen.** Rejected because the defect is a property of the belief-
generation prompt, not of one persona's corpus. Confirming the fix against the whole panel
costs about twelve Haiku calls and is the only way to know it actually holds for the other
currently-active scholars most likely to reproduce it.
