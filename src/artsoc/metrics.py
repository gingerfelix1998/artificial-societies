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
from dataclasses import dataclass, field
from pathlib import Path

from artsoc.schema import NUCLEAR_THRESHOLD, RunRecord

#: Below this ratio of consulted personas to declared panel size, the panel is nominal.
COVERAGE_WARNING_RATIO = 0.5

#: At or below this out-of-record rate, the escape hatch is suspected of not firing.
OUT_OF_RECORD_WARNING_RATE = 0.02

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

    #: Which model served each role. One distinct value across every role means a smoke
    #: test: the presidential decision is the primary metric, and serving it from the same
    #: cheap model as everything else changes what was measured, not just what it cost.
    models: dict[str, str] = field(default_factory=dict)

    warnings: list[str] = field(default_factory=list)


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
    citations = sum(len(o.citations) for o in opinions)
    unsupported = sum(len(r.unsupported_citations) for r in records)

    consulted = {p for r in records for p in r.personas_consulted}
    declared = max((r.panel_size for r in records), default=0)
    per_run = [
        len(r.personas_consulted) / r.panel_size for r in records if r.panel_size
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
        n_citations=citations,
        n_unsupported=unsupported,
        citation_integrity=round(1 - unsupported / citations, 4) if citations else 1.0,
        backend=first.backend,
        models=dict(first.models),
        grounded=first.grounded,
        cache_enabled=first.cache_enabled,
        retrieval_mode=first.retrieval_mode,
        consulted_panel=bool(first.opinions) or first.advisor_brief is not None,
        persona_method=str(first.config.get("persona_method", "unknown")),
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


def delta(arm: ArmSummary, control: ArmSummary) -> Delta:
    return Delta(
        arm=arm.arm,
        control=control.arm,
        d_mean_rung=round(arm.mean_rung - control.mean_rung, 3),
        d_p_nuclear=round(arm.p_nuclear - control.p_nuclear, 4),
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
            f"    backend={s.backend} grounded={s.grounded} cache={s.cache_enabled} "
            f"retrieval={s.retrieval_mode}"
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
        out += ["", f"  {'arm':<22}{'d mean rung':>14}{'d P(nuclear)':>16}"]
        for s in ordered:
            if s.arm == CONTROL_ARM:
                continue
            d = delta(s, control)
            out.append(f"  {d.arm:<22}{d.d_mean_rung:>+14.3f}{d.d_p_nuclear:>+16.2%}")

    out += _loo_section(ordered)

    out += ["", "=" * 78, "HOW THIS MAY AND MAY NOT BE READ", "=" * 78, ""]
    out.append(
        "  Report deltas, never absolute rates. The absolute rung distribution from any\n"
        "  arm is not a finding about nuclear strategists (Rivera et al., FAccT 2024).\n"
        "  A single transcript is an anecdote; the distribution is the result.\n"
        "  Per-persona influence is not reported: routing correlates with question tags,\n"
        "  which correlate with outcome, so it would be observational and read as causal."
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
