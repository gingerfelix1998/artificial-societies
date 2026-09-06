"""`RunConfig`, and the rule that an arm is a file rather than a flag.

Invariant 5: anything that changes *what is being tested* lives in `configs/arms/*.yaml`.
Only `--n`, `--seed0`, `--out-dir` and `--append` may be CLI-only, because those are
operational — how many replications to run and where to put them — rather than
experimental. A `--backend` flag would be an experimental switch wearing operational
clothes: it changes what produced the numbers, so it belongs in the config and is recorded
in every output record.

`RunConfig` is **frozen**. A run cannot mutate its own configuration part-way through, so
`RunRecord.config` describes what actually ran rather than what the config happened to look
like when the record was serialised.

Validation reuses the vocabularies that already exist — `personas.METHODS`,
`agents.SYNTHESIS_MODES` — rather than restating them here. A second copy of a list is a
second thing to forget to update.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from artsoc.agents import SYNTHESIS_MODES
from artsoc.personas import METHODS

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "configs"
ARMS_DIR = CONFIG_DIR / "arms"
BASE_CONFIG = CONFIG_DIR / "base.yaml"

#: Retrieval modes `retrieval.get_retriever` will accept. Named here so a config fails at
#: load rather than part-way through the first replication.
RETRIEVAL_MODES: frozenset[str] = frozenset({"stub", "corpus"})

#: Where a panel comes from. `synthetic` is the celebrity-effect control.
PANEL_SOURCES: frozenset[str] = frozenset({"registry", "synthetic"})


class RunConfig(BaseModel):
    """Everything that determines what a replication tests.

    Frozen and `extra="forbid"`: an unrecognised key in an arm file is a typo that would
    otherwise silently do nothing, which is the worst outcome — the arm would run, produce
    numbers, and not be testing what its filename claims.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm: str
    scenario_id: str = "phase1_tel_dispersal_v1"

    #: Not a CLI flag. See the module docstring.
    backend: str = "mock"

    #: An experimental choice, not an optimisation. With caching on, measured variance is
    #: variance in the decision step given fixed advisory input; with it off, it is
    #: whole-system variance. Both are legitimate and they answer different questions.
    cache_enabled: bool = True

    retrieval_mode: str = "stub"

    #: False for the control arm: President and intelligence brief, no advisor, no panel.
    consult_panel: bool = True

    persona_method: str = "m2"
    panel_source: str = "registry"

    #: The declared panel size. `metrics` compares it against the personas actually
    #: consulted, which is what gates the panel-size claim.
    panel_size: int = Field(default=15, ge=1)

    k_per_question: int = Field(default=4, ge=1)
    n_questions: int = Field(default=3, ge=1)

    synthesis_mode: str = "full_range"

    notes: str = ""

    @field_validator("persona_method")
    @classmethod
    def _known_method(cls, value: str) -> str:
        if value not in METHODS:
            raise ValueError(f"persona_method {value!r} not in {sorted(METHODS)}")
        return value

    @field_validator("synthesis_mode")
    @classmethod
    def _known_synthesis(cls, value: str) -> str:
        if value not in SYNTHESIS_MODES:
            raise ValueError(f"synthesis_mode {value!r} not in {sorted(SYNTHESIS_MODES)}")
        return value

    @field_validator("retrieval_mode")
    @classmethod
    def _known_retrieval(cls, value: str) -> str:
        if value not in RETRIEVAL_MODES:
            raise ValueError(f"retrieval_mode {value!r} not in {sorted(RETRIEVAL_MODES)}")
        return value

    @field_validator("panel_source")
    @classmethod
    def _known_panel_source(cls, value: str) -> str:
        if value not in PANEL_SOURCES:
            raise ValueError(f"panel_source {value!r} not in {sorted(PANEL_SOURCES)}")
        return value


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"no config at {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a mapping, got {type(loaded).__name__}")
    return loaded


def list_arms(arms_dir: Path | None = None) -> list[str]:
    """Every arm that has a config file, sorted."""
    target = arms_dir or ARMS_DIR
    return sorted(p.stem for p in target.glob("*.yaml"))


def load_arm(name: str, config_dir: Path | None = None) -> RunConfig:
    """Load one arm: the base defaults with that arm's overlay applied.

    A flat overlay on purpose. Nested merging would let an arm change one field of a nested
    block while appearing to leave the rest alone, and the diff between two arms is
    supposed to be readable at a glance.
    """
    root = config_dir or CONFIG_DIR
    base = _read_yaml(root / "base.yaml")
    overlay_path = root / "arms" / f"{name}.yaml"
    if not overlay_path.exists():
        available = ", ".join(list_arms(root / "arms")) or "none"
        raise FileNotFoundError(f"no arm {name!r} in {root / 'arms'}; available: {available}")
    overlay = _read_yaml(overlay_path)

    merged = {**base, **overlay}
    # The arm's identity comes from its filename, not from a field an overlay could set to
    # something else. A record labelled with the wrong arm is worse than no record.
    merged["arm"] = name
    return RunConfig.model_validate(merged)


def base_defaults(config_dir: Path | None = None) -> RunConfig:
    """The base configuration, for comparing what an arm actually varies."""
    root = config_dir or CONFIG_DIR
    return RunConfig.model_validate({**_read_yaml(root / "base.yaml"), "arm": "_base"})


def varied_fields(config: RunConfig, base: RunConfig | None = None) -> dict[str, Any]:
    """The fields in which an arm differs from base.

    Used by `artsoc arms` to show what each arm is actually testing, and by a test that
    refuses an arm identical to base — such an arm runs, produces numbers, and measures
    nothing.
    """
    reference = base or base_defaults()
    ignore = {"arm", "notes"}
    return {
        field: getattr(config, field)
        for field in RunConfig.model_fields
        if field not in ignore and getattr(config, field) != getattr(reference, field)
    }
