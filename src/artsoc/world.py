"""The append-only world log and the per-nation perception filter.

Two boundaries live here.

**Write access.** Only the President writes to the world. The host injects the opening
event; everything after that is a presidential action. `WorldLog.write` refuses any other
author rather than trusting callers to be well behaved.

**Read access.** No agent reads the log directly. A nation reads it through its own
`PerceptionFilter`, which returns `PerceivedEvent` objects — a type with no
`ground_truth_detail` field. Misperception is therefore modelled rather than decorative:
an event can be observed late, observed partially, or missed entirely, and the analyst can
score the gap because the host still holds the truth the agents never saw.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from artsoc.schema import DoctrineCard, PerceivedEvent, PublicEvent, WorldEvent

PRESIDENT_ROLE = "president"
HOST_ROLE = "host"

#: Repo root, resolved from the installed-editable package location.
REPO_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = REPO_ROOT / "data" / "scenarios"


class WorldLog:
    """Append-only record of what has actually happened."""

    def __init__(self) -> None:
        self._events: list[WorldEvent] = []

    @property
    def events(self) -> tuple[WorldEvent, ...]:
        return tuple(self._events)

    def __len__(self) -> int:
        return len(self._events)

    def inject(self, event: WorldEvent) -> WorldEvent:
        """Host injection of a scenario event. Not available to any agent."""
        self._events.append(event)
        return event

    def write(self, event: WorldEvent, *, author_role: str) -> WorldEvent:
        """Append an agent-authored event.

        The President is the only role with write access to the world; other nations'
        Intelligence Officers read the consequences. Anything else is a design error, so
        it raises rather than being quietly dropped.
        """
        if author_role != PRESIDENT_ROLE:
            raise PermissionError(
                f"role {author_role!r} may not write to the world log; "
                "write access is the President's alone"
            )
        self._events.append(event)
        return event


def public_events_from(events: tuple[WorldEvent, ...] | list[WorldEvent]) -> list[PublicEvent]:
    """What was publicly known or announced, for the citizen audience (ADR 0009).

    Deliberately not a `PerceptionFilter` product: the audience is not a nation's
    collection apparatus and gets no `confidence`/`degraded`/collection reading — only
    `PublicEvent`'s bare `event_id`/`t`/`actor_nation`/`description`, dropping
    `ground_truth_detail`, `observable_signature`, `covert` and `action` explicitly. Use
    this on the injected scenario events, never on `PerceivedEvent`s.
    """
    return [
        PublicEvent(
            event_id=event.event_id,
            t=event.t,
            actor_nation=event.actor_nation,
            description=event.description,
        )
        for event in events
    ]


class PerceptionParams(BaseModel):
    """One nation's collection apparatus, as parameters rather than prose.

    The service's declared orientation lives on its `DoctrineCard.collection_bias` and
    appears in the Intelligence Officer's prompt on purpose — what a service is looking
    for shapes what it reports. `bias_keywords` is the same bias expressed mechanically:
    it decides which signature elements survive degraded collection.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    detection_prob: float = 0.92
    covert_detection_prob: float = 0.35
    delay_steps: int = 0
    noise_prob: float = 0.30
    bias_keywords: tuple[str, ...] = ()


class PerceptionFilter:
    """Turns the world log into one nation's necessarily partial view of it."""

    def __init__(self, nation: str, params: PerceptionParams) -> None:
        self.nation = nation
        self.params = params

    def view(
        self, log: WorldLog, now: int, rng: random.Random
    ) -> tuple[list[PerceivedEvent], list[str]]:
        """Return (what this nation sees, ids of events it failed to see).

        Own actions are always seen: a state knows what it did. Everything else is subject
        to delay, detection probability and collection noise.
        """
        seen: list[PerceivedEvent] = []
        missed: list[str] = []

        for event in log.events:
            if event.actor_nation == self.nation:
                seen.append(self._own(event, now))
                continue

            if event.t + self.params.delay_steps > now:
                # Not yet collected, reported or processed. Not a miss — just not here.
                continue

            p = self.params.covert_detection_prob if event.covert else self.params.detection_prob
            if rng.random() >= p:
                missed.append(event.event_id)
                continue

            degraded = rng.random() < self.params.noise_prob
            seen.append(self._foreign(event, now, degraded))

        return seen, missed

    # -- construction of the agent-visible objects ---------------------------------
    #
    # Every path below builds a PerceivedEvent field by field. There is deliberately no
    # bulk copy from WorldEvent: adding a host-only field to WorldEvent later cannot leak
    # through here by accident.

    def _own(self, event: WorldEvent, now: int) -> PerceivedEvent:
        return PerceivedEvent(
            event_id=event.event_id,
            t_occurred=event.t,
            t_observed=event.t,
            actor_nation=event.actor_nation,
            description=event.description,
            observable_signature=list(event.observable_signature),
            confidence=1.0,
            degraded=False,
            source_note="own action; not a collection product",
        )

    def _foreign(self, event: WorldEvent, now: int, degraded: bool) -> PerceivedEvent:
        signature = list(event.observable_signature)
        note = "collected"
        confidence = 0.9

        if degraded and signature:
            # Partial collection. What survives is biased towards what the service was
            # looking for, which is how a declared collection bias distorts a picture
            # without anyone lying.
            preferred = [s for s in signature if self._matches_bias(s)]
            other = [s for s in signature if not self._matches_bias(s)]
            keep = max(1, len(signature) // 2)
            signature = (preferred + other)[:keep]
            note = "partial collection; some signature elements not observed"
            confidence = 0.5

        return PerceivedEvent(
            event_id=event.event_id,
            t_occurred=event.t,
            t_observed=now,
            actor_nation=event.actor_nation,
            description=event.description,
            observable_signature=signature,
            confidence=confidence,
            degraded=degraded,
            source_note=note,
        )

    def _matches_bias(self, signature_item: str) -> bool:
        item = signature_item.lower()
        return any(k.lower() in item for k in self.params.bias_keywords)


class Scenario(BaseModel):
    """An injected event plus the presidential doctrine card.

    Held as a host-side object: `events` are `WorldEvent`s and therefore carry
    `ground_truth_detail`. Nothing here goes into a prompt unfiltered.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    scenario_id: str
    schema_version: str
    self_nation: str
    adversary_nation: str
    now: int
    doctrine_card: DoctrineCard
    perception: PerceptionParams
    events: list[WorldEvent]
    notes: list[str] = Field(default_factory=list, alias="_notes")

    def ground_truth(self) -> dict[str, str]:
        """The host's truth, for the output record only. Never for a prompt."""
        return {e.event_id: e.ground_truth_detail for e in self.events}


def load_scenario(scenario_id: str, scenario_dir: Path | None = None) -> Scenario:
    path = (scenario_dir or SCENARIO_DIR) / f"{scenario_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no scenario at {path}")
    return Scenario.model_validate(json.loads(path.read_text(encoding="utf-8")))


def build_world(scenario: Scenario) -> WorldLog:
    """A world log with the scenario's events injected by the host."""
    log = WorldLog()
    for event in scenario.events:
        log.inject(event)
    return log
