"""Generate a mock-backed session so the frontend can be developed without spending money.

`configs/base.yaml` currently declares a live backend, so every session started from the UI
bills the provider. Developing a chart against that is not reasonable, and neither is
developing it against no data at all.

**What this does and does not permit.** It loads committed arm configs and pins `backend:
mock` and `retrieval_mode: stub` onto them. That is the one place in the repository a
`RunConfig` is built outside `configs/`, and it is deliberately kept here rather than in
`session.py` or `api.py`:

* The API cannot reach it. A client may name committed arms and nothing else, so invariant
  11 is untouched — no UI control can produce this configuration.
* The records say so. `RunRecord.backend` is `"mock"`, `grounded` is false, and every
  response the UI builds from them carries the MOCK banner and the not-grounded warning.
  Mock output is `MOCK:`-prefixed nonsense by design, so a fixture sweep cannot later be
  read as a cheap live run.
* It is not a result and cannot be mistaken for one. Arms differ under the mock only
  because their prompts hash differently.

Usage: `make demo-fixture`, or `python scripts/demo_fixture.py --n 20`.
"""

from __future__ import annotations

import argparse
import sys

from artsoc import session as session_module
from artsoc.config import RunConfig
from artsoc.metrics import CONTROL_ARM
from artsoc.session import ProgressEvent, SessionSpec, run_session, session_dir

#: The control plus one full-loop arm: the minimum from which anything is interpretable.
DEFAULT_ARMS = [CONTROL_ARM, "baseline"]

DEFAULT_SCENARIO = "phase1_tel_dispersal_v1"


def _mock_loader():
    """`load_arm`, with the backend and retriever pinned for a free offline sweep."""
    real = session_module.load_arm

    def loader(name: str, *args: object, **kwargs: object) -> RunConfig:
        return real(name, *args, **kwargs).model_copy(
            update={"backend": "mock", "retrieval_mode": "stub"}
        )

    return loader


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="demo-fixture", description=__doc__)
    parser.add_argument("--n", type=int, default=20, help="replications per arm")
    parser.add_argument("--arms", nargs="+", default=DEFAULT_ARMS)
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--label", default="Mock fixture session")
    args = parser.parse_args(argv)

    spec = SessionSpec(
        label=args.label, scenario_id=args.scenario, arms=args.arms, n=args.n
    )

    # Patched on the module rather than passed in, because `session.run_session` resolves
    # arms itself — and it must, since that lookup is what stops a caller inventing a
    # configuration. This script is the deliberate exception, and it is loud about it.
    original = session_module.load_arm
    session_module.load_arm = _mock_loader()  # type: ignore[assignment]
    try:
        print(
            f"MOCK FIXTURE: {args.n} replications of {', '.join(args.arms)} on the mock "
            "backend.\nOutput is shape-correct and content-nonsense. No number from this "
            "session is a finding.\n"
        )
        state = run_session(spec, _report)
    finally:
        session_module.load_arm = original  # type: ignore[assignment]

    print(f"\n{state.status}: {session_dir(spec.session_id)}")
    print(f"session id {spec.session_id}")
    return 0 if state.status == "complete" else 1


def _report(event: ProgressEvent) -> None:
    if event.failure:
        print(f"  {event.arm}: FAILED {event.failure}", file=sys.stderr)
        return
    end = "\n" if event.completed == event.total else "\r"
    print(f"  {event.arm}: {event.completed}/{event.total}", end=end, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
