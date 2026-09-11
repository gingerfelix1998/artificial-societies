"""Dump the pydantic models the frontend consumes as JSON Schema.

The frontend's TypeScript types are **generated** from these, never hand-written. A
hand-maintained copy of `RunRecord` drifts from the schema the moment a field moves, and
the drift surfaces as a blank panel rather than as an error — which is the worst kind of
failure to debug, because the page still renders.

`metrics.ArmSummary` and `metrics.Delta` are stdlib dataclasses rather than pydantic
models. `TypeAdapter` produces schema for those too, so they are covered here without a
mirror class in this file that could disagree with the original.

Usage: `python scripts/dump_schema.py <output-dir>` — see `make types`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from artsoc import metrics, narrative, schema, session, views
from artsoc.config import RunConfig

#: One file per model. Names match the TypeScript type they become.
PYDANTIC_MODELS: dict[str, Any] = {
    "RunRecord": schema.RunRecord,
    "PerceivedEvent": schema.PerceivedEvent,
    "IntelBrief": schema.IntelBrief,
    "PresidentialQuery": schema.PresidentialQuery,
    "AnalyticalQuestion": schema.AnalyticalQuestion,
    "RoutingRecord": schema.RoutingRecord,
    "TheoristOpinion": schema.TheoristOpinion,
    "AdvisorBrief": schema.AdvisorBrief,
    "PresidentialAction": schema.PresidentialAction,
    "RunConfig": RunConfig,
    "LoopStep": views.LoopStep,
    "ProvenanceFlow": views.ProvenanceFlow,
    "CoaSupport": views.CoaSupport,
    "SessionFacts": views.SessionFacts,
    "InteractionGraph": views.InteractionGraph,
    "RepresentativeRun": views.RepresentativeRun,
    "EngagementSummary": views.EngagementSummary,
    "PipelineFlow": views.PipelineFlow,
    "SessionSpec": session.SessionSpec,
    "SessionState": session.SessionState,
    "SessionSummary": session.SessionSummary,
    "CallEstimate": session.CallEstimate,
    "ProgressEvent": session.ProgressEvent,
    "ChatTurn": session.ChatTurn,
    "RunNarrative": narrative.RunNarrative,
    "SessionAnalysis": narrative.SessionAnalysis,
    "AnalysisAnswer": narrative.AnalysisAnswer,
}

#: Dataclasses from `metrics`. Converting them to pydantic to serialise them would touch a
#: core module for a client's benefit; a TypeAdapter reads them as they are.
DATACLASSES: dict[str, Any] = {
    "ArmSummary": metrics.ArmSummary,
    "Delta": metrics.Delta,
}


def _api_models() -> dict[str, Any]:
    """Response models that live in `api.py`, which needs the optional extra.

    Required rather than skipped. Generating a partial type file would leave the client's
    own response types hand-written, which is the drift this whole path exists to prevent —
    and it would fail as a blank panel rather than as a build error.
    """
    try:
        from artsoc import api
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise SystemExit(
            "the api extra is not installed, so the frontend's response types cannot be "
            "generated. Run `make install-api` first."
        ) from exc

    return {
        "ScenarioInfo": api.ScenarioInfo,
        "ArmInfo": api.ArmInfo,
        "SessionCreated": api.SessionCreated,
        "RepresentativeView": api.RepresentativeView,
        "PassageLookup": api.PassageLookup,
        "LandingView": api.LandingView,
        "RosterEntry": api.RosterEntry,
    }


def dump(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # Serialization mode, not the default validation mode. The frontend consumes records
    # that have been *written*, and computed fields — `RoutingRecord.selected`,
    # `PresidentialAction.rung` — are dumped but are not inputs. A validation schema omits
    # them, so a client typed from it cannot see the field the record plainly contains.
    for name, model in {**PYDANTIC_MODELS, **_api_models()}.items():
        written.append(_write(out_dir, name, model.model_json_schema(mode="serialization")))
    for name, model in DATACLASSES.items():
        written.append(
            _write(out_dir, name, TypeAdapter(model).json_schema(mode="serialization"))
        )

    return written


def _write(out_dir: Path, name: str, body: dict[str, Any]) -> Path:
    # `title` is what json-schema-to-typescript names the exported interface, so it is set
    # explicitly rather than left to whatever pydantic inferred.
    body["title"] = name
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    written = dump(Path(args[0]))
    print(f"wrote {len(written)} schema files to {args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
