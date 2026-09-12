"""The statistics primitives added for ADR 0011, and the ladder-aware parts of `metrics.py`.

Every interval/test-statistic below is exact or a documented, named approximation —
Wilson score intervals and the sign test are closed-form and exact (stdlib
`statistics.NormalDist`/`math.comb`, no scipy); the Wilcoxon normal approximation names
its own reliability threshold rather than silently degrading. Worked numbers are computed
independently (not asserted from memory) and pinned here so a future change to the
formulas is caught rather than rationalised.
"""

from __future__ import annotations

import math

import pytest

from artsoc.metrics import (
    approval_shares,
    combine_interval_diff,
    matched_seed_pairs,
    mean_interval,
    paired_contrast,
    sign_test,
    summarise,
    wilcoxon_signed_rank,
    wilson_interval,
)
from artsoc.schema import (
    ActionType,
    Approval,
    AudienceRecord,
    Citizen,
    CitizenResponse,
    IntelBrief,
    PresidentialAction,
    RunRecord,
)


def _record(
    seed: int, action: ActionType, ladder: str = "kahn", arm: str = "baseline"
) -> RunRecord:
    act = PresidentialAction(action=action, justification="MOCK:", ladder=ladder)
    return RunRecord(
        run_id=f"{arm}-{seed}",
        arm=arm,
        seed=seed,
        started_at="2026-01-01T00:00:00Z",
        wall_time_s=0.0,
        config={},
        backend="mock",
        cache_enabled=True,
        retrieval_mode="stub",
        grounded=False,
        scenario_id="fixture",
        intel_brief=IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate"),
        action=act,
        rung=act.rung,
    )


def _audience_record(citizens: list[Citizen], responses: list[CitizenResponse]) -> AudienceRecord:
    weight = {c.citizen_id: c.weight for c in citizens}
    total = sum(weight.values())
    weighted: dict[str, float] = {}
    for r in responses:
        weighted[r.approval.value] = weighted.get(r.approval.value, 0.0) + weight[r.citizen_id]
    weighted = {k: v / total for k, v in weighted.items()}
    return AudienceRecord(
        frame="us_1962",
        sample_seed=1,
        citizens=citizens,
        responses=responses,
        weighted_approval=weighted,
        unweighted_approval=weighted,
        response_rate=1.0,
    )


def _record_with_audience(
    seed: int, audience: AudienceRecord, arm: str = "audience_d1"
) -> RunRecord:
    return _record(seed, ActionType.NO_ACTION, arm=arm).model_copy(update={"audience": audience})


# ---------------------------------------------------------------------------
# wilson_interval
# ---------------------------------------------------------------------------


def test_wilson_interval_matches_the_worked_example() -> None:
    result = wilson_interval(5, 100)
    assert result.point == pytest.approx(0.05)
    assert result.lo == pytest.approx(0.021544, abs=1e-5)
    assert result.hi == pytest.approx(0.111750, abs=1e-5)


def test_wilson_interval_clamps_at_the_boundaries() -> None:
    zero = wilson_interval(0, 30)
    assert zero.lo == pytest.approx(0.0, abs=1e-9)
    assert zero.hi == pytest.approx(0.1135, abs=1e-3)

    one = wilson_interval(30, 30)
    assert one.hi == 1.0
    assert one.lo == pytest.approx(0.8865, abs=1e-3)


def test_wilson_interval_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        wilson_interval(1, 0)
    with pytest.raises(ValueError):
        wilson_interval(5, 3)


# ---------------------------------------------------------------------------
# mean_interval / combine_interval_diff
# ---------------------------------------------------------------------------


def test_mean_interval_requires_at_least_two_values() -> None:
    with pytest.raises(ValueError):
        mean_interval([1.0])


def test_combine_interval_diff_is_the_risk_difference() -> None:
    d = combine_interval_diff(wilson_interval(20, 100), wilson_interval(5, 100))
    assert d.point == pytest.approx(0.15)
    assert d.lo == pytest.approx(0.05915, abs=1e-4)
    assert d.hi == pytest.approx(0.24328, abs=1e-4)


def test_combine_interval_diff_is_antisymmetric_under_swap() -> None:
    a, b = wilson_interval(20, 100), wilson_interval(5, 100)
    forward, backward = combine_interval_diff(a, b), combine_interval_diff(b, a)
    assert backward.point == pytest.approx(-forward.point)
    assert backward.lo == pytest.approx(-forward.hi)
    assert backward.hi == pytest.approx(-forward.lo)


def test_combine_interval_diff_is_zero_when_the_two_proportions_are_equal() -> None:
    same = wilson_interval(10, 50)
    assert combine_interval_diff(same, same).point == 0.0


def test_combine_interval_diff_reduces_to_the_two_sample_z_interval_for_symmetric_inputs() -> None:
    """For two `mean_interval`s (symmetric by construction) Newcombe's combination must
    equal the textbook `d +/- z*sqrt(SEa^2 + SEb^2)`, computed independently here."""
    a_values = [1.0, 2.0, 3.0, 4.0, 5.0]
    b_values = [2.0, 2.0, 2.0, 3.0, 3.0]
    a, b = mean_interval(a_values), mean_interval(b_values)
    combined = combine_interval_diff(a, b)

    import statistics

    z = statistics.NormalDist().inv_cdf(0.975)
    se_a = statistics.stdev(a_values) / math.sqrt(len(a_values))
    se_b = statistics.stdev(b_values) / math.sqrt(len(b_values))
    half = z * math.sqrt(se_a**2 + se_b**2)
    d = statistics.fmean(a_values) - statistics.fmean(b_values)

    assert combined.point == pytest.approx(d)
    assert combined.lo == pytest.approx(d - half)
    assert combined.hi == pytest.approx(d + half)


# ---------------------------------------------------------------------------
# sign_test / wilcoxon_signed_rank / paired_contrast
# ---------------------------------------------------------------------------


def test_sign_test_matches_the_worked_example() -> None:
    diffs = [1, 1, 1, -1, 2, 1, 0, 1, -1, 1]
    result = sign_test(diffs)
    assert (result.n, result.n_pos, result.n_neg) == (9, 7, 2)
    assert result.p_two_sided == pytest.approx(0.1796875)


def test_sign_test_with_no_nonzero_differences_is_not_significant() -> None:
    result = sign_test([0, 0, 0])
    assert result.p_two_sided == 1.0


def test_wilcoxon_signed_rank_is_unreliable_below_twenty_pairs() -> None:
    diffs = [1, 1, 1, -1, 2, 1, 0, 1, -1, 1]
    result = wilcoxon_signed_rank(diffs)
    assert result.n == 9
    assert result.statistic == pytest.approx(36.0)
    assert result.z == pytest.approx(1.6679, abs=1e-3)
    assert result.p_two_sided == pytest.approx(0.09534, abs=1e-4)
    assert result.reliable is False


def test_matched_seed_pairs_pairs_only_shared_seeds_in_order() -> None:
    a = [_record(s, ActionType.NO_ACTION, arm="a") for s in (3, 1, 2)]
    b = [_record(s, ActionType.NO_ACTION, arm="b") for s in (2, 4)]
    pairs = matched_seed_pairs(a, b)
    assert [x.seed for x, _ in pairs] == [2]


def test_matched_seed_pairs_rejects_a_duplicate_seed() -> None:
    a = [_record(1, ActionType.NO_ACTION, arm="a"), _record(1, ActionType.NO_ACTION, arm="a")]
    with pytest.raises(ValueError):
        matched_seed_pairs(a, [])


def test_paired_contrast_is_none_when_no_seeds_overlap() -> None:
    a = [_record(1, ActionType.NO_ACTION, arm="a")]
    b = [_record(2, ActionType.NO_ACTION, arm="b")]
    assert paired_contrast(a, b) is None


def test_paired_contrast_defaults_to_the_effective_ladder_band() -> None:
    treated = [_record(s, ActionType.NUCLEAR_DEMONSTRATION, arm="treated") for s in range(1, 6)]
    control = [_record(s, ActionType.NO_ACTION, arm="control") for s in range(1, 6)]
    pc = paired_contrast(treated, control)
    assert pc is not None
    assert pc.n_pairs == 5
    assert pc.mean_diff == pytest.approx(3.0)  # band 3 vs band 0, every seed
    assert "FEW MATCHED SEEDS" in pc.notes[0]


# ---------------------------------------------------------------------------
# Clustered vs naive approval CI (ADR 0011) — deterministic, no randomness.
# ---------------------------------------------------------------------------


def _unanimous_citizens(
    prefix: str, approval, n: int = 70
) -> tuple[list[Citizen], list[CitizenResponse]]:
    from artsoc.schema import PrimaryConcern

    citizens = [
        Citizen(
            citizen_id=f"{prefix}{i}",
            region="northeast",
            urbanicity="urban",
            age_band="30_44",
            sex="f",
            education="college",
            party_id="independent",
            weight=1.0,
        )
        for i in range(n)
    ]
    responses = [
        CitizenResponse(
            citizen_id=c.citizen_id, approval=approval, primary_concern=PrimaryConcern.OTHER
        )
        for c in citizens
    ]
    return citizens, responses


def test_the_clustered_approval_interval_is_much_wider_than_the_naive_pooled_one() -> None:
    """Citizens are nested within a replication and share its context, so pooling all
    ~70 x n citizens into one Wilson interval understates uncertainty relative to treating
    each replication's own share as one observation. Five replications unanimously approve
    and five unanimously disapprove — an extreme, fully deterministic within-replication
    correlation — to make the width difference unmissable without relying on randomness."""
    records = []
    for i in range(5):

        citizens, responses = _unanimous_citizens(f"a{i}_", Approval.STRONGLY_APPROVE)
        records.append(_record_with_audience(i, _audience_record(citizens, responses)))
    for i in range(5):

        citizens, responses = _unanimous_citizens(f"d{i}_", Approval.STRONGLY_DISAPPROVE)
        records.append(_record_with_audience(5 + i, _audience_record(citizens, responses)))

    shares = approval_shares(records)
    assert shares == [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    clustered = mean_interval(shares)
    total_approve = sum(
        1
        for r in records
        for resp in r.audience.responses
        if resp.approval.value == "strongly_approve"
    )
    total_citizens = sum(len(r.audience.responses) for r in records)
    naive = wilson_interval(total_approve, total_citizens)

    assert (clustered.hi - clustered.lo) > 5 * (naive.hi - naive.lo)


# ---------------------------------------------------------------------------
# summarise/ladder integration
# ---------------------------------------------------------------------------


def test_rescoring_the_same_records_under_each_ladder_gives_the_documented_bands() -> None:
    """`nuclear_demonstration`: band 3 under Kahn, rung 6 under the project table — the
    exact non-equivalence `docs/framework/ladder.md` is built around, reproduced end to
    end through `summarise`, not just at the raw table level."""
    records = [_record(s, ActionType.NUCLEAR_DEMONSTRATION, ladder="kahn") for s in range(1, 4)]
    kahn = summarise(records, ladder="kahn")
    project = summarise(records, ladder="project")
    assert kahn.rung_distribution == {3: 3}
    assert project.rung_distribution == {6: 3}
    assert kahn.p_deliberate_nuclear == 0.0
    assert kahn.p_nuclear_use == 1.0
    assert kahn.ladder == "kahn"
    assert project.ladder == "project"


def test_summarise_without_an_explicit_ladder_uses_each_records_own_ladder() -> None:
    old = _record(1, ActionType.NUCLEAR_DEMONSTRATION, ladder="project")
    new = _record(2, ActionType.NUCLEAR_DEMONSTRATION, ladder="kahn")
    mixed = summarise([old, new])
    assert mixed.ladder == "mixed"
    assert mixed.rung_distribution == {6: 1, 3: 1}
