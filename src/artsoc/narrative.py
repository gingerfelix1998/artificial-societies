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


# ---------------------------------------------------------------------------
# Session-level interpretation. Same constraints as the per-run narrative, one level up.
#
# The unit here is the distribution rather than the transcript, which is the level
# `docs/framework/measurement.md` says a claim may be made at. That does not make the output
# a finding: it is a reading of numbers that are themselves the finding, and it is labelled
# as such in the same way.
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM = (
    "You are a research assistant reading the output of a Monte Carlo simulation for an "
    "analyst. You state only what the figures show. You are reading summary statistics, "
    "not transcripts, and you have not been told what was really happening in the world."
)

ANALYSIS_RULES = """Rules you must follow, without exception:

- ONLY THE DELTA AGAINST THE CONTROL IS INTERPRETABLE. Off-the-shelf models escalate in
  wargame settings from neutral starting conditions, so an absolute escalation rate is the
  base model's prior, not a finding about nuclear strategists. Never present an absolute
  rate as a result. If no control arm was run, say that nothing here is interpretable.
- State no number that is not in the figures given to you. Do not compute new ones.
- Course-of-action support is not influence. It records whose opinions the Advisor cited
  when writing the option that was chosen. Causal attribution comes only from the loo_*
  forced-exclusion arms, and only when those arms were run.
- The President's justification is the reason it gave, recorded alongside the action. It
  did not determine the action. Never write that an outcome happened "because" of it.
- You do not know what was actually happening in the world. Do not say whether any
  assessment was correct.
- Every warning in the diagnostics gates how the numbers may be read. If one says the run
  is a mock or a smoke test, say plainly that nothing here is a finding."""

ANALYSIS_INSTRUCTION = f"""Write exactly three sentences describing how this society
responded, for someone who has not seen the figures.

1. What the panel did — how many were consulted, and how the panel behaved.
2. What the President chose, and how that compares to the control arm.
3. What is most notable about the distribution, or what prevents it being read at all.

{ANALYSIS_RULES}

Produce [[NARRATIVE:3]] sentences as JSON with key `sentences`, a list of exactly three
strings, and nothing else."""

ANSWER_INSTRUCTION = f"""Answer the analyst's question from the figures below.

{ANALYSIS_RULES}
- If the figures cannot answer the question, say so and say what would be needed. Do not
  reason past them.

Produce [[NARRATIVE:3]] sentences as JSON with key `sentences`, a list of strings, and
nothing else."""


class SessionAnalysis(BaseModel):
    """A stored three-sentence reading of one arm's distribution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    arm: str
    sentences: list[str] = Field(default_factory=list)
    model: str = ""
    caveat: str = (
        "Interpretation, not a finding. It reads the figures on this page and adds nothing "
        "to them; only contrasts against the control arm are interpretable, and every "
        "diagnostic above gates how they may be read."
    )


class AnalysisAnswer(BaseModel):
    """One answered follow-up question, stored so re-asking it costs nothing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    arm: str
    question: str
    answer: str = ""
    model: str = ""
    caveat: str = (
        "Interpretation of the figures on this page, not a finding, and not a new "
        "measurement. Nothing here feeds any metric."
    )


def build_analysis_context(payload: dict[str, Any]) -> str:
    """The figures block both session-level calls are given.

    Exposed so a test can scan it the way `tests/test_access_matrix.py` scans role prompts.
    Everything here is already-computed summary output — `metrics.ArmSummary`, `Delta`,
    `views.SessionFacts`, `views.CoaSupport` and the warnings. No record, no prompt, and no
    `host_ground_truth`: the caller assembles this from views that never held any of them.
    """
    return json.dumps(payload, indent=2, default=str)[:24000]


def summarise_session(
    payload: dict[str, Any], client: LLMClient, session_id: str, arm: str
) -> SessionAnalysis:
    """Three sentences on how the society responded across the sweep.

    Reuses the theorist role marker for the same reason `summarise_run` does: this is a
    host-side analysis call made after every run has finished, not a participant in the
    loop, and giving it a role of its own would place it inside the access matrix and imply
    an agent that never existed.
    """
    system = f"{role_marker(Role.THEORIST)} {ANALYSIS_SYSTEM}"
    prompt = f"{ANALYSIS_INSTRUCTION}\n\nFIGURES:\n{build_analysis_context(payload)}"
    raw = client.complete(role=Role.THEORIST, system=system, prompt=prompt, cacheable=True)
    try:
        sentences = [
            str(s).strip() for s in json.loads(raw).get("sentences", []) if str(s).strip()
        ]
    except (json.JSONDecodeError, AttributeError):
        sentences = []
    return SessionAnalysis(
        session_id=session_id,
        arm=arm,
        sentences=sentences[:3],
        model=client.backend.model_for(Role.THEORIST),
    )


def answer_question(
    question: str, payload: dict[str, Any], client: LLMClient, session_id: str, arm: str
) -> AnalysisAnswer:
    """Answer one analyst question from the same figures, and nothing else."""
    system = f"{role_marker(Role.THEORIST)} {ANALYSIS_SYSTEM}"
    prompt = (
        f"{ANSWER_INSTRUCTION}\n\nQUESTION:\n{question.strip()}\n\n"
        f"FIGURES:\n{build_analysis_context(payload)}"
    )
    raw = client.complete(role=Role.THEORIST, system=system, prompt=prompt, cacheable=True)
    # The same `sentences` contract the narratives use, rather than a second response shape
    # for one caller. `llm.NARRATIVE_MARKER` is what the mock reads to produce shape-correct
    # output, and a parallel key would have to be taught to it separately for no gain.
    try:
        answer = " ".join(
            str(s).strip() for s in json.loads(raw).get("sentences", []) if str(s).strip()
        )
    except (json.JSONDecodeError, AttributeError):
        answer = ""
    return AnalysisAnswer(
        session_id=session_id,
        arm=arm,
        question=question.strip(),
        answer=answer,
        model=client.backend.model_for(Role.THEORIST),
    )
