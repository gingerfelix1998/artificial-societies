"""Arms are config files, and the CLI may not become a second place to define one.

Invariant 5. The tests here exist because the failure they guard against is silent: a
`--panel-size` flag would work perfectly, produce numbers, and leave no record of what was
varied. An arm file is version-controlled, diffable, and copied into every output record.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from artsoc.cli import PERMITTED_RUN_FLAGS, build_parser, main
from artsoc.config import (
    RunConfig,
    base_defaults,
    list_arms,
    load_arm,
    varied_fields,
)
from artsoc.schema import ActionType, IntelBrief, PresidentialAction, RunRecord
from artsoc.sim import write_jsonl

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

#: The reference configuration. It is base defaults by design, so it is the one arm
#: exempt from the "must vary something" rule below.
REFERENCE_ARM = "baseline"


def _makefile_var(name: str) -> list[str]:
    """Read a Make variable, following backslash line continuations."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\s*:=\s*((?:.*\\\n)*.*)$", text, re.MULTILINE)
    assert match, f"Makefile no longer declares {name}; the sweeps cannot be compared"
    body = match.group(1).replace("\\\n", " ")
    # LOO_ARMS uses $(addprefix loo_,a b c); expand it the way Make would.
    prefix = re.match(r"\$\(addprefix\s+([A-Za-z0-9_]+),(.*)\)\s*$", body.strip())
    if prefix:
        return [prefix.group(1) + w for w in prefix.group(2).split()]
    return body.split()


def _makefile_arms() -> list[str]:
    return _makefile_var("ARMS")


def test_the_makefile_and_the_config_directory_cannot_drift() -> None:
    """A sweep naming an arm with no config fails halfway through, after spending time."""
    declared = sorted(_makefile_var("ARMS") + _makefile_var("LOO_ARMS"))
    assert declared == sorted(list_arms())


def test_the_two_sweeps_do_not_overlap() -> None:
    """They answer different questions and their contrasts have different baselines."""
    assert not set(_makefile_var("ARMS")) & set(_makefile_var("LOO_ARMS"))


def test_there_is_one_exclusion_arm_per_theorist() -> None:
    """A missing arm is a theorist whose influence simply never gets measured."""
    from artsoc.personas import load_registry

    expected = {f"loo_{p.persona_id}" for p in load_registry()}
    assert set(_makefile_var("LOO_ARMS")) == expected


def test_every_exclusion_arm_removes_exactly_one_known_theorist() -> None:
    """Two at once would confound them; zero would silently duplicate baseline."""
    from artsoc.personas import load_registry

    known = {p.persona_id for p in load_registry()}
    for name in list_arms():
        if not name.startswith("loo_"):
            continue
        excluded = load_arm(name).excluded_personas
        assert len(excluded) == 1, f"{name} excludes {len(excluded)} personas"
        assert excluded[0] in known
        assert name == f"loo_{excluded[0]}", "arm name must state who it removes"


def test_only_the_exclusion_arms_exclude_anyone() -> None:
    """A core arm quietly missing a theorist would corrupt every contrast drawn from it."""
    for name in list_arms():
        if name.startswith("loo_"):
            continue
        assert load_arm(name).excluded_personas == []


def test_every_arm_loads_and_validates() -> None:
    """An arm that fails to load fails after the sweep has already spent time on others."""
    for name in list_arms():
        config = load_arm(name)
        assert config.arm == name


def test_an_arms_identity_comes_from_its_filename() -> None:
    """A record labelled with the wrong arm is worse than no record."""
    for name in list_arms():
        assert load_arm(name).arm == name


def test_every_arm_except_the_reference_varies_something() -> None:
    """An arm identical to base runs, produces numbers, and measures nothing."""
    base = base_defaults()
    for name in list_arms():
        varied = varied_fields(load_arm(name), base)
        if name == REFERENCE_ARM:
            assert varied == {}, "baseline is the reference and must not vary from base"
        else:
            assert varied, f"arm {name!r} is identical to base and tests nothing"


def test_each_core_arm_varies_a_distinct_axis() -> None:
    """Two arms varying the same field would produce a contrast that isolates nothing.

    Scoped to the core sweep. The exclusion arms all vary `excluded_personas`, which is the
    point of them — they differ in the value, not the axis, and are checked separately.
    """
    signatures = {}
    for name in _makefile_var("ARMS"):
        if name == REFERENCE_ARM:
            continue
        signature = tuple(sorted(varied_fields(load_arm(name))))
        assert signature not in signatures, (
            f"arms {name!r} and {signatures[signature]!r} vary the same fields {signature}"
        )
        signatures[signature] = name


def test_the_control_arm_consults_no_panel() -> None:
    """Every interpretable number is a delta against this arm, so its definition matters."""
    control = load_arm("escalation_prior")
    assert control.consult_panel is False


def test_a_config_is_frozen_once_loaded() -> None:
    """A run that could mutate its own config would make RunRecord.config a fiction."""
    config = load_arm("baseline")
    with pytest.raises(ValidationError):
        config.panel_size = 99


def test_an_unknown_key_in_an_arm_file_is_rejected() -> None:
    """A typo'd key would silently do nothing while the arm claims to test something."""
    with pytest.raises(ValidationError):
        RunConfig.model_validate({"arm": "x", "panl_size": 4})


def test_an_invalid_vocabulary_value_is_rejected_at_load() -> None:
    """Failing at load beats failing part-way through the first replication."""
    for bad in (
        {"persona_method": "m9"},
        {"synthesis_mode": "whatever"},
        {"retrieval_mode": "magic"},
        {"panel_source": "elsewhere"},
    ):
        with pytest.raises(ValidationError):
            RunConfig.model_validate({"arm": "x", **bad})


def test_a_missing_arm_names_the_ones_that_exist() -> None:
    """A typo at the command line should not read as 'this arm is broken'."""
    with pytest.raises(FileNotFoundError) as exc:
        load_arm("no_such_arm")
    assert "baseline" in str(exc.value)


def test_every_arm_file_records_why_it_exists() -> None:
    """An arm without a stated purpose becomes uninterpretable the moment it is not new."""
    for name in list_arms():
        assert load_arm(name).notes.strip(), f"arm {name!r} has no notes"


def test_an_arms_notes_do_not_claim_a_panel_size_it_does_not_run() -> None:
    """Notes are read as description, and the frontend renders them on the arm cards.

    `baseline` claimed a 15-persona panel while the registry held 12 — harmless in a
    comment, and a false statement the moment it is shown to someone choosing arms.

    The realised size is what has to match, not `panel_size`. That field is a cap:
    `build_panel` returns the whole pool when the cap exceeds it, so an exclusion arm
    declaring 12 actually runs one fewer than the registry holds.
    """
    from artsoc.personas import load_registry

    registry = len(load_registry())
    for name in list_arms():
        config = load_arm(name)
        if config.panel_source != "registry":
            continue
        realised = min(config.panel_size, registry - len(config.excluded_personas))
        # `\b` so "M2 personas" does not read as a two-person panel.
        for claimed in re.findall(r"\b(\d+)(?:[-\s]persona|\s*$)", config.notes):
            assert int(claimed) == realised, (
                f"arm {name!r} notes claim a {claimed}-persona panel but it runs {realised}"
            )
        for claimed in re.findall(r"[Pp]anel of (\d+)", config.notes):
            assert int(claimed) == realised, (
                f"arm {name!r} notes say 'panel of {claimed}' but it runs {realised}"
            )


# ---------------------------------------------------------------------------
# The CLI must not become a second place to define an experiment.
# ---------------------------------------------------------------------------


def _subparser_flags(command: str) -> set[str]:
    """Option strings a subcommand exposes, excluding argparse's own help."""
    subparsers = build_parser()._subparsers._group_actions[0]
    chosen = subparsers.choices[command]
    flags = {opt for action in chosen._actions for opt in action.option_strings}
    return flags - {"-h", "--help"}


def test_the_run_command_exposes_only_the_permitted_operational_flags() -> None:
    """Invariant 5: only --n, --seed0, --out-dir and --append may live outside a config.

    Anything else changes what is being tested, and a flag leaves no version-controlled
    record of what was varied. Adding a fifth option fails here on purpose.
    """
    assert _subparser_flags("run") == set(PERMITTED_RUN_FLAGS)


def test_there_is_no_backend_flag() -> None:
    """The backend changes what produced the numbers, so it is experimental, not operational."""
    assert "--backend" not in _subparser_flags("run")
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "baseline", "--backend", "mock"])


def test_the_other_subcommands_take_no_experimental_options() -> None:
    """None of them runs an experiment, so none may acquire a way to configure one.

    `ingest` is included deliberately: chunking and passage ids are fixed by ADR 0003, and
    a `--chunk-size` flag would let someone silently invalidate every stored citation.

    `rescore` is deliberately not in this list (ADR 0011): unlike a flag that would let a
    caller configure what experiment to run, `--ladder` selects which of two already-
    committed, deterministic, host-side lookup tables an *already-collected* record is
    re-read through. No model call, no new `RunRecord`, nothing that could be true of one
    run and not another the way `--backend` would be.
    """
    for name in ("arms", "analyse", "ingest"):
        assert _subparser_flags(name) == set()


def test_rescore_exposes_only_the_ladder_choice() -> None:
    """`rescore`'s one flag is closed to the ladders `schema.rung_for` actually knows."""
    assert _subparser_flags("rescore") == {"--ladder"}


def _fixture_record(seed: int, ladder: str) -> RunRecord:
    action = PresidentialAction(
        action=ActionType.NUCLEAR_DEMONSTRATION, justification="MOCK:", ladder=ladder
    )
    return RunRecord(
        run_id=f"fixture-{seed}",
        arm="fixture",
        seed=seed,
        started_at="2026-01-01T00:00:00Z",
        wall_time_s=0.0,
        config={},
        backend="mock",
        cache_enabled=True,
        retrieval_mode="stub",
        grounded=False,
        scenario_id="fixture",
        intel_brief=IntelBrief(summary="MOCK:", assessed_activity="MOCK:", confidence="moderate"),
        action=action,
        rung=action.rung,
    )


def test_rescore_reports_different_bands_with_no_model_call(tmp_path, capsys) -> None:
    """`artsoc rescore --ladder` re-reads an existing file under either ladder (ADR 0011).

    `nuclear_demonstration` is band 3 under Kahn (below the headline threshold) and rung 6
    under the project table — the exact non-equivalence the ladder change is built around.
    Reads a plain JSONL file and calls only `cli.main`/`metrics.report_for_files`, neither
    of which constructs an `LLMClient` or a backend, so this is offline by construction.
    """
    path = tmp_path / "fixture.jsonl"
    write_jsonl([_fixture_record(1, "kahn"), _fixture_record(2, "kahn")], path)

    assert main(["rescore", str(path), "--ladder", "kahn"]) == 0
    kahn_out = capsys.readouterr().out
    assert main(["rescore", str(path), "--ladder", "project"]) == 0
    project_out = capsys.readouterr().out

    assert "band 3 (Intense Crises)" in kahn_out
    assert "rung 6" in project_out
    assert kahn_out != project_out
