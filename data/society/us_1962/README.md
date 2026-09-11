# The 1962 US public — sampling frame

A committed input, like `data/theorists/registry.yaml` and `data/excomm/registry.yaml`, not
a generated artefact. Loaded by `society.load_frame` and sampled by `society.sample_citizens`
(ADR 0009). The audience is an **outcome measure**: it reads the President's decision after
it is made and reacts to it. Nothing it produces returns to any earlier stage of the loop.

## The two files, and why they are separate

- **`strata.yaml`** — construction inputs. The marginal targets `sample_citizens` draws
  each citizen's stratum attributes from and rakes the panel's weights to match.
- **`validation_targets.yaml`** — held-out marginals, used only to compute
  `AudienceRecord.validation_distance` after the fact. **Never** read by the sampler.

Keeping these in separate files means a diff shows immediately if an item is ever moved
from one to the other. **Moving an item from `validation_targets.yaml` into
`strata.yaml` (or vice versa) invalidates the validation reading for every run recorded
before the move** — the check would then be comparing the sample against the table it was
built from, which validates nothing.

## Sourcing status

Every marginal in `strata.yaml` carries a `source:` line. Lines marked `# UNVERIFIED` are
my best reading of a commonly cited historical figure for the relevant Census/Gallup/SRC-NES
item, reproduced from general knowledge or a secondary compilation rather than confirmed
against a primary table in the session that authored this file. `west`'s regional share and
the `urbanicity`/`education` marginals *were* checked against a primary-Census-linked
compilation and are not marked UNVERIFIED.

This mirrors how `CLAUDE.md` already treats `corpus_notes`, `prominence`, and the claim
retrieval thresholds: the mechanism is real and testable now; some of the numbers it runs on
need a primary-source calibration pass before a run built on this frame is presented as a
finding rather than a demonstration of the mechanism. See
`docs/prompts/improvements-log.md` for the tracked follow-up.

## The independence assumption

`sample_citizens` draws each citizen's stratum values **independently per dimension** from
`strata.yaml`'s marginals (a weighted draw per dimension), then computes raking weights so
the *weighted* sample matches every dimension's marginal even though the independent draw
does not reproduce the true 1962 joint distribution across dimensions (e.g. region and party
identification really were correlated in 1962; this sampler does not model that
correlation). This is a real methodological simplification, stated in ADR 0009's
Consequences section, not silently assumed away. A joint (correlated) construction is the
tracked follow-up in `docs/prompts/improvements-log.md`.

## Raking parameters

`sample_citizens` uses standard RIM (iterative proportional) weighting: iterate over
dimensions, rescaling each citizen's weight by `target_share / current_weighted_share` for
their category, until either the maximum per-cell deviation from target is below
**tolerance 1e-4** or **25 iterations** have run, whichever comes first. `AudienceRecord`
warns (via `metrics._warnings`) when the achieved marginals still deviate from target beyond
this tolerance after convergence — a sign the sample size is too small for the number of
strata cells, not a bug in the raking itself.

## Editing this frame

- Adding a field to `schema.Citizen` requires adding its marginal here first —
  `society.load_frame` raises if a `Citizen` field has no matching dimension, and raises if
  a `strata.yaml` dimension has no matching `Citizen` field, so the two cannot drift apart.
- A category's share must be a plausible-sounding number **with a source line**, not an
  invented one — the same rule `CLAUDE.md` already holds theorist `prominence` values to,
  applied here for the first time to demographic data.
- `audience_size` (default 70) is set in `RunConfig`, not here; this file only supplies
  proportions, not a count.
