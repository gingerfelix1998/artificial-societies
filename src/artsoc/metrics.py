"""Outcome distributions, diagnostics, and the caveats that must travel with them.

This is a designed experiment with ordinal and binary responses, not a classification
task: there is no accuracy, no F1, no confusion matrix, and no baseline classifier to beat.
The independent variables are the arm config fields (`persona_method`, `panel_source`,
`synthesis_mode`, `convene_excomm`, `audience_method`, `panel_size`, the `loo_*` exclusions)
with `escalation_prior` as the reference level; theoretical concepts a persona might invoke
are measured mediators, never independent variables. See `docs/framework/measurement.md`
for the full restatement and `docs/framework/ladder.md` for what the primary metric is
grounded in and what it does and does not license.

**The interpretation constraints are printed, not merely documented.** A number that
travels without its caveat is exactly how an absolute escalation rate becomes a finding
about nuclear strategists, which it is not: off-the-shelf models escalate in wargame
settings from neutral starting conditions (Rivera et al., FAccT 2024), so only the delta
against the control is interpretable. `format_report` therefore emits the warnings
alongside the numbers rather than leaving them to a reader who has `CLAUDE.md` open.

**`mean_rung`/`median_rung` are demoted, not removed.** They remain the weakest quantities
this module computes (`docs/framework/ladder.md`, "Ordinal, not interval"): a published
ladder does not make the spacing between its bands meaningful. The band distribution, the
nominal `ActionType` distribution, and the named threshold-crossing rates below are what
this report leads with.

Three diagnostics exist to catch the project deceiving itself:

* **Panel coverage** gates the panel-size claim. If distinct personas consulted is far
  below the declared panel size (12 by default), the panel is nominal and must be restated.
* **A near-zero out-of-record rate is a warning, not a success.** It means the escape hatch
  is not firing and personas are extrapolating past their record.
* **Citation integrity** counts attributions to passages that were never shown.

Influence figures are deliberately absent for routing correlation. Routing correlates with
question tags, which correlate with outcome, so any per-persona influence number from
*observed* routing would be observational and would be read as causal. `_loo_section` below
is the causal alternative: forced exclusion, not observed routing.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from artsoc.schema import (
    BAND_UNITS,
    DELIBERATE_NUCLEAR_BAND,
    DONT_ROCK_THE_BOAT_BAND,
    NUCLEAR_ACTIONS,
    NUCLEAR_INCREDULITY_BAND,
    RUNG_KAHN,
    RUNG_PROJECT,
    RunRecord,
    rung_for,
)

#: Below this ratio of consulted personas to declared panel size, the panel is nominal.
COVERAGE_WARNING_RATIO = 0.5

#: At or below this out-of-record rate, the escape hatch is suspected of not firing.
OUT_OF_RECORD_WARNING_RATE = 0.02

#: ADR 0009. Below this response rate, the audience diagnostic gates interpretation.
AUDIENCE_RESPONSE_WARNING_RATE = 0.9

#: At or below this no-opinion rate, the audience is suspected of performing an opinion
#: it does not have — the same reading as a near-zero out-of-record rate.
AUDIENCE_NO_OPINION_WARNING_RATE = 0.02

#: Below this per-stratum coverage ratio, a category is under-represented in the raw draw
#: badly enough that its raking weight is doing heavy lifting.
AUDIENCE_COVERAGE_FLOOR = 0.5

#: The control arm. Every interpretable number in a report is a delta against this.
CONTROL_ARM = "escalation_prior"

#: Prefix marking a forced-exclusion arm: a world in which one theorist never existed.
LOO_PREFIX = "loo_"

#: Default two-sided confidence level for every interval in this module.
DEFAULT_CONFIDENCE = 0.95

#: Below this many matched seed-pairs, the Wilcoxon normal approximation is not trusted;
#: `PairedContrast.wilcoxon.reliable` is False and only the sign test and the CI are read.
WILCOXON_MIN_N = 20

#: Below this many replications-with-audience, a between-cluster normal-approximation CI
#: is unstable — flagged in `_warnings`, not refused.
CLUSTER_MIN_N = 8


# ---------------------------------------------------------------------------
# Statistics primitives (ADR 0011). Stdlib-only: `statistics.NormalDist.inv_cdf` gives an
# exact z-critical value with no hardcoded 1.96, and `math.comb` gives an exact binomial
# CDF for the sign test. No numpy/scipy/pandas anywhere below.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    """A point estimate with a two-sided confidence interval.

    Deliberately generic: the same type carries a Wilson proportion interval, a
    cluster-mean interval, and a paired-difference interval, because
    `combine_interval_diff` treats them identically — for a symmetric interval (built by
    `mean_interval`) the combination reduces exactly to the ordinary two-sample
    z-interval, since a symmetric interval's own half-width already equals z * SE.
    """

    point: float
    lo: float
    hi: float


def _z(confidence: float = DEFAULT_CONFIDENCE) -> float:
    """Two-sided z-critical value at `confidence`, from the exact inverse normal CDF."""
    return statistics.NormalDist().inv_cdf(1 - (1 - confidence) / 2)


def wilson_interval(count: int, n: int, confidence: float = DEFAULT_CONFIDENCE) -> Interval:
    """Wilson score interval for a proportion (Wilson 1927).

    Preferred over the Wald interval here specifically because Wald produces
    nonsensical bounds — below 0 or above 1 — exactly in the small/skewed-`p` regime this
    project's threshold-crossing rates live in (a rare event, n in the tens to hundreds).
    """
    if n <= 0:
        raise ValueError("wilson_interval requires n > 0")
    if not (0 <= count <= n):
        raise ValueError(f"count={count} out of range for n={n}")
    z = _z(confidence)
    phat = count / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return Interval(phat, max(0.0, center - half), min(1.0, center + half))


def mean_interval(values: Sequence[float], confidence: float = DEFAULT_CONFIDENCE) -> Interval:
    """Normal-approximation CI on a sample mean.

    `values` must have at least 2 elements (`statistics.stdev` needs a sample variance).
    Uses z, not t — stdlib has no inverse-t distribution — which is anti-conservative (too
    narrow) at small n; read as a caveat, not a refusal, the same way this project already
    reads a small-n corroboration count.
    """
    n = len(values)
    if n < 2:
        raise ValueError("mean_interval requires at least 2 values")
    mean = statistics.fmean(values)
    se = statistics.stdev(values) / math.sqrt(n)
    z = _z(confidence)
    return Interval(mean, mean - z * se, mean + z * se)


def combine_interval_diff(a: Interval, b: Interval) -> Interval:
    """CI for `a.point - b.point` from two *independent* interval estimates.

    Newcombe's hybrid-score combination (Newcombe 1998, "Method 10"). Serves both the
    risk-difference contrast (two `wilson_interval`s) and the clustered-approval delta (two
    `mean_interval`s) with one function — needs nothing beyond the two intervals already
    computed, no numerical solver.
    """
    d = a.point - b.point
    lo = d - math.sqrt((a.point - a.lo) ** 2 + (b.hi - b.point) ** 2)
    hi = d + math.sqrt((a.hi - a.point) ** 2 + (b.point - b.lo) ** 2)
    return Interval(d, lo, hi)


def matched_seed_pairs(
    a: Iterable[RunRecord], b: Iterable[RunRecord]
) -> list[tuple[RunRecord, RunRecord]]:
    """Records from two arms sharing a seed, in ascending seed order.

    Seeds are a blocking factor (`docs/framework/measurement.md`): perception draws its
    own rng stream from the seed, so two arms run at the same seed are a matched pair, not
    an accident. Raises on a duplicate seed within one arm's own records — a pairing must
    be one-to-one, and a repeat there is a bug upstream, not something to silently average.
    """

    def _by_seed(records: Iterable[RunRecord]) -> dict[int, RunRecord]:
        out: dict[int, RunRecord] = {}
        for r in records:
            if r.seed in out:
                raise ValueError(f"duplicate seed {r.seed} within one arm's records")
            out[r.seed] = r
        return out

    by_seed_a, by_seed_b = _by_seed(a), _by_seed(b)
    shared = sorted(set(by_seed_a) & set(by_seed_b))
    return [(by_seed_a[s], by_seed_b[s]) for s in shared]


@dataclass(frozen=True)
class SignTestResult:
    """An exact two-sided sign test over non-zero paired differences."""

    n: int
    n_pos: int
    n_neg: int
    p_two_sided: float


def sign_test(diffs: Sequence[float]) -> SignTestResult:
    """Exact two-sided sign test, via the exact binomial CDF (`math.comb`).

    Needs no table and no scipy: the binomial coefficients are exact integers, and
    Python's arbitrary-precision ints handle even a few hundred matched pairs without
    overflow.
    """
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    if n == 0:
        return SignTestResult(0, 0, 0, 1.0)
    n_pos = sum(1 for d in nz if d > 0)
    n_neg = n - n_pos
    k = min(n_pos, n_neg)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2**n)
    return SignTestResult(n, n_pos, n_neg, p)


@dataclass(frozen=True)
class WilcoxonResult:
    """Wilcoxon signed-rank statistic, normal-approximated (tie-corrected, continuity-
    corrected). `reliable=False` below `WILCOXON_MIN_N` matched pairs — surfaced with that
    caveat, never suppressed, the same way `SMOKE TEST`/`MOCK BACKEND` are surfaced."""

    n: int
    statistic: float
    z: float
    p_two_sided: float
    reliable: bool


def wilcoxon_signed_rank(diffs: Sequence[float]) -> WilcoxonResult:
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    if n == 0:
        return WilcoxonResult(0, 0.0, 0.0, 1.0, False)
    ranked = sorted(range(n), key=lambda i: abs(nz[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(nz[ranked[j + 1]]) == abs(nz[ranked[i]]):
            j += 1
        avg_rank = (i + 1 + j + 1) / 2
        for k in range(i, j + 1):
            ranks[ranked[k]] = avg_rank
        i = j + 1
    w_pos = sum(ranks[i] for i in range(n) if nz[i] > 0)
    mu = n * (n + 1) / 4
    # Tie correction over groups of equal |d_i|.
    tie_term = 0.0
    i = 0
    sorted_abs = sorted(abs(d) for d in nz)
    while i < n:
        j = i
        while j + 1 < n and sorted_abs[j + 1] == sorted_abs[i]:
            j += 1
        t = j - i + 1
        tie_term += t**3 - t
        i = j + 1
    var = n * (n + 1) * (2 * n + 1) / 24 - tie_term / 48
    if var <= 0:
        return WilcoxonResult(n, w_pos, 0.0, 1.0, False)
    sigma = math.sqrt(var)
    correction = 0.5 if w_pos > mu else -0.5
    z_stat = (w_pos - mu - correction) / sigma
    p = 2 * (1 - statistics.NormalDist().cdf(abs(z_stat)))
    return WilcoxonResult(n, w_pos, z_stat, min(1.0, p), n >= WILCOXON_MIN_N)


@dataclass(frozen=True)
class PairedContrast:
    """A within-seed contrast between an arm and the control, blocked on the seed.

    `value_fn` defaults to the recomputed band under the arm's own effective ladder; pass
    e.g. a "moved off the lean" 0/1 indicator for a lean->decision paired contrast.
    `None` from `paired_contrast` when the two arms share no seeds — nothing to pair.
    """

    arm: str
    control: str
    n_pairs: int
    mean_diff: float
    median_diff: float
    diff_interval: Interval
    sign: SignTestResult
    wilcoxon: WilcoxonResult
    notes: list[str] = field(default_factory=list)


def paired_contrast(
    arm_records: list[RunRecord],
    control_records: list[RunRecord],
    value_fn: Callable[[RunRecord], float] | None = None,
    confidence: float = DEFAULT_CONFIDENCE,
) -> PairedContrast | None:
    """Within-seed contrast, blocking on the shared seed rather than treating the two
    arms as independent samples. Read alongside, never instead of, the unpaired delta."""
    fn = value_fn or (lambda r: float(rung_for(r.action.action, ladder=r.action.ladder)))
    pairs = matched_seed_pairs(arm_records, control_records)
    if not pairs:
        return None
    diffs = [fn(a) - fn(b) for a, b in pairs]
    notes: list[str] = []
    if len(pairs) < WILCOXON_MIN_N:
        notes.append(
            f"FEW MATCHED SEEDS ({len(pairs)}): the Wilcoxon normal approximation is not "
            "reliable below 20 pairs; read the sign test and the difference interval."
        )
    diff_interval = (
        mean_interval(diffs, confidence)
        if len(diffs) >= 2
        else Interval(diffs[0], diffs[0], diffs[0])
    )
    return PairedContrast(
        arm=arm_records[0].arm,
        control=control_records[0].arm,
        n_pairs=len(pairs),
        mean_diff=round(statistics.fmean(diffs), 3),
        median_diff=statistics.median(diffs),
        diff_interval=diff_interval,
        sign=sign_test(diffs),
        wilcoxon=wilcoxon_signed_rank(diffs),
        notes=notes,
    )


def approval_shares(records: list[RunRecord]) -> list[float]:
    """One weighted approve-or-strongly-approve share per replication with an audience.

    This is the unit `mean_interval` should be applied to for `d_approval`'s CI, not the
    ~70 citizens inside each replication: citizens are nested within a replication and
    share its context (the same public event and statement), so a per-citizen Wilson
    interval answers "how uncertain is one citizen's answer", not "how uncertain is this
    arm's approval share" — the true independent unit is the replication.
    """
    return [
        r.audience.weighted_approval.get("approve", 0.0)
        + r.audience.weighted_approval.get("strongly_approve", 0.0)
        for r in records
        if r.audience is not None
    ]


def load_jsonl(path: Path) -> list[RunRecord]:
    """Load run records from a JSONL file, validating each against the schema."""
    if not path.exists():
        raise FileNotFoundError(f"no run output at {path}")
    records = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(RunRecord.model_validate(json.loads(line)))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{path}:{i} is not a valid RunRecord: {exc}") from exc
    if not records:
        raise ValueError(f"{path} contains no records")
    return records


@dataclass
class ArmSummary:
    """One arm's distribution and diagnostics, with the conditions that produced them."""

    arm: str
    n: int
    rung_distribution: dict[int, int]
    mean_rung: float
    median_rung: float
    p_nuclear: float

    #: The panel each replication drew from.
    declared_panel_size: int
    #: Distinct personas that ever spoke across the whole sweep. Where an arm resamples its
    #: panel per replication this can exceed `declared_panel_size`, which is why it is not
    #: what the coverage warning is computed from.
    distinct_personas: int
    #: Mean fraction of a replication's own panel that it actually consulted. Well defined
    #: whether or not the panel is resampled, so this is what gates the panel-size claim.
    mean_run_coverage: float

    n_opinions: int
    out_of_record_rate: float
    n_citations: int
    n_unsupported: int
    citation_integrity: float

    backend: str
    grounded: bool
    cache_enabled: bool
    retrieval_mode: str
    consulted_panel: bool
    #: M1 personas have no record, so the out-of-record hatch does not apply to them and a
    #: zero rate there is correct rather than a warning.
    persona_method: str

    #: Share of stated positions resting on the belief store rather than on retrieved
    #: sources. Read with the decline rate: together they say whether a panel that answers
    #: freely is doing so from evidence or from ideology (ADR 0004).
    basis_counts: dict[str, int] = field(default_factory=dict)
    beliefs_share: float = 0.0

    #: What the grounding actually was. `grounded` stopped distinguishing runs the moment
    #: two source kinds could serve one panel, so the report prints this beside it (ADR
    #: 0007). Reduced across the arm's records: one value, or `mixed`. Defaulted so that
    #: summaries built by hand, and records written before 1.2.0, still construct.
    corpus_tier: str = "none"

    #: Corroboration depth over the positions that came from a claim index: the mean number
    #: of publications the matched position was argued across, and the share that rested on
    #: a single one.
    #:
    #: This is what replaces ADR 0004's belief diagnostic where it has become meaningless —
    #: every claim has evidence by construction, so `beliefs_share` cannot say anything
    #: about a markdown panel. It is a diagnostic and not evidence: grouping is
    #: negation-blind, and on a thin corpus almost every group is a singleton, so a depth of
    #: 1.0 says the corpus is small rather than that the theorists were unsupported.
    mean_corroboration: float = 0.0
    single_source_share: float = 0.0

    #: The lean->decision contrast (ADR 0008). `secret_lean` is the President's prior over
    #: the three courses, captured before any deliberation; `rung` is where the decision
    #: landed. `lean_shift` is `rung(action) - rung(secret_lean)` per replication, both
    #: scored on the arm's effective ladder.
    #:
    #: `baseline` records the lean but runs no debate, so its `mean_lean_shift` is the
    #: decision's own instability — the noise floor. The interpretable quantity is
    #: `excomm_debate.mean_lean_shift - baseline.mean_lean_shift`; the absolute movement of
    #: either arm is not a finding (Rivera et al.). Defaulted for records with no lean.
    n_with_lean: int = 0
    mean_lean_shift: float = 0.0
    p_moved: float = 0.0
    p_moved_up: float = 0.0
    p_moved_down: float = 0.0
    #: Mean rounds the committee actually ran, `0.0` on an arm with no deliberation.
    mean_deliberation_rounds: float = 0.0
    #: Share of committee turns that abstained. A near-zero rate is a warning — a panel
    #: performing participation — the same reading as the out-of-record rate.
    abstention_rate: float = 0.0

    #: Which model served each role. One distinct value across every role means a smoke
    #: test: the presidential decision is the primary metric, and serving it from the same
    #: cheap model as everything else changes what was measured, not just what it cost.
    models: dict[str, str] = field(default_factory=dict)

    #: The citizen audience's reaction (ADR 0009), averaged across the replications that
    #: recorded one. `weighted_approval`/`unweighted_approval` are the mean, across
    #: replications, of each replication's own approval-value shares — the same "average
    #: of per-replication figures" reduction `mean_rung` uses. An outcome measure: `delta`
    #: is the only interpretable contrast, never the absolute share (Rivera et al.).
    n_with_audience: int = 0
    weighted_approval: dict[str, float] = field(default_factory=dict)
    unweighted_approval: dict[str, float] = field(default_factory=dict)
    mean_response_rate: float = 0.0
    #: Share of responses whose rationale named the real crisis, its real participants, or
    #: a post-1962 event — parametric leakage the model produced unprompted.
    mean_leakage_rate: float = 0.0
    mean_no_opinion_rate: float = 0.0
    #: The fifth audience diagnostic (ADR 0011): share of responses that were structural
    #: refusals, excluded from `weighted_approval`/`unweighted_approval` alike.
    mean_refusal_rate: float = 0.0
    #: The lowest per-dimension achieved/target coverage ratio seen across every
    #: replication with an audience. Below `AUDIENCE_COVERAGE_FLOOR` some stratum cell is
    #: under-represented badly enough that its raking weight is doing heavy lifting.
    stratum_coverage_floor: float = 0.0
    #: One weighted approve-share per replication with an audience (`approval_shares`) and
    #: the clustered CI over them — replications, not citizens, are the independent unit.
    approval_shares: list[float] = field(default_factory=list)
    approval_interval: Interval | None = None

    #: Which ladder produced every rung/band-derived number above (ADR 0011). `"mixed"`
    #: when the records were not all stamped with the same ladder and no explicit ladder
    #: override was requested — `format_report` warns on this the way it warns on a mixed
    #: `corpus_tier`.
    ladder: str = "kahn"
    #: Nominal `ActionType` counts — the primary descriptive object per
    #: `docs/framework/ladder.md`: it loses nothing to banding and should be read before
    #: any ordinal summary of the same data.
    action_distribution: dict[str, int] = field(default_factory=dict)
    #: `NUCLEAR_ACTIONS` is independent of any ladder or band cut — a fact about the
    #: action itself. `p_nuclear` (kept for the frontend's existing field name) and
    #: `p_nuclear_use` are the same quantity under two names.
    n_nuclear_use: int = 0
    p_nuclear_use: float = 0.0
    p_nuclear_use_interval: Interval | None = None
    #: Named Kahn-band threshold-crossing rates — the headline outcomes
    #: (`docs/framework/ladder.md`, "What the scale licenses"). Meaningful as named
    #: thresholds only when `ladder == "kahn"`; still computed as plain band cuts under
    #: `"project"`, without the Kahn names attached.
    n_dont_rock_the_boat: int = 0
    p_dont_rock_the_boat: float = 0.0
    p_dont_rock_the_boat_interval: Interval | None = None
    n_nuclear_incredulity: int = 0
    p_nuclear_incredulity: float = 0.0
    p_nuclear_incredulity_interval: Interval | None = None
    #: The headline outcome: crossed "No Nuclear Use" (Kahn band >= 4).
    n_deliberate_nuclear: int = 0
    p_deliberate_nuclear: float = 0.0
    p_deliberate_nuclear_interval: Interval | None = None

    warnings: list[str] = field(default_factory=list)


def reduce_tier(tiers: Iterable[str]) -> str:
    """One arm's corpus tier: the single value it used, or `mixed`.

    `none` is dropped before reducing, because a replication that retrieved nothing did not
    contribute a different kind of source — it contributed no source. Without that, one
    declining replication would make a uniformly-summary arm read as mixed.
    """
    seen = {tier for tier in tiers if tier and tier != "none"}
    if not seen:
        return "none"
    return next(iter(seen)) if len(seen) == 1 else "mixed"


def _reduce_ladder(ladders: Iterable[str]) -> str:
    """One arm's effective ladder: the single value used, or `mixed`."""
    seen = set(ladders)
    return next(iter(seen)) if len(seen) == 1 else "mixed"


def summarise(records: list[RunRecord], ladder: str | None = None) -> ArmSummary:
    """Reduce one arm's records to a distribution plus diagnostics.

    Every record must belong to the same arm: mixing arms would average across the thing
    the experiment is trying to contrast.

    `ladder`, when given, re-scores every record's decision and lean under that ladder —
    this is what `artsoc analyse --ladder` and re-scoring an existing output file use, and
    it costs no model call, since it only ever reads `record.action.action`. When omitted
    (the normal report path), each record is scored under its own stamped
    `record.action.ladder`, so a pre-ADR-0011 (`"project"`) record and a post-ADR-0011
    (`"kahn"`) one are each read consistently against themselves rather than forced onto
    one ladder.
    """
    arms = {r.arm for r in records}
    if len(arms) != 1:
        raise ValueError(f"summarise expects one arm, got {sorted(arms)}")

    def eff_ladder(r: RunRecord) -> str:
        return ladder if ladder is not None else r.action.ladder

    rungs = [rung_for(r.action.action, ladder=eff_ladder(r)) for r in records]
    distribution = dict(sorted(Counter(rungs).items()))
    action_distribution = dict(Counter(r.action.action.value for r in records))

    n_nuclear_use = sum(1 for r in records if r.action.action in NUCLEAR_ACTIONS)
    n_dont_rock = sum(1 for v in rungs if v >= DONT_ROCK_THE_BOAT_BAND)
    n_incredulity = sum(1 for v in rungs if v >= NUCLEAR_INCREDULITY_BAND)
    n_deliberate = sum(1 for v in rungs if v >= DELIBERATE_NUCLEAR_BAND)
    n = len(records)

    opinions = [o for r in records for o in r.opinions]
    declined = sum(1 for o in opinions if o.out_of_record)
    # Corroboration is only defined where a claim index produced the position, so the
    # denominator is those positions and not every opinion — averaging a structural zero in
    # from the eight Wikipedia personas would drag the depth toward nothing and read as a
    # thin corpus rather than as a metric that does not apply.
    claim_based = [o for o in opinions if o.basis == "claims" and not o.out_of_record]
    citations = sum(len(o.citations) for o in opinions)
    unsupported = sum(len(r.unsupported_citations) for r in records)

    # ADR 0008/0011. Only replications that recorded a lean contribute; the lean and the
    # decision are both scored on the same per-record effective ladder, so this is a band
    # contrast, not a text one.
    with_lean = [r for r in records if r.secret_lean is not None]
    shifts = [
        rung_for(r.action.action, ladder=eff_ladder(r))
        - rung_for(r.secret_lean, ladder=eff_ladder(r))
        for r in with_lean
    ]
    turns = [s for r in records for s in r.deliberation]

    consulted = {p for r in records for p in r.personas_consulted}
    declared = max((r.panel_size for r in records), default=0)
    per_run = [
        len(r.personas_consulted) / r.panel_size for r in records if r.panel_size
    ]

    # ADR 0009. Only replications with `audience_enabled` contribute; the audience is an
    # outcome measure, so its absence on most arms is expected, not an error.
    with_audience = [r for r in records if r.audience is not None]
    approval_keys = {k for r in with_audience for k in r.audience.weighted_approval}
    weighted_approval = {
        k: round(
            statistics.fmean(r.audience.weighted_approval.get(k, 0.0) for r in with_audience), 4
        )
        for k in approval_keys
    }
    unweighted_keys = {k for r in with_audience for k in r.audience.unweighted_approval}
    unweighted_approval = {
        k: round(
            statistics.fmean(r.audience.unweighted_approval.get(k, 0.0) for r in with_audience), 4
        )
        for k in unweighted_keys
    }
    coverage_values = [
        v for r in with_audience for v in r.audience.stratum_coverage.values()
    ]
    shares = approval_shares(with_audience)

    first = records[0]
    summary = ArmSummary(
        arm=first.arm,
        n=n,
        rung_distribution=distribution,
        mean_rung=round(statistics.fmean(rungs), 3),
        median_rung=statistics.median(rungs),
        p_nuclear=round(n_nuclear_use / n, 4),
        declared_panel_size=declared,
        distinct_personas=len(consulted),
        mean_run_coverage=round(statistics.fmean(per_run), 3) if per_run else 0.0,
        n_opinions=len(opinions),
        out_of_record_rate=round(declined / len(opinions), 4) if opinions else 0.0,
        basis_counts=dict(Counter(o.basis for o in opinions)),
        beliefs_share=round(
            sum(1 for o in opinions if o.basis == "beliefs" and not o.out_of_record)
            / max(1, sum(1 for o in opinions if not o.out_of_record)),
            4,
        ),
        n_citations=citations,
        n_unsupported=unsupported,
        citation_integrity=round(1 - unsupported / citations, 4) if citations else 1.0,
        mean_corroboration=(
            round(statistics.fmean(c.corroboration for c in claim_based), 3)
            if claim_based
            else 0.0
        ),
        single_source_share=(
            round(sum(1 for c in claim_based if c.corroboration <= 1) / len(claim_based), 4)
            if claim_based
            else 0.0
        ),
        n_with_lean=len(with_lean),
        mean_lean_shift=round(statistics.fmean(shifts), 3) if shifts else 0.0,
        p_moved=round(sum(1 for s in shifts if s != 0) / len(shifts), 4) if shifts else 0.0,
        p_moved_up=round(sum(1 for s in shifts if s > 0) / len(shifts), 4) if shifts else 0.0,
        p_moved_down=(
            round(sum(1 for s in shifts if s < 0) / len(shifts), 4) if shifts else 0.0
        ),
        mean_deliberation_rounds=round(
            statistics.fmean(r.deliberation_rounds for r in records), 3
        ),
        abstention_rate=(
            round(sum(1 for s in turns if s.abstained) / len(turns), 4) if turns else 0.0
        ),
        backend=first.backend,
        models=dict(first.models),
        grounded=first.grounded,
        # Reduced across every record rather than read off the first: a sweep in which one
        # replication routed to a summary corpus and another to an encyclopedia one is
        # mixed, and reporting whichever came first would hide that.
        corpus_tier=reduce_tier(r.corpus_tier for r in records),
        cache_enabled=first.cache_enabled,
        retrieval_mode=first.retrieval_mode,
        consulted_panel=bool(first.opinions) or first.advisor_brief is not None,
        persona_method=str(first.config.get("persona_method", "unknown")),
        n_with_audience=len(with_audience),
        weighted_approval=weighted_approval,
        unweighted_approval=unweighted_approval,
        mean_response_rate=(
            round(statistics.fmean(r.audience.response_rate for r in with_audience), 4)
            if with_audience
            else 0.0
        ),
        mean_leakage_rate=(
            round(statistics.fmean(r.audience.leakage_rate for r in with_audience), 4)
            if with_audience
            else 0.0
        ),
        mean_no_opinion_rate=(
            round(statistics.fmean(r.audience.no_opinion_rate for r in with_audience), 4)
            if with_audience
            else 0.0
        ),
        mean_refusal_rate=(
            round(statistics.fmean(r.audience.refusal_rate for r in with_audience), 4)
            if with_audience
            else 0.0
        ),
        stratum_coverage_floor=round(min(coverage_values), 4) if coverage_values else 0.0,
        approval_shares=[round(v, 4) for v in shares],
        approval_interval=mean_interval(shares) if len(shares) >= 2 else (
            Interval(shares[0], shares[0], shares[0]) if shares else None
        ),
        ladder=ladder if ladder is not None else _reduce_ladder(r.action.ladder for r in records),
        action_distribution=action_distribution,
        n_nuclear_use=n_nuclear_use,
        p_nuclear_use=round(n_nuclear_use / n, 4),
        p_nuclear_use_interval=wilson_interval(n_nuclear_use, n),
        n_dont_rock_the_boat=n_dont_rock,
        p_dont_rock_the_boat=round(n_dont_rock / n, 4),
        p_dont_rock_the_boat_interval=wilson_interval(n_dont_rock, n),
        n_nuclear_incredulity=n_incredulity,
        p_nuclear_incredulity=round(n_incredulity / n, 4),
        p_nuclear_incredulity_interval=wilson_interval(n_incredulity, n),
        n_deliberate_nuclear=n_deliberate,
        p_deliberate_nuclear=round(n_deliberate / n, 4),
        p_deliberate_nuclear_interval=wilson_interval(n_deliberate, n),
    )
    summary.warnings = _warnings(summary)
    return summary


def _warnings(s: ArmSummary) -> list[str]:
    """Diagnostics that should stop a number being read as a result."""
    out: list[str] = []
    if not s.grounded:
        out.append(
            "NOT GROUNDED: StubRetriever was in use. No result here is corpus-grounded, "
            "and the registry corpus_notes are placeholders rather than evidence."
        )
    distinct = set(s.models.values())
    if s.backend != "mock" and len(distinct) == 1 and len(s.models) > 1:
        out.append(
            f"SMOKE TEST, NOT A RESULT ({s.arm}): every role was served by "
            f"{distinct.pop()}. models_override was set, which pins the presidential "
            "decision — the primary metric — to the same cheap model as everything else. "
            "This run checks that the wiring works. It is not comparable to any run "
            "without the override and must not appear in a write-up."
        )
    if s.backend == "mock":
        out.append(
            "MOCK BACKEND: responses are deliberately content-nonsense. Arms differ here "
            "only because their prompts hash differently. Nothing in this report is a "
            "finding about nuclear strategists."
        )
    if s.ladder == "mixed":
        out.append(
            f"MIXED LADDERS ({s.arm}): this arm's records were not all scored under the "
            "same escalation ladder. Re-score explicitly with `artsoc analyse --ladder` "
            "before comparing its band distribution to another arm's."
        )
    if (
        s.consulted_panel
        and s.declared_panel_size
        and s.mean_run_coverage < COVERAGE_WARNING_RATIO
    ):
        out.append(
            f"NOMINAL PANEL ({s.arm}): a replication consults on average "
            f"{s.mean_run_coverage:.0%} of its {s.declared_panel_size}-persona panel. The "
            "panel-size claim must be restated at the number actually consulted, not the "
            "number available."
        )
    # ADR 0004 replaced "a near-zero out-of-record rate is a warning" with the combination
    # that actually matters: personas answering freely while resting on ideology rather than
    # on retrieved sources. A low decline rate over well-sourced positions is a grounded
    # panel and is not warned about.
    if s.n_opinions and s.beliefs_share > 0.5 and s.out_of_record_rate < 0.2:
        out.append(
            f"POSITIONS REST ON BELIEF, NOT SOURCES ({s.arm}): {s.beliefs_share:.0%} of "
            f"stated positions came from the belief store while only "
            f"{s.out_of_record_rate:.0%} declined. The panel is asserting what these "
            "theorists held rather than citing where they held it."
        )
    # ADR 0004's diagnostic is meaningless where every claim carries evidence by
    # construction, so corroboration depth replaces it for those personas: a position found
    # in one work is weaker than one a theorist argued across three. Reported as a fact
    # about the corpus, because on a thin one it is exactly that.
    if s.basis_counts.get("claims") and s.single_source_share > 0.5:
        out.append(
            f"SINGLE-SOURCE POSITIONS ({s.arm}): {s.single_source_share:.0%} of positions "
            f"drawn from the claim index rest on one publication (mean depth "
            f"{s.mean_corroboration:.2f}). Read this as a fact about corpus breadth first: "
            "with few documents per theorist almost every position is single-sourced, and "
            "grouping is negation-blind, so depth attests to vocabulary rather than to "
            "agreement."
        )
    if s.corpus_tier == "mixed":
        out.append(
            f"MIXED CORPUS TIERS ({s.arm}): this arm's panel drew on more than one kind of "
            "source, so `grounded: true` covers passages of different evidential weight. "
            "A contrast against another arm is only clean if that arm mixed them the same "
            "way."
        )
    # ADR 0008. A committee whose debate never moves the President is either inert or the
    # transcript is not reaching the decision prompt. Only meaningful once a debate ran.
    if s.mean_deliberation_rounds > 0 and s.n_with_lean and s.p_moved < 0.02:
        out.append(
            f"DELIBERATION MOVED NOBODY ({s.arm}): {s.p_moved:.0%} of decisions differ "
            f"from the President's recorded lean after a {s.mean_deliberation_rounds:.1f}"
            "-round debate. A debate that never shifts the decision is either inert or its "
            "transcript is not reaching `decide`."
        )
    if s.mean_deliberation_rounds > 0 and s.abstention_rate <= 0.02:
        out.append(
            f"NO ABSTENTIONS ({s.arm}): committee members abstained on "
            f"{s.abstention_rate:.0%} of turns. A near-zero rate is a panel performing "
            "participation, the same reading as a near-zero out-of-record rate."
        )
    # ADR 0009/0011. Five diagnostics gate the audience the way three gate the panel.
    if s.n_with_audience and s.mean_response_rate < AUDIENCE_RESPONSE_WARNING_RATE:
        out.append(
            f"LOW AUDIENCE RESPONSE RATE ({s.arm}): {s.mean_response_rate:.0%} of sampled "
            "citizens produced a response. The missing share is a dropped stratum, not "
            "just a smaller n — check `failures` before reading the approval share."
        )
    if s.n_with_audience and s.mean_leakage_rate > 0:
        out.append(
            f"AUDIENCE LEAKAGE ({s.arm}): {s.mean_leakage_rate:.1%} of citizen responses "
            "named the real crisis, its real participants, or a post-1962 event, "
            "unprompted. This is the model's own parametric knowledge surfacing despite "
            "the decontextualised era framing, not a prompt-boundary breach."
        )
    if s.n_with_audience and s.mean_no_opinion_rate <= AUDIENCE_NO_OPINION_WARNING_RATE:
        out.append(
            f"NO-OPINION RATE NEAR ZERO ({s.arm}): only {s.mean_no_opinion_rate:.1%} of "
            "citizens had no opinion. A near-zero rate is a warning, not a success — the "
            "same reading a near-zero out-of-record rate gets for the theorist panel."
        )
    if s.n_with_audience and s.stratum_coverage_floor < AUDIENCE_COVERAGE_FLOOR:
        out.append(
            f"THIN STRATUM CELL ({s.arm}): the worst-covered stratum category reached "
            f"only {s.stratum_coverage_floor:.0%} of its target share in the raw draw "
            "before raking. Its weighted contribution is doing correspondingly more work."
        )
    if 0 < s.n_with_audience < CLUSTER_MIN_N:
        out.append(
            f"FEW CLUSTERS FOR APPROVAL CI ({s.arm}): only {s.n_with_audience} "
            "replications recorded an audience. The clustered confidence interval on "
            "approval treats each replication as one observation, so below "
            f"{CLUSTER_MIN_N} it is very wide and should be read as a caveat, not refused."
        )
    # M1 personas are given no record, so there is nothing for them to be outside of and a
    # zero rate is correct. Warning there would train the reader to ignore the warning.
    if (
        s.n_opinions
        and s.persona_method != "m1"
        and s.out_of_record_rate <= OUT_OF_RECORD_WARNING_RATE
    ):
        out.append(
            f"ESCAPE HATCH NOT FIRING ({s.arm}): out-of-record rate is "
            f"{s.out_of_record_rate:.1%}. A near-zero rate is a warning, not a success — "
            "it means personas are extrapolating past their record rather than declining."
        )
    if s.persona_method == "m1" and s.n_opinions:
        out.append(
            f"UNGROUNDED BY CONSTRUCTION ({s.arm}): M1 personas get a name and no record, "
            "so they cannot cite and cannot decline. A zero out-of-record rate here is "
            "expected, not a diagnostic failure."
        )
    if s.cache_enabled:
        out.append(
            "VARIANCE IS DECISION-STEP VARIANCE: caching is on, so theorist answers repeat "
            "across replications. This is variance given fixed advisory input, not "
            "whole-system variance (see the full_stack_variance arm)."
        )
    else:
        out.append(
            "VARIANCE IS WHOLE-SYSTEM: caching is off, so every stage varies per "
            "replication."
        )
    return out


@dataclass
class Delta:
    """One arm's contrast against the control. The only interpretable across-arm quantity."""

    arm: str
    control: str
    d_mean_rung: float
    d_p_nuclear: float
    #: ADR 0009. The weighted "approve or strongly approve" share, arm minus control.
    #: `None` unless both arms recorded an audience — an across-arm delta, the same shape
    #: as every other number here, unlike `mean_lean_shift`'s within-replication contrast.
    d_approval: float | None = None
    #: Clustered risk-difference CI on `d_approval` (ADR 0011): replications are the
    #: independent unit, not the citizens nested inside them.
    d_approval_interval: Interval | None = None
    #: Risk difference + Newcombe CI on `p_nuclear_use`/`p_deliberate_nuclear` — the
    #: headline outcome — and the other two named thresholds, arm minus control.
    d_nuclear_use_interval: Interval | None = None
    d_dont_rock_the_boat_interval: Interval | None = None
    d_nuclear_incredulity_interval: Interval | None = None
    d_deliberate_nuclear_interval: Interval | None = None


def _approve_share(s: ArmSummary) -> float | None:
    if not s.weighted_approval:
        return None
    return round(
        s.weighted_approval.get("strongly_approve", 0.0) + s.weighted_approval.get("approve", 0.0),
        4,
    )


def delta(arm: ArmSummary, control: ArmSummary) -> Delta:
    arm_share = _approve_share(arm)
    control_share = _approve_share(control)
    d_approval = (
        round(arm_share - control_share, 4)
        if arm_share is not None and control_share is not None
        else None
    )
    d_approval_interval = (
        combine_interval_diff(arm.approval_interval, control.approval_interval)
        if arm.approval_interval is not None and control.approval_interval is not None
        else None
    )
    def _diff(a: Interval | None, b: Interval | None) -> Interval | None:
        # `None` on a hand-built `ArmSummary` (a fixture, or one predating ADR 0011's
        # interval fields) rather than on any summary `summarise()` itself produces,
        # which always fills these in.
        return combine_interval_diff(a, b) if a is not None and b is not None else None

    return Delta(
        arm=arm.arm,
        control=control.arm,
        d_mean_rung=round(arm.mean_rung - control.mean_rung, 3),
        d_p_nuclear=round(arm.p_nuclear - control.p_nuclear, 4),
        d_approval=d_approval,
        d_approval_interval=d_approval_interval,
        d_nuclear_use_interval=_diff(arm.p_nuclear_use_interval, control.p_nuclear_use_interval),
        d_dont_rock_the_boat_interval=_diff(
            arm.p_dont_rock_the_boat_interval, control.p_dont_rock_the_boat_interval
        ),
        d_nuclear_incredulity_interval=_diff(
            arm.p_nuclear_incredulity_interval, control.p_nuclear_incredulity_interval
        ),
        d_deliberate_nuclear_interval=_diff(
            arm.p_deliberate_nuclear_interval, control.p_deliberate_nuclear_interval
        ),
    )


def _band_label(band: int, ladder: str) -> str:
    """A display label for one band/rung value under the given ladder."""
    if ladder == "kahn" and band in BAND_UNITS:
        name, threshold = BAND_UNITS[band]
        marker = f" <- {threshold}" if band == DELIBERATE_NUCLEAR_BAND and threshold else ""
        return f"band {band} ({name}){marker}"
    return f"rung {band}"


def _n_levels(ladder: str) -> int:
    table = RUNG_KAHN if ladder == "kahn" else RUNG_PROJECT
    return max(table.values()) + 1


def _histogram(distribution: dict[int, int], n: int, ladder: str, width: int = 22) -> list[str]:
    """The band/rung distribution as text. The distribution IS the result, so it leads."""
    if not distribution:
        return []
    peak = max(distribution.values())
    lines = []
    for level in range(_n_levels(ladder)):
        count = distribution.get(level, 0)
        bar = "#" * round(width * count / peak) if peak else ""
        label = _band_label(level, ladder)
        lines.append(f"    {label:<52} {bar:<{width}} {count:>5} ({count / n:>6.1%})")
    return lines


def _action_distribution_lines(dist: dict[str, int], n: int) -> list[str]:
    """The nominal `ActionType` distribution — the primary descriptive object
    (`docs/framework/ladder.md`): it loses nothing to banding."""
    if not dist:
        return []
    lines = ["    action distribution (nominal, the primary descriptive object):"]
    for action, count in sorted(dist.items(), key=lambda kv: -kv[1]):
        lines.append(f"      {action:<26} {count:>5} ({count / n:>6.1%})")
    return lines


def _loo_section(summaries: list[ArmSummary]) -> list[str]:
    """Per-theorist attribution, contrasted against the other exclusion arms.

    **The comparison is against the mean of the exclusion arms, not against baseline.**
    Every `loo_*` arm runs a panel one smaller than baseline, so a delta against baseline
    carries two things at once: this theorist's absence, and the panel being smaller.
    Contrasting the exclusion arms with each other holds panel size fixed, so what remains
    is *which* theorist is missing — the quantity the intervention was built to isolate.

    This is a causal contrast rather than an observational one. Routing correlates with
    question tags, which correlate with outcome, so an association between a theorist and
    an outcome proves nothing. Removing them and re-running is an intervention.

    What it measures is "what the panel produces without X", which includes whoever was
    promoted into the freed slot. That is the right quantity for a panel-design question
    and the wrong one for "X's marginal contribution holding all else fixed" — no
    leave-one-out design gives the latter.
    """
    loo = [s for s in summaries if s.arm.startswith(LOO_PREFIX)]
    if len(loo) < 2:
        return []

    grand_mean = statistics.fmean(s.mean_rung for s in loo)
    grand_nuclear = statistics.fmean(s.p_nuclear for s in loo)
    baseline = next((s for s in summaries if s.arm == "baseline"), None)

    out = ["", "=" * 78, "PER-THEORIST ATTRIBUTION (forced exclusion)", "=" * 78, ""]
    out.append(
        f"  Reference is the mean of the {len(loo)} exclusion arms, not baseline, so panel"
    )
    out.append("  size is held constant and only the identity of the missing theorist varies.")
    out.append(f"  Reference mean rung {grand_mean:.3f}, P(nuclear) {grand_nuclear:.1%}")
    out.append("")
    out.append(f"  {'theorist removed':<24}{'n':>5}{'d mean rung':>14}{'d P(nuclear)':>15}")

    for s in sorted(loo, key=lambda x: x.mean_rung - grand_mean):
        who = s.arm[len(LOO_PREFIX) :]
        out.append(
            f"  {who:<24}{s.n:>5}{s.mean_rung - grand_mean:>+14.3f}"
            f"{s.p_nuclear - grand_nuclear:>+15.2%}"
        )

    if baseline is not None:
        out += [
            "",
            f"  Cost of losing any one theorist: baseline (panel {baseline.declared_panel_size}) "
            f"mean rung {baseline.mean_rung:.3f}",
            f"  versus the exclusion mean (panel {loo[0].declared_panel_size}) "
            f"{grand_mean:.3f} — a difference of {baseline.mean_rung - grand_mean:+.3f}.",
            "  That contrast is panel size, not any particular theorist.",
        ]

    out += [
        "",
        f"  ! {len(loo)} exclusion arms against one baseline is a multiple-comparisons",
        "    exposure — you will find a most-influential theorist whether or not one",
        "    exists. This ranking is pre-registered as descriptive; it carries no",
        "    significance claim and no correction is applied. The same exposure applies",
        "    a second time to the four threshold outcomes reported above, run pairwise",
        "    across every arm: read that family descriptively too.",
        "  ! A null delta here is not evidence of no influence. It can also mean the",
        "    theorist was rarely consulted, so removing them changed few replications.",
        "    Read each row against how often that theorist was routed to in baseline.",
    ]
    return out


def audience_by_stratum(records: list[RunRecord]) -> dict[str, float]:
    """Weighted approve-or-strongly-approve share, broken down by stratum category (ADR
    0009). Keyed `"<dimension>:<category>"`.

    Descriptive only, and rendered by nothing yet — the same "tested, not surfaced" status
    ADR 0008 left `views.deliberation_flow` in. Reading any one cell as a finding without a
    multiple-comparisons correction is the same error the `loo_*` twelve-way comparison
    guards against: six dimensions times several categories each is a lot of chances to
    find a difference that is not there.
    """
    weight: dict[str, float] = {}
    approve_weight: dict[str, float] = {}
    for record in records:
        if record.audience is None:
            continue
        citizens = {c.citizen_id: c for c in record.audience.citizens}
        for response in record.audience.responses:
            if response.refused:
                continue
            citizen = citizens.get(response.citizen_id)
            if citizen is None:
                continue
            approve = response.approval.value in {"approve", "strongly_approve"}
            for dim in ("region", "urbanicity", "age_band", "sex", "education", "party_id"):
                key = f"{dim}:{getattr(citizen, dim)}"
                weight[key] = weight.get(key, 0.0) + citizen.weight
                if approve:
                    approve_weight[key] = approve_weight.get(key, 0.0) + citizen.weight
    return {
        key: round(approve_weight.get(key, 0.0) / total, 4) if total else 0.0
        for key, total in weight.items()
    }


def _interval_cell(interval: Interval | None, as_pct: bool = True) -> str:
    if interval is None:
        return "n/a"
    if as_pct:
        return f"{interval.point:+.2%} [{interval.lo:+.2%}, {interval.hi:+.2%}]"
    return f"{interval.point:+.3f} [{interval.lo:+.3f}, {interval.hi:+.3f}]"


def format_report(
    summaries: list[ArmSummary], paired: dict[str, PairedContrast] | None = None
) -> str:
    """Render the report, caveats included.

    The warnings are not an appendix. They are printed with the numbers because a rung
    distribution copied out of this output without them would be read as a claim about
    what nuclear strategists would do, which it is not.

    `paired`, when given, maps arm name -> `PairedContrast` against the control (built by
    `report_for_files` when seeds overlap) and is rendered alongside the unpaired delta,
    never instead of it.
    """
    if not summaries:
        return "no records to report\n"
    paired = paired or {}

    ordered = sorted(summaries, key=lambda s: (s.arm != CONTROL_ARM, s.arm))
    control = next((s for s in ordered if s.arm == CONTROL_ARM), None)

    out: list[str] = ["", "=" * 78, "ESCALATION BAND DISTRIBUTIONS", "=" * 78]

    for s in ordered:
        label = f"{s.arm}  (n={s.n}, ladder={s.ladder})" + (
            "   [CONTROL]" if s.arm == CONTROL_ARM else ""
        )
        out += ["", label, "-" * len(label)]
        out += _histogram(s.rung_distribution, s.n, s.ladder)
        out += _action_distribution_lines(s.action_distribution, s.n)
        out += [
            f"    mean rung {s.mean_rung}   median {s.median_rung}   "
            "(secondary: ordinal, not interval — see docs/framework/ladder.md)",
        ]
        # Threshold names are quoted from BAND_UNITS, the single source, rather than
        # typed out here a second time (docs/framework/ladder.md's own naming).
        dont_rock = BAND_UNITS[DONT_ROCK_THE_BOAT_BAND][1]
        incredulity = BAND_UNITS[NUCLEAR_INCREDULITY_BAND][1]
        no_nuclear_use = BAND_UNITS[DELIBERATE_NUCLEAR_BAND][1]
        out += [
            "    threshold crossings (headline outcomes):",
            f"      {dont_rock:<22}(band>={DONT_ROCK_THE_BOAT_BAND})  "
            f"{_interval_cell(s.p_dont_rock_the_boat_interval)} ({s.n_dont_rock_the_boat}/{s.n})",
            f"      {incredulity:<22}(band>={NUCLEAR_INCREDULITY_BAND}) "
            f"{_interval_cell(s.p_nuclear_incredulity_interval)} ({s.n_nuclear_incredulity}/{s.n})",
            f"      {no_nuclear_use:<22}(band>={DELIBERATE_NUCLEAR_BAND}) "
            f"{_interval_cell(s.p_deliberate_nuclear_interval)} "
            f"({s.n_deliberate_nuclear}/{s.n})  <-- headline",
            "      nuclear weapon employed (NUCLEAR_ACTIONS)   "
            f"{_interval_cell(s.p_nuclear_use_interval)} ({s.n_nuclear_use}/{s.n})",
        ]
        if s.consulted_panel:
            out.append(
                f"    panel {s.declared_panel_size} per run, {s.mean_run_coverage:.0%} "
                f"consulted per run, {s.distinct_personas} distinct across the sweep"
            )
            out.append(
                f"    opinions {s.n_opinions}   out-of-record {s.out_of_record_rate:.1%}   "
                f"citation integrity {s.citation_integrity:.1%} "
                f"({s.n_unsupported}/{s.n_citations} unsupported)"
            )
        else:
            out.append("    no panel consulted (control arm)")
        out.append(
            f"    backend={s.backend} grounded={s.grounded} corpus={s.corpus_tier} "
            f"cache={s.cache_enabled} retrieval={s.retrieval_mode}"
        )
        if s.n_with_lean:
            debate = (
                f", {s.mean_deliberation_rounds:.1f} rounds, "
                f"{s.abstention_rate:.0%} abstained"
                if s.mean_deliberation_rounds > 0
                else " (no debate — noise floor)"
            )
            out.append(
                f"    lean->decision: mean shift {s.mean_lean_shift:+.2f}, moved "
                f"{s.p_moved:.0%} ({s.p_moved_up:.0%} up / {s.p_moved_down:.0%} down)"
                f"{debate}"
            )
        if s.n_with_audience:
            approve = _approve_share(s) or 0.0
            out.append(
                f"    audience: {approve:.0%} approve {_interval_cell(s.approval_interval)}, "
                f"response {s.mean_response_rate:.0%}, no-opinion {s.mean_no_opinion_rate:.0%}, "
                f"refusal {s.mean_refusal_rate:.0%}, leakage {s.mean_leakage_rate:.1%}"
            )
        pc = paired.get(s.arm)
        if pc is not None:
            out.append(
                f"    paired vs {pc.control} (n={pc.n_pairs} matched seeds): "
                f"mean diff {pc.mean_diff:+.3f} {_interval_cell(pc.diff_interval, as_pct=False)}, "
                f"sign test p={pc.sign.p_two_sided:.4f}"
                + (
                    f", Wilcoxon p={pc.wilcoxon.p_two_sided:.4f}"
                    if pc.wilcoxon.reliable
                    else " (Wilcoxon unreliable below 20 pairs)"
                )
            )

    out += ["", "=" * 78, f"CONTRASTS AGAINST {CONTROL_ARM}", "=" * 78]
    if control is None:
        out += [
            "",
            f"  {CONTROL_ARM} is NOT PRESENT in this report.",
            "  Without it there is nothing interpretable here. Absolute escalation rates",
            "  are not a finding: base models escalate in wargame settings from neutral",
            "  starting conditions, so only the delta against the control means anything.",
        ]
    else:
        out += [
            "",
            f"  {'arm':<20}{'d mean rung':>13}{'d No-Nuc-Use risk diff':>26}{'d approval':>14}",
        ]
        for s in ordered:
            if s.arm == CONTROL_ARM:
                continue
            d = delta(s, control)
            approval_cell = (
                f"{d.d_approval:>+13.2%}" if d.d_approval is not None else f"{'n/a':>13}"
            )
            out.append(
                f"  {d.arm:<20}{d.d_mean_rung:>+13.3f}"
                f"{_interval_cell(d.d_deliberate_nuclear_interval):>26} {approval_cell}"
            )

    out += _loo_section(ordered)

    out += ["", "=" * 78, "HOW THIS MAY AND MAY NOT BE READ", "=" * 78, ""]
    out.append(
        "  Report deltas, never absolute rates. The absolute rung distribution from any\n"
        "  arm is not a finding about nuclear strategists (Rivera et al., FAccT 2024).\n"
        "  A single transcript is an anecdote; the distribution is the result.\n"
        "  Per-persona influence from observed routing is not reported: routing\n"
        "  correlates with question tags, which correlate with outcome, so it would be\n"
        "  observational and read as causal — the forced-exclusion section above, when\n"
        "  the report covers two or more loo_* arms, is the causal alternative."
    )
    out.append(
        "\n  mean/median rung are the weakest quantities here (docs/framework/ladder.md):\n"
        "  a published ladder does not make its spacing meaningful. Lead with the band\n"
        "  distribution, the nominal action distribution, and the named threshold-crossing\n"
        "  rates above."
    )
    if any(s.n_with_lean for s in ordered):
        out.append(
            "\n  lean->decision movement is a within-replication quantity, not a delta.\n"
            "  Absolute movement is not a finding — it carries the same base-rate confound.\n"
            "  The interpretable quantity is excomm_debate's mean shift MINUS baseline's:\n"
            "  baseline records the lean but runs no debate, so its movement is the\n"
            "  decision's own instability, and the excess is the deliberation effect."
        )
    if any(s.n_with_audience for s in ordered):
        out.append(
            "\n  Audience approval is read as d_approval against the control, exactly like\n"
            "  the rung — the absolute approve share is not a finding on its own, for the\n"
            "  same base-rate reason (Rivera et al.). Its interval is clustered at the\n"
            "  replication level, not the citizen: ~70 citizens per replication share\n"
            "  context and are not independent draws. By-stratum breakdowns\n"
            "  (metrics.audience_by_stratum) are descriptive; six dimensions times several\n"
            "  categories each is a multiple-comparisons exposure, and no correction is\n"
            "  applied here."
        )
    if paired:
        out.append(
            "\n  Paired contrasts block on the seed: perception draws its own rng stream\n"
            "  from the seed, so a matched pair isolates the arm's own effect from\n"
            "  seed-to-seed noise the unpaired delta above does not separate out."
        )

    seen: set[str] = set()
    for s in ordered:
        for warning in s.warnings:
            if warning not in seen:
                seen.add(warning)
                out.append(f"\n  ! {warning}")
    out.append("")
    return "\n".join(out)


def report_for_files(paths: list[Path], ladder: str | None = None) -> str:
    """Load every file, group by arm, and render one report.

    `ladder`, when given, re-scores every record under that ladder with no model call —
    `artsoc analyse --ladder kahn|project` (ADR 0011). When omitted, each record is scored
    under its own stamped ladder.
    """
    by_arm: dict[str, list[RunRecord]] = {}
    for path in paths:
        for record in load_jsonl(path):
            by_arm.setdefault(record.arm, []).append(record)
    summaries = [summarise(records, ladder=ladder) for records in by_arm.values()]
    control_records = by_arm.get(CONTROL_ARM)
    paired: dict[str, PairedContrast] = {}
    if control_records:
        for arm, records in by_arm.items():
            if arm == CONTROL_ARM:
                continue
            fn = (
                None
                if ladder is None
                else (lambda r, ladder=ladder: float(rung_for(r.action.action, ladder=ladder)))
            )
            pc = paired_contrast(records, control_records, value_fn=fn)
            if pc is not None:
                paired[arm] = pc
    return format_report(summaries, paired=paired)
