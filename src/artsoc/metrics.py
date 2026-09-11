"""Outcome distributions, diagnostics, and the caveats that must travel with them.

The deliverable is a distribution over escalation rungs across replications plus contrasts
against `escalation_prior` — never a modal narrative and never a single transcript. One run
reaching a nuclear rung is an anecdote; "10% of 100 replications crossed the threshold" is
a result.

**The interpretation constraints are printed, not merely documented.** A number that
travels without its caveat is exactly how an absolute escalation rate becomes a finding
about nuclear strategists, which it is not: off-the-shelf models escalate in wargame
settings from neutral starting conditions (Rivera et al., FAccT 2024), so only the delta
against the control is interpretable. `format_report` therefore emits the warnings
alongside the numbers rather than leaving them to a reader who has `CLAUDE.md` open.

Three diagnostics exist to catch the project deceiving itself:

* **Panel coverage** gates the panel-size claim. If distinct personas consulted is far
  below the declared panel size, "15 personas" is nominal and must be restated.
* **A near-zero out-of-record rate is a warning, not a success.** It means the escape hatch
  is not firing and personas are extrapolating past their record.
* **Citation integrity** counts attributions to passages that were never shown.

Influence figures are deliberately absent. Routing correlates with question tags, which
correlate with outcome, so any per-persona influence number would be observational and
would be read as causal. Defensible attribution needs forced-inclusion and
forced-exclusion arms, which do not exist yet.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from artsoc.schema import NUCLEAR_THRESHOLD, RunRecord, rung_for

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
    #: landed. `lean_shift` is `rung(action) - rung(secret_lean)` per replication.
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
    #: The lowest per-dimension achieved/target coverage ratio seen across every
    #: replication with an audience. Below `AUDIENCE_COVERAGE_FLOOR` some stratum cell is
    #: under-represented badly enough that its raking weight is doing heavy lifting.
    stratum_coverage_floor: float = 0.0

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


def summarise(records: list[RunRecord]) -> ArmSummary:
    """Reduce one arm's records to a distribution plus diagnostics.

    Every record must belong to the same arm: mixing arms would average across the thing
    the experiment is trying to contrast.
    """
    arms = {r.arm for r in records}
    if len(arms) != 1:
        raise ValueError(f"summarise expects one arm, got {sorted(arms)}")

    rungs = [r.rung for r in records]
    distribution = dict(sorted(Counter(rungs).items()))

    opinions = [o for r in records for o in r.opinions]
    declined = sum(1 for o in opinions if o.out_of_record)
    # Corroboration is only defined where a claim index produced the position, so the
    # denominator is those positions and not every opinion — averaging a structural zero in
    # from the eight Wikipedia personas would drag the depth toward nothing and read as a
    # thin corpus rather than as a metric that does not apply.
    claim_based = [o for o in opinions if o.basis == "claims" and not o.out_of_record]
    citations = sum(len(o.citations) for o in opinions)
    unsupported = sum(len(r.unsupported_citations) for r in records)

    # ADR 0008. Only replications that recorded a lean contribute; the lean and the rung
    # both go through `rung_for`, so this is a ladder contrast, not a text one.
    with_lean = [r for r in records if r.secret_lean is not None]
    shifts = [r.rung - rung_for(r.secret_lean) for r in with_lean]
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

    first = records[0]
    summary = ArmSummary(
        arm=first.arm,
        n=len(records),
        rung_distribution=distribution,
        mean_rung=round(statistics.fmean(rungs), 3),
        median_rung=statistics.median(rungs),
        p_nuclear=round(sum(1 for r in rungs if r >= NUCLEAR_THRESHOLD) / len(rungs), 4),
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
        stratum_coverage_floor=round(min(coverage_values), 4) if coverage_values else 0.0,
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
    # ADR 0009. Four diagnostics gate the audience the way the three above gate the panel.
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
    """One arm's contrast against the control. The only interpretable quantity here."""

    arm: str
    control: str
    d_mean_rung: float
    d_p_nuclear: float
    #: ADR 0009. The weighted "approve or strongly approve" share, arm minus control.
    #: `None` unless both arms recorded an audience — an across-arm delta, the same shape
    #: as every other number here, unlike `mean_lean_shift`'s within-replication contrast.
    d_approval: float | None = None


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
    return Delta(
        arm=arm.arm,
        control=control.arm,
        d_mean_rung=round(arm.mean_rung - control.mean_rung, 3),
        d_p_nuclear=round(arm.p_nuclear - control.p_nuclear, 4),
        d_approval=d_approval,
    )


def _histogram(distribution: dict[int, int], n: int, width: int = 28) -> list[str]:
    """A rung distribution as text. The distribution IS the result, so it leads."""
    if not distribution:
        return []
    peak = max(distribution.values())
    lines = []
    for rung in range(0, 9):
        count = distribution.get(rung, 0)
        bar = "#" * round(width * count / peak) if peak else ""
        marker = " <- nuclear threshold" if rung == NUCLEAR_THRESHOLD else ""
        lines.append(f"    rung {rung} | {bar:<{width}} {count:>5} ({count / n:>6.1%}){marker}")
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
    multiple-comparisons correction is the same error the `loo_*` fifteen-way comparison
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


def format_report(summaries: list[ArmSummary]) -> str:
    """Render the report, caveats included.

    The warnings are not an appendix. They are printed with the numbers because a rung
    distribution copied out of this output without them would be read as a claim about
    what nuclear strategists would do, which it is not.
    """
    if not summaries:
        return "no records to report\n"

    ordered = sorted(summaries, key=lambda s: (s.arm != CONTROL_ARM, s.arm))
    control = next((s for s in ordered if s.arm == CONTROL_ARM), None)

    out: list[str] = ["", "=" * 78, "ESCALATION RUNG DISTRIBUTIONS", "=" * 78]

    for s in ordered:
        label = f"{s.arm}  (n={s.n})" + ("   [CONTROL]" if s.arm == CONTROL_ARM else "")
        out += ["", label, "-" * len(label)]
        out += _histogram(s.rung_distribution, s.n)
        out += [
            f"    mean rung {s.mean_rung}   median {s.median_rung}   "
            f"P(rung>={NUCLEAR_THRESHOLD}) {s.p_nuclear:.1%}",
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
                f"    audience: {approve:.0%} approve, response rate "
                f"{s.mean_response_rate:.0%}, no-opinion {s.mean_no_opinion_rate:.0%}, "
                f"leakage {s.mean_leakage_rate:.1%}"
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
        out += ["", f"  {'arm':<22}{'d mean rung':>14}{'d P(nuclear)':>16}{'d approval':>14}"]
        for s in ordered:
            if s.arm == CONTROL_ARM:
                continue
            d = delta(s, control)
            approval_cell = (
                f"{d.d_approval:>+13.2%}" if d.d_approval is not None else f"{'n/a':>13}"
            )
            out.append(
                f"  {d.arm:<22}{d.d_mean_rung:>+14.3f}{d.d_p_nuclear:>+16.2%} {approval_cell}"
            )

    out += _loo_section(ordered)

    out += ["", "=" * 78, "HOW THIS MAY AND MAY NOT BE READ", "=" * 78, ""]
    out.append(
        "  Report deltas, never absolute rates. The absolute rung distribution from any\n"
        "  arm is not a finding about nuclear strategists (Rivera et al., FAccT 2024).\n"
        "  A single transcript is an anecdote; the distribution is the result.\n"
        "  Per-persona influence is not reported: routing correlates with question tags,\n"
        "  which correlate with outcome, so it would be observational and read as causal."
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
            "  same base-rate reason (Rivera et al.). By-stratum breakdowns\n"
            "  (metrics.audience_by_stratum) are descriptive; six dimensions times several\n"
            "  categories each is a multiple-comparisons exposure, and no correction is\n"
            "  applied here."
        )

    seen: set[str] = set()
    for s in ordered:
        for warning in s.warnings:
            if warning not in seen:
                seen.add(warning)
                out.append(f"\n  ! {warning}")
    out.append("")
    return "\n".join(out)


def report_for_files(paths: list[Path]) -> str:
    """Load every file, group by arm, and render one report."""
    by_arm: dict[str, list[RunRecord]] = {}
    for path in paths:
        for record in load_jsonl(path):
            by_arm.setdefault(record.arm, []).append(record)
    return format_report([summarise(records) for records in by_arm.values()])
