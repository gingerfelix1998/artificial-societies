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

from artsoc.cli import PERMITTED_RUN_FLAGS, build_parser
from artsoc.config import (
    RunConfig,
    base_defaults,
    list_arms,
    load_arm,
    varied_fields,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"

#: The reference configuration. It is base defaults by design, so it is the one arm
#: exempt from the "must vary something" rule below.
REFERENCE_ARM = "baseline"


def _makefile_arms() -> list[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(r"^ARMS\s*:=\s*(.+)$", text, re.MULTILINE)
    assert match, "Makefile no longer declares ARMS; the sweep and the configs cannot be compared"
    return match.group(1).split()


def test_the_makefile_and_the_config_directory_cannot_drift() -> None:
    """`make phase1` sweeping an arm that has no config fails halfway through a run."""
    assert sorted(_makefile_arms()) == sorted(list_arms())


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


def test_each_arm_varies_a_distinct_axis() -> None:
    """Two arms varying the same field would produce a contrast that isolates nothing."""
    signatures = {}
    for name in list_arms():
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


def test_arms_and_analyse_take_no_experimental_options() -> None:
    """Neither reads a config, so neither may acquire a way to change one."""
    for name in ("arms", "analyse"):
        assert _subparser_flags(name) == set()
