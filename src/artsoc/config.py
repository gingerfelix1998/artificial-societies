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
from artsoc.llm import DEFAULT_MODELS
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

#: How the panel for each question is chosen.
#:
#: `advisor` models the social act: the Advisor is shown who exists and what they work on,
#: picks by name, and states why. The reason is recorded.
#: `tag` is the mechanical control: deterministic overlap between question tags and
#: declared areas, no model involved, perfectly reproducible. Keeping it runnable means the
#: cost of modelling selection can be measured rather than assumed.
ROUTING_MODES: frozenset[str] = frozenset({"advisor", "tag"})


class RunConfig(BaseModel):
    """Everything that determines what a replication tests.

    Frozen and `extra="forbid"`: an unrecognised key in an arm file is a typo that would
    otherwise silently do nothing, which is the worst outcome — the arm would run, produce
    numbers, and not be testing what its filename claims.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    arm: str
    scenario_id: str = "phase1_tel_dispersal_v1"

    #: Not a CLI flag. See the module docstring. The mock is the default; a live backend
    #: is opted into here, never from the command line (ADR 0002).
    backend: str = "mock"

    #: Model per role, for a live backend. Ignored by the mock, which serves every role
    #: itself and records "mock" for all of them. Partial maps are merged over the
    #: defaults, so an arm can move one role without restating the rest.
    models: dict[str, str] = Field(default_factory=dict)

    #: Theorist calls fanned out at once. Operational, not experimental: a run must
    #: produce the same record at any setting, which a test pins. Theorist calls are
    #: independent by construction — they cannot see each other — so this is safe in a way
    #: most parallelisation is not.
    max_concurrency: int = Field(default=4, ge=1)

    #: Re-asks when a model returns something unparseable, and SDK retries on 429/5xx.
    #: At roughly 40,000 calls in a full sweep, both will happen.
    max_parse_retries: int = Field(default=2, ge=0)
    max_api_retries: int = Field(default=3, ge=0)

    #: Thinking depth for models that take adaptive thinking. Thinking tokens bill as
    #: output, and output already dominates this workload, so this is the main cost dial.
    effort: str = "medium"

    #: SMOKE TEST ONLY. Forces every role onto one model, superseding `models`.
    #:
    #: This exists to check the wiring — that credentials resolve, that every role returns
    #: parseable JSON, that the escape hatch fires, that a record round-trips — before any
    #: of that is paid for at Opus rates. It is not a cheap way to get results.
    #:
    #: Nothing produced under it is comparable to anything produced without it: the
    #: presidential decision is the primary metric, and serving it from the cheapest model
    #: changes what is being measured rather than only what it costs. `metrics` warns
    #: whenever a report contains such a run, and `artsoc run` warns before starting one.
    models_override: str | None = None

    #: An experimental choice, not an optimisation. With caching on, measured variance is
    #: variance in the decision step given fixed advisory input; with it off, it is
    #: whole-system variance. Both are legitimate and they answer different questions.
    cache_enabled: bool = True

    retrieval_mode: str = "stub"

    #: How many passages a theorist is shown. More context, more tokens.
    retrieval_top_k: int = Field(default=3, ge=1)

    #: Distinct content terms the best passage must share with the question before it is
    #: shown at all. This is the dial that decides the out-of-record rate, so it is
    #: experimental rather than operational: raise it and personas decline more.
    retrieval_min_terms: int = Field(default=1, ge=0)

    #: The same bar for the belief store. Lower by default because beliefs are single
    #: sentences and source chunks are ~150 words: an absolute term count is a much harder
    #: test for the short one, and applying one number to both meant the fallback never
    #: fired. None derives it as `retrieval_min_terms - 1`.
    retrieval_belief_min_terms: int | None = Field(default=None, ge=0)

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

    routing_mode: str = "advisor"

    #: Personas the world operates as though never existed. They are absent from the panel,
    #: from every roster the Advisor is shown, and from every prompt of every role — not
    #: merely unrouted. This is the forced-exclusion intervention that makes influence
    #: causal rather than observational.
    excluded_personas: list[str] = Field(default_factory=list)

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

    @field_validator("routing_mode")
    @classmethod
    def _known_routing(cls, value: str) -> str:
        if value not in ROUTING_MODES:
            raise ValueError(f"routing_mode {value!r} not in {sorted(ROUTING_MODES)}")
        return value

    @field_validator("excluded_personas")
    @classmethod
    def _excluded_are_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("excluded_personas contains duplicates")
        return value

    @field_validator("models")
    @classmethod
    def _known_roles(cls, value: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(value) - set(DEFAULT_MODELS))
        if unknown:
            raise ValueError(
                f"models names roles that do not exist: {unknown}; "
                f"valid roles: {sorted(DEFAULT_MODELS)}"
            )
        return value

    @field_validator("effort")
    @classmethod
    def _known_effort(cls, value: str) -> str:
        allowed = {"low", "medium", "high", "xhigh", "max"}
        if value not in allowed:
            raise ValueError(f"effort {value!r} not in {sorted(allowed)}")
        return value

    def resolved_models(self) -> dict[str, str]:
        """The model that will actually serve each role.

        One place computes this, so `sim`, `metrics` and the CLI cannot disagree about
        what a run is doing.
        """
        if self.models_override:
            return dict.fromkeys(DEFAULT_MODELS, self.models_override)
        return {**DEFAULT_MODELS, **self.models}

    @property
    def is_smoke_test(self) -> bool:
        """True when every role is pinned to one model by `models_override`."""
        return self.models_override is not None

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
