# The escalation ladder

How the primary metric is constructed, why it is grounded in Kahn's ladder, and what the
resulting scale does and does not license.

Status: the band structure is corroborated in outline by multiple secondary treatments.
Individual rung numbers are marked `UNVERIFIED` below until checked against the primary
text, in the same style as `data/society/us_1962/strata.yaml`.

---

## The problem this solves

The President selects exactly one `ActionType` from a closed set of fifteen. Scoring that
choice requires an ordering, and until now the ordering was the project's own: an eight-level
table with a nuclear threshold at six, both chosen by us. That is defensible as a design
decision and indefensible as a measurement instrument. Two objections follow immediately.
First, the spacing between levels is an invention, so any statistic that treats the scale as
interval — a mean, a linear model — is reading structure that was assumed rather than
established. Second, the location of the nuclear threshold was a judgement with no external
warrant, and it is the single most consequential number in the project.

Grounding the scale in a published ladder answers the second objection outright and clarifies
exactly what remains true of the first.

## Why Kahn

Herman Kahn, *On Escalation: Metaphors and Scenarios* (Praeger, 1965; repr. Transaction,
2010). Kahn groups forty-four rungs into seven units, bordered below by a pre-escalation
stage and above by an aftermath stage, and separates the units by named thresholds. He also
offered an alternative image — an elevator in a seven-floor department store, each floor
offering options of varying intensity — which puts the emphasis where we need it: on the
thresholds between units rather than on distances between adjacent rungs.

Three reasons for Kahn over the alternatives.

**Construct validity for this action space.** Kahn's lower units are written out of the
crisis-manoeuvring vocabulary the fifteen actions are drawn from: hardening of positions,
shows of force, mobilisation, readiness status, harassment. A scenario turning on mobile
missile dispersal in 1962 sits squarely in that register. Morgan et al., *Dangerous
Thresholds* (RAND, 2008) is a good framework built on threshold logic rather than a rung
sequence, but its cases are regional and post-Cold-War and its concerns include some that did
not exist in 1962. It is retained as a robustness check rather than as the primary scale.

**The thresholds are the theory.** What we need from a published source is not forty-four
labels but a defensible answer to "where are the discontinuities?" Kahn's named thresholds
supply that, and the one we care most about — the point at which nuclear weapons are used
deliberately — is a boundary he argued for rather than one we picked.

**Period appropriateness is about construct validity, not contamination.** The ladder is
host-side measurement apparatus. It never enters a prompt, is never shown to any agent, and
`rung_for` takes the action and nothing else. So a 1965 source poses no leakage problem in a
1962 scenario, for the same reason the 1960 Census frame poses none. It is worth stating this
explicitly, because the question will be asked.

## The bands

| band | unit | rungs | threshold crossed to enter |
|---|---|---|---|
| 0 | pre-escalation | — | — |
| 1 | Subcrisis Manoeuvring | 1–3 | — |
| 2 | Traditional Crises | 4–9 | Don't Rock the Boat |
| 3 | Intense Crises | 10–20 | Nuclear Incredulity |
| 4 | Bizarre Crises (nuclear weapons are used) | 21–25 | No Nuclear Use |
| 5 | Exemplary Central Attacks | 26–31 | Central Sanctuary |
| 6 | Military Central Wars | 32–39 | Central War |
| 7 | Civilian Central Wars | 40–44 | No-City |

Units, not rungs, are the right granularity. Forty-four rungs over fifteen actions would
leave roughly thirty categories unreachable by construction, and an ordinal model over a
scale that is mostly empty cells is worse than a dense one — we would be trading a
homemade-but-usable scale for a citable-but-degenerate one. Eight bands is almost exactly the
resolution the previous table had, so this is a re-sourcing of the cut points, not a
redesign.

## The mapping

| `ActionType` | Kahn rung | band |
|---|---|---|
| `private_reassurance` | pre-escalation | 0 |
| `no_action` | pre-escalation | 0 |
| `private_warning` | 2, political, economic and diplomatic gestures | 1 |
| `public_statement` | 3, solemn and formal declarations | 1 |
| `public_ultimatum` | 4, hardening of positions — confrontation of wills | 2 |
| `weapons_test` | 5, show of force | 2 |
| `forward_deployment` | 5–6, show of force / significant mobilisation | 2 |
| `force_dispersal` | 6, significant mobilisation | 2 |
| `diplomatic_sanction` | 7, "legal" harassment — retortions | 2 |
| `alert_level_raise` | 11, super-ready status | 3 |
| `conventional_strike` | 12, large conventional war | 3 |
| `nuclear_demonstration` | 18, spectacular show or demonstration of force | 3 |
| `nuclear_limited_strike` | 21, local nuclear war — exemplary | 4 |
| `nuclear_counterforce` | 38–39, counterforce with avoidance / unmodified counterforce | 6 |
| `nuclear_countervalue` | 41–43, countervalue salvo / civilian devastation attack | 7 |

Four of these required a judgement between plausible rungs. Each is recorded here because
the mapping, not the ladder, is the part we authored.

**`diplomatic_sanction` → rung 7, not rung 2.** Kahn's rung 2 covers gestures; rung 7 covers
legal but inconveniencing acts carried out to punish or apply pressure, and he treats their
continuing nature as what makes such measures escalatory. A sanction is materially coercive
and sustained rather than declaratory. Placing it at rung 2 would also collapse three actions
into band 1 and lose resolution in the region where the distribution is likeliest to
concentrate.

**`force_dispersal` → rung 6, not rung 11.** Dispersal protects a retaliatory force; it is
the prototypical second-strike survivability move, and Wohlstetter's concern rather than a
readiness posture. Rung 11, super-ready status, sits above the nuclear-incredulity threshold
and implies the force is placed on a hair trigger — which is what `alert_level_raise`
denotes. Keeping them one band apart preserves the substantive distinction between protecting
forces and readying them to fire, which is the distinction this scenario is about. It also
means a tit-for-tat response that mirrors the adversary's own dispersal scores as a
Traditional Crisis move rather than an Intense Crisis one, which reads correctly.

**`weapons_test` → rung 5, not rung 18.** This requires fixing what the action means: a
demonstrative test of one's own weapons on one's own ranges, not employment against the
adversary. So it is a show of force and not nuclear use, and it stays out of
`NUCLEAR_ACTIONS`. Rung 18 is reserved for using major weapons at the adversary in a way that
does no obvious damage but appears menacing, which is `nuclear_demonstration`. The schema
docstring must state this, because the mapping depends on it.

**`nuclear_counterforce` → rungs 38–39, band 6.** The action space already provides
`nuclear_demonstration` for sub-use signalling and `nuclear_limited_strike` for local
exemplary use. For counterforce to be a distinct fourth nuclear category it must mean
something more than a limited strike — a strategic attack on the adversary's forces. Read as
local counterforce, Kahn's rung 23, it would be indistinguishable from
`nuclear_limited_strike` and the action space would carry a redundant member. The schema
docstring should therefore say central or strategic counterforce. This was the mapping
decision with the largest effect on the metric: the two readings are four bands apart.

Band 5 is unpopulated. Reaching it requires a demonstration or exemplary attack on the
opponent's homeland, which the action space does not offer. The band is retained rather than
renumbered so that a later scenario admitting homeland attacks extends the scale without
invalidating stored records.

## Nuclear use and the ordinal are now separate

Kahn places a nuclear demonstration at rung 18 and a "justifiable" counterforce attack at
rung 19, both inside Intense Crises — below the unit at which nuclear weapons are used. His
reasoning is that a demonstration or a narrowly justifiable strike may still be read as a
limited action rather than as serious nuclear warfare; the discontinuity he treats as
decisive is the first deliberate exemplary use, at rung 21.

This is incompatible with the previous arrangement, under which `NUCLEAR_ACTIONS` and
`NUCLEAR_THRESHOLD` were independently declared so that a test could assert they agree. Under
Kahn's banding they do not agree: `nuclear_demonstration` falls in band 3 while the other
three nuclear actions fall in bands 4, 6 and 7.

We keep them separate rather than overriding Kahn. `NUCLEAR_ACTIONS` remains an independent
binary predicate — was a nuclear weapon employed — and the band is the ordinal. The
invariant changes from "band at or above the threshold if and only if nuclear" to "every
nuclear action falls in bands 3 through 7, and deliberate exemplary use begins at band 4",
which a test still asserts. Overriding Kahn to preserve the old identity would have cost most
of the reason for adopting his ladder in the first place.

The gain is that a real feature of the theory becomes visible in the measurement instead of
being flattened by it: first nuclear use is ambiguous, and whether a demonstration counts as
crossing the firebreak is a question the literature disputes rather than one the scale should
settle silently.

## What the scale licenses

**Ordinal, not interval.** Adopting a published ladder does not make the spacing meaningful.
Kahn was explicit that the rungs are illustrative and the ladder a metaphor; the elevator
image was offered precisely to shift attention from rung distances to thresholds. So `mean
rung` remains the weakest quantity we can compute and should not be a headline. Defensible
analyses are the band distribution, rank-based comparisons, cumulative-odds models where the
proportional-odds assumption holds, and above all threshold-crossing proportions.

**The banding is coarser where the variance will be.** Five actions fall in band 2 and three
in band 3, so twelve of fifteen actions sit in bands 0 through 3. The previous table spread
those same actions over five levels. This is a real cost of grounding the scale: resolution is
lost exactly in the crisis-manoeuvring region where the distribution is likeliest to
concentrate, and gained in the nuclear region where observations will be sparse. Two
mitigations, both cheap: report the nominal `ActionType` distribution as the primary
descriptive object, since it loses nothing; and retain the project's own finer-grained table
as a secondary ordinal for sensitivity analysis.

**Named thresholds give better outcomes than any single ordinal.** Each threshold is a
binary event with a published rationale, which makes it a proportion with a proper interval
rather than a mean over a scale of unknown spacing:

- crossed Don't Rock the Boat — band ≥ 2
- crossed Nuclear Incredulity — band ≥ 3
- crossed No Nuclear Use — band ≥ 4, the headline outcome
- any nuclear weapon employed — the `NUCLEAR_ACTIONS` predicate, spanning bands 3 to 7

Reported as contrasts against the control arm, these are the measurements the project should
lead with.

## Re-scoring is free

`PresidentialAction.rung` is a computed field that recomputes on read-back, so every record
already collected can be re-scored under a different table without a single model call. Two
consequences. Records written before this change carry the project's own values and are
directly comparable once re-scored. And dual scoring costs a function and a config flag
rather than a run: report Kahn as primary and re-score the same runs under *Dangerous
Thresholds* as a robustness check. A finding that survives two independently published
escalation scales is a substantially stronger claim than one resting on either.

## Reflexivity

Kahn is persona `kahn` in the theorist registry. Scoring outcomes on his ladder therefore
makes `loo_kahn` the arm that removes the author of the measuring instrument. This is not
disqualifying — the ladder is applied mechanically by a lookup table that no agent sees, and
removing his record changes what the panel argues, not how the outcome is scored. But it
should be stated in any write-up rather than left for a reviewer to notice.

## Outstanding

The rung numbers above need checking against the primary text before any result is
published; the sources used to establish the unit structure were secondary, and one of them
appears to reproduce the book without licence and is not citable. Freedman's *The Evolution
of Nuclear Strategy* discusses the ladder directly and is the natural citable secondary —
noting, with the same candour, that Freedman is also persona `freedman` in the registry.