"""`artsoc run` / `analyse` / `arms` / `ingest` / `rescore`.

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

from artsoc.config import LADDERS, base_defaults, list_arms, load_arm, varied_fields
from artsoc.ingest import ingest_all
from artsoc.llm import DiskCache, LLMClient, get_backend
from artsoc.metrics import report_for_files
from artsoc.personas import load_registry
from artsoc.retrieval import CORPUS_ROOT
from artsoc.sim import CACHE_DIR, DEFAULT_OUT_DIR, run_many, write_jsonl

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

    sub.add_parser(
        "ingest",
        help="build each persona's corpus from its declared source",
        description=(
            "Builds one store per persona into data/corpora/, from the source its "
            "registry entry declares. `markdown` personas are chunked and claim-indexed "
            "from data/corpora-src/ with no network and no model call; `wikipedia` "
            "personas are fetched, chunked, and given a generated belief store. "
            "Re-running produces identical passage ids from identical text (ADR 0003)."
        ),
    )

    analyse = sub.add_parser("analyse", help="summarise one or more run outputs")
    analyse.add_argument("paths", nargs="+", type=Path, help="JSONL files from `artsoc run`")

    rescore = sub.add_parser(
        "rescore",
        help="summarise existing run outputs under a chosen escalation ladder",
        description=(
            "Re-scores already-collected records under `--ladder`, with no model call: "
            "`PresidentialAction.rung` is recomputed from the stored `action`, ignoring "
            "whichever ladder each record was originally stamped with (ADR 0011). This is "
            "a deterministic, host-side re-reading of fixed data, not a new experiment — "
            "see docs/framework/ladder.md."
        ),
    )
    rescore.add_argument("paths", nargs="+", type=Path, help="JSONL files from `artsoc run`")
    rescore.add_argument(
        "--ladder",
        choices=sorted(LADDERS),
        default="kahn",
        help="escalation ladder to re-score against (default kahn)",
    )

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
    if config.is_smoke_test and config.backend != "mock":
        # Printed before the first call, not after the bill. A smoke test that is mistaken
        # for a real run is worse than one that never happened.
        print(
            f"  SMOKE TEST: models_override pins every role to {config.models_override}, "
            "including the presidential decision.\n"
            "  This checks the wiring. Nothing it produces is comparable to a normal run.\n"
            "  Remove models_override from configs/base.yaml before collecting results."
        )
    target = (out_dir or DEFAULT_OUT_DIR) / f"{arm}.jsonl"
    failures: list[tuple[int, str]] = []
    records = list(run_many(config, n, seed0, failures))
    written = write_jsonl(records, target, append=append)
    print(f"{arm}: wrote {written} records to {target}")

    if failures:
        # Reported with their seeds, never silently dropped. A replication may fail for
        # reasons correlated with its outcome, so a distribution over the survivors is
        # biased unless the reader can see how many were lost and re-run them.
        print(f"  {len(failures)} of {n} replications FAILED and are not in the output:")
        for seed, reason in failures[:5]:
            print(f"    seed {seed}: {reason[:110]}")
        if len(failures) > 5:
            print(f"    ... and {len(failures) - 5} more")
        print("  Re-run individually with --seed0 <seed> --n 1 to reproduce.")

    spend = sum(r.est_cost_usd for r in records)
    if spend:
        tin = sum(v[0] for r in records for v in r.token_usage.values())
        tout = sum(v[1] for r in records for v in r.token_usage.values())
        print(
            f"  billed {tin:,} in / {tout:,} out tokens across "
            f"{sum(r.llm_calls - r.cache_hits for r in records)} calls\n"
            f"  estimated ${spend:.4f} (published rates, not an invoice) "
            f"-- ${spend / max(written, 1):.4f} per replication"
        )
    if config.backend == "mock":
        print(
            "  note: mock backend — output is shape-correct and content-nonsense. "
            "No number from this run is a finding."
        )
    return 0


def cmd_ingest() -> int:
    personas = load_registry()
    config = base_defaults()

    # A backend is needed only to generate belief stores for `wikipedia` personas. When
    # every persona is `markdown` the whole ingest is offline and model-free, so no client
    # is constructed — that also means a live backend in base.yaml is never touched by a
    # markdown-only ingest.
    needs_client = any(p.corpus_source == "wikipedia" for p in personas)
    client = (
        LLMClient(
            backend=get_backend(config.backend, config.resolved_models(), effort=config.effort),
            run_seed=0,
            cache=DiskCache(CACHE_DIR),
            cache_enabled=True,
        )
        if needs_client
        else None
    )

    by_source: dict[str, int] = {}
    for p in personas:
        by_source[p.corpus_source] = by_source.get(p.corpus_source, 0) + 1
    mix = ", ".join(f"{n} {src}" for src, n in sorted(by_source.items()))
    tail = f", then beliefs via {config.backend}" if needs_client else ""
    print(f"ingesting {len(personas)} personas ({mix}){tail}\n")

    manifests, failures = ingest_all(personas, client=client)

    for m in sorted(manifests, key=lambda x: x["persona_id"]):
        state = "reused" if m.get("reused") else "built"
        if m.get("corpus_source") == "markdown":
            detail = f"{m['n_chunks']:>3} chunks  {m.get('n_claims', 0):>3} claims"
        else:
            detail = (
                f"{m['n_chunks']:>3} chunks  {len(m.get('abstracts', [])):>2} abstracts  "
                f"{m.get('n_beliefs', 0):>2} beliefs"
            )
        print(f"  {m['persona_id']:<14} {state:<6} {m.get('corpus_source', '?'):<10} {detail}")
    for persona_id, reason in failures:
        # Reported, never swallowed: a persona with no corpus declines every question, and
        # an analyst reading a 0% contribution needs to know it was a missing page.
        print(f"  {persona_id:<14} FAILED — {reason}", file=sys.stderr)

    reused = sum(1 for m in manifests if m.get("reused"))
    print(
        f"\n{len(manifests) - reused} built, {reused} reused from disk, "
        f"{len(failures)} failed -> {CORPUS_ROOT}"
    )
    if manifests:
        print(
            "  `markdown` personas are rebuilt every time (offline and free). A complete "
            "`wikipedia`\n  store is reused rather than refetched — delete its directory to "
            "force one. Either way,\n  a source-text change rewrites passage ids and "
            "invalidates stored citations (ADR 0003)."
        )
    return 1 if failures and not manifests else 0


def cmd_analyse(paths: list[Path]) -> int:
    print(report_for_files(paths))
    return 0


def cmd_rescore(paths: list[Path], ladder: str) -> int:
    print(f"rescoring {len(paths)} file(s) under the {ladder!r} ladder — no model call\n")
    print(report_for_files(paths, ladder=ladder))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "arms":
        return cmd_arms()
    if args.command == "ingest":
        return cmd_ingest()
    if args.command == "run":
        return cmd_run(args.arm, args.n, args.seed0, args.out_dir, args.append)
    if args.command == "analyse":
        return cmd_analyse(args.paths)
    if args.command == "rescore":
        return cmd_rescore(args.paths, args.ladder)
    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
