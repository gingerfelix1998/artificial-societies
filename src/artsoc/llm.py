"""The single choke point for every model call, plus the offline mock backend.

Every prompt in the system passes through `LLMClient.complete`. That is what makes the
access matrix testable: a recorder wrapped around this one class sees every `(system,
prompt)` pair any role has ever been shown.

**The mock backend is deliberately content-nonsense.** Responses are shape-correct so the
loop runs, and their text is prefixed `MOCK:` so it can never be mistaken for real output
and written up as a finding. Do not make it plausible.

**The mock reads nothing but the prompt.** Where it needs a structured hint — how many
questions to produce, whether a corpus block was retrieved — that hint is a marker inside
the prompt, not a side channel argument. A side channel would be invisible to
`tests/test_access_matrix.py`, which scans prompts, and would therefore be a way for
scenario context to reach a theorist without any test noticing.

**Seeds must move the outcome.** The presidential decision is sampled from a weighted
distribution over the closed action space. If every seed produced the same action, Monte
Carlo would be measuring nothing.

A live backend belongs behind `get_backend`. There is no live backend in phase 1.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from artsoc.schema import ActionType

MOCK_PREFIX = "MOCK:"

#: Bumped whenever mock output changes shape. It is part of the cache key, so old cached
#: responses cannot be silently served against new parsing code.
MOCK_VERSION = "mock-1"


class Role(str, Enum):
    """Which step of the loop is calling. One prompt shape per role, no shared scratchpad."""

    INTEL_OFFICER = "intelligence_officer"
    PRESIDENT_QUERY = "president_query"
    ADVISOR_QUESTIONS = "advisor_questions"
    THEORIST = "theorist"
    ADVISOR_SYNTHESIS = "advisor_synthesis"
    PRESIDENT_DECISION = "president_decision"


def role_marker(role: Role) -> str:
    """The marker each role stamps into its own system prompt."""
    return f"[[ROLE:{role.value}]]"


def parse_role(system: str) -> Role:
    match = re.search(r"\[\[ROLE:([a-z_]+)\]\]", system)
    if not match:
        raise ValueError("system prompt carries no role marker; the backend cannot route it")
    try:
        return Role(match.group(1))
    except ValueError as exc:
        raise ValueError(f"unknown role marker {match.group(1)!r}") from exc


# Markers the mock reads out of the prompt. They are instructions a real model would also
# act on, expressed compactly enough for a deterministic stub to obey.
N_MARKER = re.compile(r"\[\[N:(\d+)\]\]")
NO_RECORD_MARKER = "[[CORPUS:none]]"
CONSENSUS_MARKER = "[[SYNTHESIS:consensus]]"
PASSAGE_ID = re.compile(r"\[([A-Za-z0-9_]+:[A-Za-z0-9_]+:\d+)\]")


#: Weighted sampling distribution for the mock's presidential decision.
#:
#: THESE WEIGHTS ARE INVENTED. They exist so that a Monte Carlo sweep produces a
#: distribution spanning several rungs rather than a point mass. They are not a prior, not
#: calibrated against anything, and no arm contrast computed over mock output is a
#: finding: arms differ here only because their prompts hash differently.
DECISION_WEIGHTS: dict[ActionType, float] = {
    ActionType.PRIVATE_REASSURANCE: 4.0,
    ActionType.NO_ACTION: 8.0,
    ActionType.PUBLIC_STATEMENT: 12.0,
    ActionType.PRIVATE_WARNING: 14.0,
    ActionType.DIPLOMATIC_SANCTION: 8.0,
    ActionType.PUBLIC_ULTIMATUM: 8.0,
    ActionType.FORCE_DISPERSAL: 12.0,
    ActionType.ALERT_LEVEL_RAISE: 12.0,
    ActionType.WEAPONS_TEST: 4.0,
    ActionType.FORWARD_DEPLOYMENT: 8.0,
    ActionType.CONVENTIONAL_STRIKE: 5.0,
    ActionType.NUCLEAR_DEMONSTRATION: 3.0,
    ActionType.NUCLEAR_LIMITED_STRIKE: 1.0,
    ActionType.NUCLEAR_COUNTERFORCE: 0.7,
    ActionType.NUCLEAR_COUNTERVALUE: 0.3,
}

#: A bounded bank of decontextualised analytical questions the mock Advisor draws from.
#:
#: Bounded on purpose. Theorist answers are cached on the question text, so a bank that
#: repeats across replications is what lets the cache demonstrate anything at all. Real
#: question formulation would be open-ended; this is a stub property, not a design claim.
#: Every entry carries MOCK_PREFIX verbatim, like every other mock product. A near-miss
#: marker such as "MOCK-Q1:" reads as mock to a human but not to the substring check that
#: keeps stub text out of a write-up, so the two must not drift apart.
QUESTION_BANK: tuple[tuple[str, tuple[str, ...]], ...] = (
    (f"{MOCK_PREFIX} Q1 placeholder question about force posture changes under uncertainty",
     ("posture", "survivability", "first_strike")),
    (f"{MOCK_PREFIX} Q2 placeholder question about what makes a threat believable",
     ("credibility", "deterrence", "coercion")),
    (f"{MOCK_PREFIX} Q3 placeholder question about reading intent from ambiguous movement",
     ("misperception", "signalling", "inadvertent_escalation")),
    (f"{MOCK_PREFIX} Q4 placeholder question about controlling escalation once begun",
     ("escalation", "escalation_control", "c2")),
    (f"{MOCK_PREFIX} Q5 placeholder question about organisational routine versus choice",
     ("organisational", "doctrine", "c2")),
    (f"{MOCK_PREFIX} Q6 placeholder question about constraints on use beyond deterrence",
     ("taboo", "norms", "deterrence")),
    (f"{MOCK_PREFIX} Q7 placeholder question about regional dynamics and third parties",
     ("regional", "proliferation", "signalling")),
    (f"{MOCK_PREFIX} Q8 placeholder question about visible restraint as a signal",
     ("signalling", "credibility", "escalation_control")),
)


class Backend(Protocol):
    """What a backend must provide. A live backend would implement exactly this."""

    name: str

    def complete(self, role: Role, system: str, prompt: str, seed_hint: str) -> str: ...


class MockBackend:
    """Deterministic, offline, obviously fake.

    Keyed on a hash of the system prompt, the user prompt and a seed hint, so the same
    call always returns the same text and different seeds return different text.
    """

    name = "mock"

    def complete(self, role: Role, system: str, prompt: str, seed_hint: str) -> str:
        digest = hashlib.sha256(
            "\x00".join([MOCK_VERSION, role.value, system, prompt, seed_hint]).encode("utf-8")
        ).hexdigest()
        rng = random.Random(int(digest[:16], 16))
        handler = {
            Role.INTEL_OFFICER: self._intel,
            Role.PRESIDENT_QUERY: self._query,
            Role.ADVISOR_QUESTIONS: self._questions,
            Role.THEORIST: self._theorist,
            Role.ADVISOR_SYNTHESIS: self._synthesis,
            Role.PRESIDENT_DECISION: self._decision,
        }[role]
        return json.dumps(handler(prompt, rng, digest))

    # -- one shape per role -------------------------------------------------------

    def _intel(self, prompt: str, rng: random.Random, digest: str) -> dict:
        n_events = prompt.count("EVENT ")
        return {
            "summary": f"{MOCK_PREFIX} placeholder intelligence summary {digest[:6]}",
            "assessed_activity": (
                f"{MOCK_PREFIX} placeholder assessment over {n_events} reported item(s); "
                "this text is not an assessment"
            ),
            "confidence": rng.choice(["low", "moderate", "high"]),
            "alternative_explanations": [
                f"{MOCK_PREFIX} placeholder alternative explanation A",
                f"{MOCK_PREFIX} placeholder alternative explanation B",
            ],
            "collection_gaps": [f"{MOCK_PREFIX} placeholder collection gap"],
        }

    def _query(self, prompt: str, rng: random.Random, digest: str) -> dict:
        return {
            "text": (
                f"{MOCK_PREFIX} placeholder decontextualised question to the advisor "
                f"{digest[:6]}"
            ),
            "concerns": [
                f"{MOCK_PREFIX} placeholder concern {rng.randint(1, 9)}",
                f"{MOCK_PREFIX} placeholder concern {rng.randint(10, 19)}",
            ],
        }

    def _questions(self, prompt: str, rng: random.Random, digest: str) -> dict:
        match = N_MARKER.search(prompt)
        n = int(match.group(1)) if match else 3
        n = max(1, min(n, len(QUESTION_BANK)))
        chosen = rng.sample(range(len(QUESTION_BANK)), n)
        return {
            "questions": [
                {"text": QUESTION_BANK[i][0], "tags": list(QUESTION_BANK[i][1])} for i in chosen
            ]
        }

    def _theorist(self, prompt: str, rng: random.Random, digest: str) -> dict:
        passage_ids = PASSAGE_ID.findall(prompt)
        no_record = NO_RECORD_MARKER in prompt

        # The escape hatch fires when nothing was retrieved, and occasionally even when
        # something was, because a question can fall outside a record that exists. A
        # decline rate pinned at zero would mean the hatch is not working.
        declines = no_record or (bool(passage_ids) and rng.random() < 0.15)
        if declines:
            return {
                "position": f"{MOCK_PREFIX} out of record — placeholder decline",
                "reasoning": f"{MOCK_PREFIX} placeholder: the retrieved record does not cover this",
                "citations": [],
                "out_of_record": True,
                "confidence": round(rng.uniform(0.1, 0.3), 2),
            }

        # Some grounded answers arrive with no citation at all. That is a real failure
        # mode and the citation-integrity metric has to be able to see it.
        cites: list[str] = []
        if passage_ids and rng.random() < 0.8:
            cites = rng.sample(passage_ids, min(len(passage_ids), rng.randint(1, 2)))

        return {
            "position": (
                f"{MOCK_PREFIX} placeholder position {rng.randint(1, 5)} — not a real claim"
            ),
            "reasoning": f"{MOCK_PREFIX} placeholder reasoning {digest[:6]}; content is nonsense",
            "citations": cites,
            "out_of_record": False,
            "confidence": round(rng.uniform(0.35, 0.9), 2),
        }

    def _synthesis(self, prompt: str, rng: random.Random, digest: str) -> dict:
        consensus_only = CONSENSUS_MARKER in prompt
        minority = (
            []
            if consensus_only
            else [
                f"{MOCK_PREFIX} placeholder minority position {rng.randint(1, 9)}",
                f"{MOCK_PREFIX} placeholder dissent {digest[:4]}",
            ]
        )
        return {
            "summary": f"{MOCK_PREFIX} placeholder advisory brief {digest[:6]}",
            "consensus_points": [
                f"{MOCK_PREFIX} placeholder consensus point 1",
                f"{MOCK_PREFIX} placeholder consensus point 2",
            ],
            "minority_positions": minority,
        }

    def _decision(self, prompt: str, rng: random.Random, digest: str) -> dict:
        actions = sorted(DECISION_WEIGHTS, key=lambda a: a.value)
        weights = [DECISION_WEIGHTS[a] for a in actions]
        action = rng.choices(actions, weights=weights, k=1)[0]
        return {
            "action": action.value,
            "justification": (
                f"{MOCK_PREFIX} placeholder justification {digest[:6]}; qualitative data only, "
                "and no part of it produced the action above"
            ),
        }


def get_backend(name: str) -> Backend:
    """Resolve a backend by name.

    A live model backend goes here, behind the same `Backend` protocol. There is none in
    phase 1 by design: the whole loop is built and its invariants pinned while responses
    are free, so nothing is being paid for while the architecture is still moving.
    """
    if name == "mock":
        return MockBackend()
    if name in {"api", "live", "anthropic"}:
        raise NotImplementedError(
            f"backend {name!r} is not implemented; phase 1 runs offline against the mock "
            "backend and adds no model-provider dependency"
        )
    raise ValueError(f"unknown backend {name!r}")


class DiskCache:
    """Content-addressed response cache.

    Keyed on the full call signature, so a change to any prompt, to the backend, or to the
    mock's shape version produces a different key rather than a stale hit.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> str | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["response"]
        except (OSError, ValueError, KeyError):
            return None

    def put(self, key: str, response: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"response": response}), encoding="utf-8")


@dataclass
class CallRecord:
    """One model call, as the access-matrix tests see it."""

    role: Role
    system: str
    prompt: str
    response: str
    cached: bool


@dataclass
class LLMClient:
    """Everything that talks to a model goes through here.

    Caching is an experimental choice, not an optimisation, and the setting is recorded in
    every output record:

    * **on**  — theorist answers repeat across replications of an arm, so the measured
      variance is variance in perception and in the decision step, given cached expert
      opinion.
    * **off** — every call is salted with the run seed, so every stage varies per
      replication and the measured variance is whole-system variance. The salt is the
      mock's stand-in for sampling temperature in a live backend; without it, turning the
      cache off would change call counts and nothing else, and `full_stack_variance` would
      be an arm that measures zero.
    """

    backend: Backend
    run_seed: int
    cache: DiskCache | None = None
    cache_enabled: bool = True
    calls: int = 0
    cache_hits: int = 0
    call_log: list[CallRecord] = field(default_factory=list)

    def complete(self, *, role: Role, system: str, prompt: str, cacheable: bool = True) -> str:
        # The declared role and the marker in the system prompt must agree. Role
        # differentiation that lives only in an argument would not be visible to the
        # backend or to the tests that scan prompts.
        if role_marker(role) not in system:
            raise ValueError(
                f"system prompt for {role.value} is missing its role marker; role "
                "differentiation must be present in the prompt itself"
            )

        salt = self._salt(cacheable)
        key = self._key(role, system, prompt, salt)
        use_cache = self.cache is not None and self.cache_enabled and cacheable

        if use_cache:
            hit = self.cache.get(key)  # type: ignore[union-attr]
            if hit is not None:
                self.calls += 1
                self.cache_hits += 1
                self.call_log.append(CallRecord(role, system, prompt, hit, cached=True))
                return hit

        response = self.backend.complete(role, system, prompt, salt)
        if use_cache:
            self.cache.put(key, response)  # type: ignore[union-attr]

        self.calls += 1
        self.call_log.append(CallRecord(role, system, prompt, response, cached=False))
        return response

    def _salt(self, cacheable: bool) -> str:
        if not self.cache_enabled:
            return f"seed={self.run_seed}"
        return "" if cacheable else f"seed={self.run_seed}"

    def _key(self, role: Role, system: str, prompt: str, salt: str) -> str:
        return hashlib.sha256(
            "\x00".join(
                [self.backend.name, MOCK_VERSION, role.value, system, prompt, salt]
            ).encode("utf-8")
        ).hexdigest()

    def prompts_for(self, role: Role) -> list[tuple[str, str]]:
        """Every `(system, prompt)` pair a given role has been shown."""
        return [(c.system, c.prompt) for c in self.call_log if c.role == role]
