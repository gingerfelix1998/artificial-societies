"""`artsoc run` / `analyse` / `arms`.

**The flag list is an invariant, not a convenience.** Invariant 5 permits exactly four
CLI-only options — `--n`, `--seed0`, `--out-dir`, `--append` — because those are
operational: how many replications, from which seed, written where. Everything else
changes what is being tested and therefore lives in `configs/arms/*.yaml`, where it is
version-controlled, diffable, and recorded in every output record.

There is deliberately no `--backend` flag. It would be an experimental switch wearing
operational clothes: it changes what produced the numbers. `tests/test_configs.py` asserts
this parser exposes nothing beyond the four, so adding a fifth fails the suite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from artsoc.config import list_arms, load_arm, varied_fields
from artsoc.metrics import report_for_files
from artsoc.sim import DEFAULT_OUT_DIR, run_many, write_jsonl

#: The only options that may exist outside a config file. Asserted by a test.
PERMITTED_RUN_FLAGS: frozenset[str] = frozenset({"--n", "--seed0", "--out-dir", "--append"})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="artsoc",
        description=(
            "Phase 1: LLM persona panel simulating nuclear escalation decisions under "
            "Monte Carlo. Arms are config files, not flags."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("arms", help="list the experimental arms and what each varies")

    run = sub.add_parser(
        "run",
        help="run n replications of one arm",
        description=(
            "Everything experimental is in the arm's config file. The four options here "
            "are operational only (CLAUDE.md invariant 5)."
        ),
    )
    run.add_argument("arm", help="arm name, matching a file in configs/arms/")
    run.add_argument("--n", type=int, default=100, help="replications (default 100)")
    run.add_argument("--seed0", type=int, default=1, help="first seed (default 1)")
    run.add_argument("--out-dir", type=Path, default=None, help="output directory")
    run.add_argument("--append", action="store_true", help="append rather than overwrite")

    analyse = sub.add_parser("analyse", help="summarise one or more run outputs")
    analyse.add_argument("paths", nargs="+", type=Path, help="JSONL files from `artsoc run`")

    return parser


def cmd_arms() -> int:
    arms = list_arms()
    if not arms:
        print("no arms found in configs/arms/", file=sys.stderr)
        return 1
    print(f"{len(arms)} arms:\n")
    for name in arms:
        config = load_arm(name)
        varied = varied_fields(config)
        axis = ", ".join(f"{k}={v}" for k, v in varied.items()) or "base defaults"
        print(f"  {name:<22} {axis}")
        if config.notes:
            print(f"  {'':<22} {' '.join(config.notes.split())}")
        print()
    print("Arms are config files. To change what is tested, edit configs/arms/<name>.yaml.")
    return 0


def cmd_run(arm: str, n: int, seed0: int, out_dir: Path | None, append: bool) -> int:
    config = load_arm(arm)
    target = (out_dir or DEFAULT_OUT_DIR) / f"{arm}.jsonl"
    written = write_jsonl(run_many(config, n, seed0), target, append=append)
    print(f"{arm}: wrote {written} records to {target}")
    if config.backend == "mock":
        print(
            "  note: mock backend — output is shape-correct and content-nonsense. "
            "No number from this run is a finding."
        )
    return 0


def cmd_analyse(paths: list[Path]) -> int:
    print(report_for_files(paths))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "arms":
        return cmd_arms()
    if args.command == "run":
        return cmd_run(args.arm, args.n, args.seed0, args.out_dir, args.append)
    if args.command == "analyse":
        return cmd_analyse(args.paths)
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
