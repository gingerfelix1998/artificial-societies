"""The citizen audience: the committed sampling frame and its sampler (ADR 0009).

The audience is a **second, structurally different population** from the theorists in
`personas.py`: it is not the group this project models, and it is not an instrument that
feeds the President either (the ExComm in `personas.py` is that). It is an *outcome
measure* — a stratified sample of the public that reads the President's decision after it
is made and reacts to it. Nothing built here returns to any earlier stage of the loop.

**This module makes no model call and does not import `artsoc.llm`.** Same rule as
`personas.py`, for the same reason: sampling produces prompt *text* and stratum data, only
`agents.py` sends anything anywhere, and the access-matrix tests can inspect what a citizen
would be shown without a backend.

**A `Citizen` field with no marginal is not a persona attribute.** `load_frame` enforces
this both ways — a `strata.yaml` dimension with no matching `schema.Citizen` field, or a
`Citizen` field with no matching dimension, is a load-time error, the same discipline
`personas.py`'s tag-vocabulary contract holds theorist tags to.

**The sampler assumes independence across dimensions.** Each citizen's stratum values are
drawn independently, category by category, then raking weights correct the *weighted*
sample back to the target marginals. The true 1962 population's dimensions were
correlated (region and party identification, notably); this sampler does not model that
joint structure. See `data/society/us_1962/README.md` for the full statement of this
limitation and ADR 0009's Consequences section for why it was accepted for this pass.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import yaml

from artsoc.schema import Citizen

#: Repo root, resolved the same way `personas.py` and `world.py` do it.
REPO_ROOT = Path(__file__).resolve().parents[2]
SOCIETY_DIR = REPO_ROOT / "data" / "society"

#: RIM (iterative proportional) raking parameters. See `data/society/<frame>/README.md`
#: for the reasoning; a run whose achieved marginals still miss this tolerance after
#: convergence is a sign the sample is too small for the number of strata cells, not a bug
#: in the raking itself.
RAKING_TOLERANCE = 1e-4
RAKING_MAX_ITERATIONS = 25


@dataclass(frozen=True)
class Frame:
    """One committed sampling frame, loaded from `data/society/<name>/`."""

    name: str
    #: dimension name -> {category: target_share}. The construction input.
    dimensions: dict[str, dict[str, float]]
    #: dimension name -> {category: target_share}. Held out from construction; used only
    #: to compute `AudienceRecord.validation_distance`.
    validation_dimensions: dict[str, dict[str, float]]


@dataclass
class AudienceSample:
    """The drawn panel: weighted `Citizen`s, plus what the sampler can already say about
    how well the draw matches its targets."""

    citizens: list[Citizen]
    #: Unweighted — the raw draw, before raking. dimension -> {category: achieved_share}.
    achieved_marginals: dict[str, dict[str, float]]
    #: dimension -> {category: target_share}, carried alongside `achieved_marginals` so a
    #: caller does not have to re-open the frame to read what was being aimed at.
    target_marginals: dict[str, dict[str, float]]
    #: dimension -> the lowest achieved/target ratio of any category in that dimension.
    #: `1.0` would mean every category met or exceeded its target; well below `1.0` means
    #: some category is under-represented in the raw draw (raking corrects the weighted
    #: read, not the raw counts).
    stratum_coverage: dict[str, float]


def load_frame(frame: str, root: Path | None = None) -> Frame:
    """Load and cross-validate a committed sampling frame.

    Raises `FileNotFoundError` if the frame does not exist, and `ValueError` if
    `strata.yaml`'s dimensions and `schema.Citizen`'s fields have drifted apart, or if any
    dimension's shares do not sum to 1.0.
    """
    base = (root or SOCIETY_DIR) / frame
    strata_path = base / "strata.yaml"
    if not strata_path.exists():
        raise FileNotFoundError(f"no sampling frame at {strata_path}")

    strata = yaml.safe_load(strata_path.read_text(encoding="utf-8")) or {}
    dimensions = {
        name: dict(spec["categories"])
        for name, spec in (strata.get("dimensions") or {}).items()
    }

    citizen_fields = set(Citizen.model_fields) - {"citizen_id", "weight"}
    declared = set(dimensions)
    if declared != citizen_fields:
        missing_on_citizen = sorted(declared - citizen_fields)
        missing_in_frame = sorted(citizen_fields - declared)
        raise ValueError(
            f"{strata_path} and schema.Citizen have drifted: dimensions with no Citizen "
            f"field {missing_on_citizen}, Citizen fields with no dimension "
            f"{missing_in_frame}"
        )

    for name, categories in dimensions.items():
        total = sum(categories.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"{strata_path} dimension {name!r} sums to {total}, not 1.0")

    validation_path = base / "validation_targets.yaml"
    validation_raw: dict = {}
    if validation_path.exists():
        validation_raw = yaml.safe_load(validation_path.read_text(encoding="utf-8")) or {}
    validation_dimensions = {
        name: dict(spec["categories"])
        for name, spec in (validation_raw.get("dimensions") or {}).items()
    }

    return Frame(name=frame, dimensions=dimensions, validation_dimensions=validation_dimensions)


def sample_citizens(frame: Frame, n: int, rng: random.Random) -> AudienceSample:
    """Deterministic given `rng`. Draws `n` citizens, one stratum value per dimension each,
    independently (see the module docstring's independence-assumption note), then computes
    raking weights so the weighted panel matches `frame.dimensions` even though the raw
    draw does not."""
    dim_names = sorted(frame.dimensions)
    draws: list[dict[str, str]] = [
        {dim: _weighted_choice(frame.dimensions[dim], rng) for dim in dim_names}
        for _ in range(n)
    ]

    weights = _rake(draws, dim_names, frame.dimensions)

    citizens = [
        Citizen(citizen_id=f"c{idx:03d}", weight=weights[idx], **draws[idx])
        for idx in range(n)
    ]

    achieved = _tally(draws, dim_names)
    coverage = {
        dim: min(
            (
                (achieved[dim].get(cat, 0.0) / target) if target > 0 else 1.0
                for cat, target in frame.dimensions[dim].items()
            ),
            default=1.0,
        )
        for dim in dim_names
    }

    return AudienceSample(
        citizens=citizens,
        achieved_marginals=achieved,
        target_marginals={dim: dict(frame.dimensions[dim]) for dim in dim_names},
        stratum_coverage=coverage,
    )


def build_citizen_identity_prompt(citizen: Citizen) -> str:
    """Demographic and era context, with no reference to the crisis and no year (ADR
    0009). The scenario is anonymised to Nation A / Nation B for the same reason — naming
    the episode, or the year, is exactly the cue that lets a model retrieve how it ended."""
    age = citizen.age_band.replace("_", "-").replace("-plus", "+")
    return (
        "You are a member of the public, asked for your honest personal reaction to a "
        "national event — not as an expert, an official, or a commentator, just as "
        "someone like you would see it.\n\n"
        "ABOUT YOU:\n"
        f"- You live in the {citizen.region.replace('_', ' ')} region, in a "
        f"{citizen.urbanicity} area.\n"
        f"- You are in the {age} age group.\n"
        f"- Sex: {citizen.sex}.\n"
        f"- Education: {citizen.education.replace('_', ' ')}.\n"
        f"- Political leaning: {citizen.party_id}.\n\n"
        "Reason about the situation exactly as it is presented to you. Do not identify it "
        "with any named historical episode, and do not state or guess what year it is or "
        "how any such episode turned out — answer as someone living through this moment, "
        "without hindsight."
    )


def _weighted_choice(categories: dict[str, float], rng: random.Random) -> str:
    labels = list(categories.keys())
    weights = list(categories.values())
    return rng.choices(labels, weights=weights, k=1)[0]


def _tally(draws: list[dict[str, str]], dim_names: list[str]) -> dict[str, dict[str, float]]:
    """Unweighted per-dimension category shares, from the raw draw."""
    n = len(draws)
    result: dict[str, dict[str, float]] = {}
    for dim in dim_names:
        counts: dict[str, int] = {}
        for row in draws:
            counts[row[dim]] = counts.get(row[dim], 0) + 1
        result[dim] = {cat: count / n for cat, count in counts.items()} if n else {}
    return result


def _rake(
    draws: list[dict[str, str]], dim_names: list[str], targets: dict[str, dict[str, float]]
) -> list[float]:
    """Standard RIM (iterative proportional) weighting: cycle over dimensions, rescaling
    every citizen's weight by `target_share / achieved_weighted_share` for their category,
    until the maximum per-cell deviation is below `RAKING_TOLERANCE` or
    `RAKING_MAX_ITERATIONS` is reached. Weights are renormalised to sum to `n`."""
    n = len(draws)
    weights = [1.0] * n
    for _ in range(RAKING_MAX_ITERATIONS):
        max_deviation = 0.0
        for dim in dim_names:
            total_weight = sum(weights)
            if total_weight <= 0:
                continue
            weighted_share: dict[str, float] = {}
            for idx, row in enumerate(draws):
                weighted_share[row[dim]] = weighted_share.get(row[dim], 0.0) + weights[idx]
            weighted_share = {cat: w / total_weight for cat, w in weighted_share.items()}
            for idx, row in enumerate(draws):
                cat = row[dim]
                target_share = targets[dim].get(cat, 0.0)
                achieved_share = weighted_share.get(cat, 0.0)
                if achieved_share > 0:
                    weights[idx] *= target_share / achieved_share
                max_deviation = max(max_deviation, abs(target_share - achieved_share))
        if max_deviation < RAKING_TOLERANCE:
            break
    total = sum(weights)
    if total > 0:
        scale = n / total
        weights = [w * scale for w in weights]
    return weights
