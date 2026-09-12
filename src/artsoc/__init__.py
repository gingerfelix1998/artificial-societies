"""artsoc — Phase 1 nuclear escalation persona-panel simulation.

The deliverable is a distribution over escalation rungs across many replications, plus
contrasts against the `escalation_prior` arm. A single transcript is not a result.
"""

from artsoc.schema import (
    BAND_UNITS,
    DELIBERATE_NUCLEAR_BAND,
    DONT_ROCK_THE_BOAT_BAND,
    NUCLEAR_ACTIONS,
    NUCLEAR_INCREDULITY_BAND,
    RUNG_KAHN,
    RUNG_PROJECT,
    SCHEMA_VERSION,
    TAG_VOCAB,
    ActionType,
    rung_for,
)

__version__ = "0.1.0"

__all__ = [
    "ActionType",
    "BAND_UNITS",
    "DELIBERATE_NUCLEAR_BAND",
    "DONT_ROCK_THE_BOAT_BAND",
    "NUCLEAR_ACTIONS",
    "NUCLEAR_INCREDULITY_BAND",
    "RUNG_KAHN",
    "RUNG_PROJECT",
    "SCHEMA_VERSION",
    "TAG_VOCAB",
    "rung_for",
    "__version__",
]
