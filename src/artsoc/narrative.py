"""A three-sentence orientation for one replication.

Its own module rather than a function in `views.py`, so the view layer keeps the property
that it makes no model call and is a pure projection of a record.

**This is interpretation, not a finding.** `docs/framework/measurement.md` is explicit that
the distribution over replications is the result and one transcript is an anecdote — a
readable narrative about a single run is precisely the modal narrative that warns against.
It ships beside `views.RunFacts`, which carries every number, so the prose never has to
state a count it could get wrong, and the UI labels it as interpretation.

**It never sees `host_ground_truth`.** The record it is given has already had that field
removed. A summary that quietly knew what was really happening would read as something the
simulation determined, when it is something the host stipulated so misperception could be
scored afterwards.

**It reports the justification as the reason the President gave, never as the cause.**
`schema.PresidentialAction` documents the justification as qualitative data that never fed
the rung. A sentence saying the outcome happened *because* of it would assert a causal
claim the design declines to make.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from artsoc.llm import LLMClient, Role, role_marker

SYSTEM = (
    "You summarise one replication of a simulation for an analyst reading its record. "
    "You state only what the record shows. You never speculate about what was really "
    "happening, and you have not been told."
)

INSTRUCTION = """Write exactly three sentences about this replication.

1. What the nation's intelligence apparatus perceived, and with what stated confidence.
2. What the advisory panel provided — how many were consulted, how many declined, and what
   the brief carried forward.
3. What the President did, and the reason it gave.

Rules:

- State only what appears below. Invent nothing, and give no number the record does not.
- The President's justification is THE REASON IT GAVE. It is recorded alongside the action
  and did not determine it. Write "gave as its reason" or "justified this by"; never write
  that the outcome happened "because" of anything.
- You do not know what was actually happening in the world, only what was perceived. Do not
  say whether the assessment was correct.

Produce [[NARRATIVE:3]] sentences as JSON with key `sentences`, a list of exactly three
strings, and nothing else."""


class RunNarrative(BaseModel):
    """A stored three-sentence summary, tied to the run it describes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The replication this describes. A narrative shown against a different run would be
    #: worse than none, so the reader is checked against this rather than assumed.
    run_id: str
    arm: str
    sentences: list[str] = Field(default_factory=list)
    model: str = ""
    #: Carried into the payload so the label cannot be dropped by a caller that forgets it.
    caveat: str = (
        "Interpretation, not a finding. One replication is an anecdote; the distribution "
        "over replications is the result. Generated from the agent-visible record only."
    )


def _agent_visible(record: Any) -> dict[str, Any]:
    """The record as an agent-side reader would see it, with the host's truth removed."""
    payload = record.model_dump(mode="json")
    payload.pop("host_ground_truth", None)
    return payload


def build_prompt(record: Any) -> str:
    """The user prompt, with ground truth already stripped.

    Exposed so a test can scan it the way `tests/test_access_matrix.py` scans role prompts.
    A leak here would not reach an agent — the run is over — but it would put the host's
    truth into a summary a reader takes as the simulation's own account.
    """
    return f"{INSTRUCTION}\n\nRECORD:\n{json.dumps(_agent_visible(record), indent=2)[:24000]}"


def summarise_run(record: Any, client: LLMClient, arm: str) -> RunNarrative:
    """Generate the narrative for one replication.

    Reuses the theorist role marker rather than adding a role to `llm.Role`: this is a
    host-side analysis call made after the run has finished, not a participant in the loop,
    and giving it a role of its own would put it inside the access matrix where it would
    imply an agent that never existed.
    """
    system = f"{role_marker(Role.THEORIST)} {SYSTEM}"
    raw = client.complete(
        role=Role.THEORIST, system=system, prompt=build_prompt(record), cacheable=True
    )
    try:
        sentences = [str(s).strip() for s in json.loads(raw).get("sentences", []) if str(s).strip()]
    except (json.JSONDecodeError, AttributeError):
        sentences = []
    return RunNarrative(
        run_id=record.run_id,
        arm=arm,
        sentences=sentences[:3],
        model=client.backend.model_for(Role.THEORIST),
    )
