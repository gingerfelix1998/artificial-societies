# Task: add the 1962 US public as an audience tier

## Read first

`CLAUDE.md`, `docs/framework/access-matrix.md`, `docs/framework/design.md`,
`docs/framework/measurement.md`, and the existing ADRs in `docs/decisions/`. Follow the
conventions there rather than the ones in this brief where they disagree — and tell me if
they disagree.

This change introduces a **second population**. The framework docs currently state that the
group being modelled is the authors of the nuclear-strategy literature, and that the
President, Advisor and Intelligence Officer are instruments rather than samples. That
statement now needs to cover two populations: the literature's authors, and the 1962 US
public. State it once, in `design.md`, and don't restate it elsewhere.

## Decisions already made — do not reopen

1. **70 citizens**, stratified, with marginals taken from Gallup and the SRC/NES 1962
   studies. Not 100. Record the 70 figure and its justification in the ADR so the number
   never has to be defended from memory.
2. The audience sees **the publicly known event** and **the President's action plus its
   justification**. Nothing else. No literature, no theorist opinions, no claim or chunk
   ids, no ExComm deliberation, no intelligence reporting, no ground truth, no rung, no
   courses of action, and no other citizen's response.
3. The audience is an **outcome measure, not an input**. Nothing returns to the President
   in this phase. `escalation_prior` stays a two-call arm and the rung delta logic is
   untouched.
4. Approval is a **closed typed response space**. No free-text field is ever scored.

## Build

### 1. Schema — `src/artsoc/schema.py`

Type separation is the first enforcement layer, so the boundary has to be impossible to
cross rather than merely unwritten. Add:

- `PublicEvent` — the publicly known view of a world event. No `ground_truth_detail`, no
  collection or source fields, no confidence. A distinct type from `PerceivedEvent`, so
  the audience cannot be handed the state's collection picture by a caller passing the
  wrong list.
- `PublicStatement` — the President's action as publicly announced: the action label and
  the justification text. It must be impossible to construct carrying a rung, a
  `CourseOfAction` id, or any advisor content. Derive it from `PresidentialAction`
  explicitly, dropping those fields.
- `Citizen` — stratum attributes only. No name, no theorist tag vocabulary, no
  `prominence`-style invented score. Fields: `citizen_id`, plus exactly the strata present
  in the committed frame (region, urbanicity, age band, sex, education, party
  identification), plus the raking `weight`.
- `CitizenResponse` — `approval` as a five-way enum including an explicit no-opinion
  category, a typed `primary_concern` enum, a free-text `rationale` marked in its
  docstring as qualitative and never scored, and a `refused` flag.
- `AudienceRecord` — the sampled panel, the sample seed, the target marginals used,
  the achieved marginals, the weighted and unweighted approval distributions, and the
  diagnostics from step 8.
- `RunRecord.audience: AudienceRecord | None`.

`extra="forbid"` throughout. Any derived field recomputes on read-back, the way
`PresidentialAction.rung` already does, so a hand-edited JSONL record cannot assert a
different number than the code produces.

### 2. Committed sampling frame — `data/society/us_1962/`

This is a committed input like `data/theorists/registry.yaml`, not generated output.

- `strata.yaml` — the marginal targets used to **construct** personas. Every marginal
  carries a source line: survey, field dates, and the item wording where the marginal is
  attitudinal rather than demographic.
- `validation_targets.yaml` — held-out poll marginals used **only** to validate output.
  Separate file, so a diff shows immediately if anyone moved an item across the line.
- `README.md` — which marginals are construction inputs, which are validation targets, and
  a statement that moving an item from the second file to the first invalidates the
  validation for every run recorded before the move.

### 3. Sampler — new module `src/artsoc/society.py`

- `sample_citizens(frame, n, rng) -> list[Citizen]`. Deterministic given the seed. Rake or
  IPF to the target marginals and return the weights.
- **Own RNG stream.** Derive it separately, exactly as perception does in `sim.run_once`,
  so adding or removing audience calls cannot shift perception draws or routing at the same
  seed. This is the property that keeps the control-arm contrast clean.
- Record achieved against target marginals in `AudienceRecord`, and warn when any cell
  deviates beyond a tolerance stated in the frame README.
- No invented attributes. If an attribute has no marginal in the frame, it is not on the
  persona. A plausible-sounding biography is not evidence.

### 4. Audience agent — `src/artsoc/agents.py`

- Add `CITIZEN = "citizen"` to `llm.Role`. One prompt shape, stamped with its own
  `[[ROLE:citizen]]` marker like every other role.
- The prompt receives `PublicEvent[]`, one `PublicStatement`, and the citizen's own stratum
  attributes. Nothing else enters it.
- Guard with `assert_decontextualised(prompt, forbidden_tokens, where="citizen")`. Build
  `forbidden_tokens` from every theorist name and `persona_id` in the registry, every claim
  and chunk id in the retrieved blocks for this replication, every ExComm participant
  label, the intel brief text, and every `ground_truth_detail` string. Raise
  `BoundaryViolation`. Never scrub — a scrubbed prompt hides the bug.
- The audience is **ungrounded by construction**. Do not pass a retriever. `grounded` must
  read False for these calls, off the same mechanism that reports it for theorists.
- No peer visibility, no deliberation, one pass.
- Give the respondent their demographic and era context without naming the crisis. The
  scenario is anonymised to Nation A and B for a reason, and a 1962 frame is exactly the
  cue that lets a model retrieve how it ended.

### 5. Orchestration — `src/artsoc/sim.py`

- The audience stage runs after `president_decision`. It cannot influence the decision —
  prove that with the test in step 9, not with a comment.
- Fan out with `ThreadPoolExecutor`, keyed by index and re-sorted by index, so the record
  is byte-identical at any `max_concurrency`.
- On failure, record `(citizen_id, reason)` and continue. A refusal is data; a crash that
  silently drops a stratum is a biased sample. Response rate goes in diagnostics.
- These calls **cannot be cached**: their input is the decision and justification, which is
  the thing that varies by design. Disable the disk cache for this role and write the reason
  in a comment so nobody re-enables it as an optimisation.

### 6. Config — `src/artsoc/config.py` and `configs/`

`audience_enabled: bool = False`, `audience_size: int = Field(default=70, ge=1)`,
`audience_frame: str = "us_1962"`, `audience_method: str = "d1"`.

Arms vary one field each, as the existing ones do: `audience_d1` at minimum, plus a second
construction arm if you add one. Keep the default off so every existing arm's cost estimate
is unchanged.

### 7. Cost gate — `src/artsoc/session.py`

`estimate_calls` must add `audience_size` to `calls_per_replication` when the audience is
enabled. Seventy uncacheable calls on top of roughly twenty is a ~4.5x increase per
replication, and unlike the theorist fan-out none of it is recovered on a re-run. A session
must not be confirmable without that reflected in the estimate.

### 8. Metrics — `src/artsoc/metrics.py`

- Weighted approval distribution, unweighted alongside it for comparison, and a by-stratum
  breakdown.
- Delta against the arm's own control, consistent with how every other number in this
  project is interpreted.
- Validation against `validation_targets.yaml`: report the distance and do not tune to it.
- Four diagnostics that gate interpretation, in the style of the existing three:
  response rate; **leakage rate** — responses referencing the actual Cuban crisis, Kennedy,
  Khrushchev, or any post-1962 event; stratum coverage, with no stratum below a floor; and
  no-opinion rate, where a near-zero rate is a **warning**, not a success, by the same logic
  that makes a near-zero out-of-record rate suspicious.

### 9. Tests — `tests/test_access_matrix.py` and new `tests/test_society.py`

- **Canary.** Inject a unique token into every theorist record, every ExComm message, the
  intel brief and every `ground_truth_detail`; assert none appears in any citizen prompt.
  Then validate the suite by deliberately breaking each boundary, confirming each test
  fails, and reverting. A canary never shown to fail is not evidence.
- **Determinism.** Same seed gives the same sample, same order, at `max_concurrency` 1 and 8.
- **Independence.** Perception draws and routing records are identical with
  `audience_enabled` True and False at the same seed.
- **Sampler.** Achieved marginals within tolerance at n=70; weights behave as documented.
- **Schema.** `PublicStatement` cannot be constructed with a rung or a COA id;
  `PublicEvent` has no ground-truth field.
- Everything runs offline. The `conftest` guard against constructing a live backend stays
  unconditional.

### 10. Docs — in the same change, not after

- `docs/framework/access-matrix.md`: new rows for `citizen`, with an explicit "no" against
  intel brief, theorist opinions, claim ids, advisor brief, courses of action, ExComm
  deliberation, rung, and other citizens.
- New ADR in `docs/decisions/`: the audience as outcome measure rather than input; why
  `PublicEvent` is a distinct type instead of reusing `PerceivedEvent`; the 70 figure and
  the frame; and the construction-versus-validation split of the marginals.
- `design.md`: the loop gains a stage, and the population statement now covers two
  populations.
- `measurement.md`: the new metric, the four diagnostics, and a note on multiple
  comparisons if by-stratum breakdowns are going to be read as findings.

## Out of scope

No feedback loop to the President. No deliberation among citizens. No judge model anywhere
near the approval number. Do not touch the theorist panel, the rung table, or
`escalation_prior`.

## One question to settle in the ADR, not in code

"They see the real-world event" has two readings. Either (a) a public-disclosure view
derived from the `WorldLog` — what was announced or plainly observable — or (b) the same
`PerceivedEvent[]` the intelligence officer receives. Reading (b) hands the public the
state's collection picture, which is wrong for 1962 and turns the audience into a second
intelligence consumer rather than a public. **This brief assumes (a).** If you want (b) the
two types collapse into one, which is less code — but record the reason, because it changes
what the approval number means.

## Acceptance

- `make test` green offline, with the new canary tests included and each one having been
  made to fail before it was trusted.
- `make arms` lists the new arms, and `estimate_calls` reflects the 70 additional calls.
- One replication with the audience enabled produces an `AudienceRecord` carrying achieved
  marginals, weighted approval, and all four diagnostics.
- No statement of audience size, frame, or boundary appears in two places with two values.