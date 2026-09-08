"""The local API: a transport shell that must not become a second place rules live.

Two halves. The first runs unconditionally and is the important one: it asserts that the
core package does not depend on the API, so `make test` keeps passing with FastAPI
uninstalled and `tests/conftest.py`'s live-backend refusal is untouched.

The second is skipped when FastAPI is absent. It checks the three hard rules from the build
spec — no configuration a client can invent, no prompt in any response, and
`host_ground_truth` gated — plus the cost gate, because the frontend can spend real money
against whatever backend `configs/base.yaml` names.
"""

from __future__ import annotations

import ast
import json
import pathlib
from collections.abc import Iterator
from typing import Any

import pytest

from artsoc.config import RunConfig
from artsoc.metrics import CONTROL_ARM

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "artsoc"
SCENARIO_ID = "phase1_tel_dispersal_v1"


# ---------------------------------------------------------------------------
# Unconditional: the optional extra must stay optional.
# ---------------------------------------------------------------------------


def test_nothing_in_artsoc_imports_the_api() -> None:
    """`api.py` is an optional extra. If any core module imported it, `make install` would
    need FastAPI, the offline guarantee would depend on a web framework being present, and
    a fresh clone would fail at import rather than at the point of use."""
    offenders = []
    for path in sorted(SRC.glob("*.py")):
        if path.name == "api.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(n == "artsoc.api" or n.startswith("artsoc.api.") for n in names):
                offenders.append(path.name)
    assert offenders == []


def test_the_api_module_holds_no_experiment_semantics() -> None:
    """Every rule the API appears to enforce is enforced in session.py, where the offline
    suite reaches it. A `RunConfig` constructed in the transport layer would be a
    configuration no test could see."""
    source = (SRC / "api.py").read_text(encoding="utf-8")
    assert "RunConfig(" not in source
    assert "model_copy" not in source


# ---------------------------------------------------------------------------
# Everything below needs the optional extra.
# ---------------------------------------------------------------------------

fastapi = pytest.importorskip("fastapi", reason="the api extra is not installed")
from fastapi.testclient import TestClient  # noqa: E402

from artsoc import api as api_module  # noqa: E402
from artsoc import session as session_module  # noqa: E402


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """Pin every arm to the mock backend and put sessions in a temporary directory.

    The API resolves arms through `session.load_arm`, which reads `configs/base.yaml` — and
    that declares a live backend and corpus retrieval for real runs. Without this an API
    test would bill the provider, which is exactly the failure conftest.py exists to stop.
    """
    real = session_module.load_arm

    def mocked(name: str, *args: object, **kwargs: object) -> RunConfig:
        return real(name, *args, **kwargs).model_copy(
            update={"backend": "mock", "retrieval_mode": "stub"}
        )

    monkeypatch.setattr(session_module, "load_arm", mocked)
    monkeypatch.setattr(session_module, "SESSIONS_DIR", tmp_path)


@pytest.fixture(autouse=True)
def _no_leaked_sessions() -> Iterator[None]:
    """Stop and join any session thread a test left running.

    Sessions run in background threads. One that outlives its test writes into a tmp_path
    pytest has already removed, which surfaces as an unrelated failure several tests later
    — and would be an actual leak in the server too.
    """
    yield
    for run in list(api_module._RUNNING.values()):
        run.cancelled.set()
        if run.thread is not None:
            run.thread.join(timeout=30)
    api_module._RUNNING.clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(api_module.create_app()) as test_client:
        yield test_client


def _spec(arms: list[str], n: int = 2) -> dict[str, Any]:
    return {"scenario_id": SCENARIO_ID, "arms": arms, "n": n, "label": "test"}


def _run_session(client: TestClient, arms: list[str], n: int = 2) -> str:
    """Start a session and drain its event stream, so the run has finished on return."""
    created = client.post("/api/sessions?confirm=true", json=_spec(arms, n))
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    with client.stream("GET", f"/api/sessions/{session_id}/events") as stream:
        for _ in stream.iter_lines():
            pass
    return session_id


# ---------------------------------------------------------------------------
# Selection among committed configs, and nothing else.
# ---------------------------------------------------------------------------


def test_scenarios_are_listed_without_their_ground_truth(client: TestClient) -> None:
    """Ground truth is host-only, and so are the scenario's own design notes.

    The notes explain what the ambiguity is meant to do and why the truth is withheld.
    Publishing them to a viewer is a softer version of publishing the truth, and this
    caught exactly that when the endpoint first returned them.
    """
    body = client.get("/api/scenarios").json()
    assert body
    assert {s["scenario_id"] for s in body} >= {SCENARIO_ID}
    blob = str(body)
    assert "ground_truth" not in blob
    assert "HOST-ONLY" not in blob

    card = next(s for s in body if s["scenario_id"] == SCENARIO_ID)
    assert card["observable_signature"], "a card with no signature shows no ambiguity"


def test_arms_are_listed_with_what_each_one_varies(client: TestClient) -> None:
    """An arm is only worth running because of the field it moves; a list of bare names
    gives a client no way to choose."""
    arms = {a["arm"]: a for a in client.get("/api/arms").json()}
    assert arms[CONTROL_ARM]["is_control"] is True
    assert arms[CONTROL_ARM]["consult_panel"] is False
    assert arms["small_panel"]["varies"] == {"panel_size": 4}
    assert arms["loo_jervis"]["is_exclusion_arm"] is True


def test_a_session_naming_an_arm_that_is_not_a_file_is_refused(
    client: TestClient,
) -> None:
    """Invariant 5 by another route: a client that can invent a configuration makes every
    result untraceable."""
    response = client.post("/api/sessions?confirm=true", json=_spec(["not_an_arm"]))
    assert response.status_code == 404
    assert "no such arm" in response.text


def test_a_request_body_cannot_carry_an_experimental_parameter(
    client: TestClient,
) -> None:
    """`SessionSpec` forbids extra fields, so there is no field through which a RunConfig
    override could arrive at all."""
    body = {**_spec(["baseline"]), "panel_size": 99, "backend": "mock"}
    assert client.post("/api/sessions?confirm=true", json=body).status_code == 422


# ---------------------------------------------------------------------------
# The cost gate. base.yaml decides the backend and currently declares a live one.
# ---------------------------------------------------------------------------


def test_starting_a_session_without_confirmation_is_refused(client: TestClient) -> None:
    response = client.post("/api/sessions", json=_spec([CONTROL_ARM, "baseline"], n=5))
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["reason"] == "confirmation required"
    assert detail["estimate"]["total_calls"] > 0


def test_the_refusal_carries_the_estimate_broken_down_by_arm(client: TestClient) -> None:
    """The control makes two calls a replication and a full loop makes twenty; one number
    across both would overstate the control tenfold and stop being read."""
    response = client.post("/api/sessions", json=_spec([CONTROL_ARM, "baseline"], n=10))
    arms = {a["arm"]: a for a in response.json()["detail"]["estimate"]["arms"]}
    assert arms[CONTROL_ARM]["calls_per_replication"] == 2
    assert arms["baseline"]["calls_per_replication"] > arms[CONTROL_ARM][
        "calls_per_replication"
    ]


def test_an_unconfirmed_session_starts_nothing(client: TestClient) -> None:
    client.post("/api/sessions", json=_spec(["baseline"]))
    assert client.get("/api/sessions").json() == []


def test_an_unknown_arm_is_refused_before_the_cost_gate(client: TestClient) -> None:
    """Estimating first means a typo returns 'no such arm', not 'confirm to spend money'."""
    assert client.post("/api/sessions", json=_spec(["ghost"])).status_code == 404


# ---------------------------------------------------------------------------
# Running, streaming, and reading back.
# ---------------------------------------------------------------------------


def test_a_confirmed_session_runs_and_streams_one_event_per_replication(
    client: TestClient,
) -> None:
    created = client.post("/api/sessions?confirm=true", json=_spec([CONTROL_ARM], n=3))
    session_id = created.json()["session_id"]

    events = []
    with client.stream("GET", f"/api/sessions/{session_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("event:"):
                events.append(line.split(": ", 1)[1])
    assert events.count("progress") == 3
    assert events[-1] == "done"
    assert client.get(f"/api/sessions/{session_id}").json()["status"] == "complete"


def test_a_summary_reports_the_contrast_and_the_caveats(client: TestClient) -> None:
    session_id = _run_session(client, [CONTROL_ARM, "baseline"], n=3)
    summary = client.get(f"/api/sessions/{session_id}/summary").json()

    assert summary["has_control"] is True
    assert [d["arm"] for d in summary["deltas"]] == ["baseline"]
    assert summary["mock"] is True
    assert summary["grounded"] is False
    assert any("MOCK BACKEND" in w for w in summary["warnings"])


def test_a_session_without_the_control_is_flagged_as_uninterpretable(
    client: TestClient,
) -> None:
    session_id = _run_session(client, ["baseline"], n=2)
    summary = client.get(f"/api/sessions/{session_id}/summary").json()
    assert summary["has_control"] is False
    assert "NO CONTROL ARM" in summary["warnings"][0]


def test_the_representative_endpoint_bundles_every_derived_view(
    client: TestClient,
) -> None:
    """Gantt, graph and event log must agree on step count; fetching them separately is
    what would let them disagree."""
    session_id = _run_session(client, ["baseline"], n=4)
    body = client.get(f"/api/sessions/{session_id}/runs/baseline/representative").json()

    assert body["arm"] == "baseline"
    assert body["representative"]["selection_note"]
    assert body["steps"] and body["graph"]["nodes"] and body["panel"]
    assert body["engagement"]["personas"]
    assert body["flow"]["label"] == "Pipeline flow to terminal rung"

    step_pairs = {(s["actor"], s["recipient"], s["kind"]) for s in body["steps"]}
    edge_pairs = {
        (e["source"], e["target"], e["kind"])
        for e in body["graph"]["edges"]
        if e["kind"] != "hallucinated"
    }
    assert step_pairs == edge_pairs


def test_the_representative_endpoint_rejects_an_arm_not_in_the_session(
    client: TestClient,
) -> None:
    session_id = _run_session(client, ["baseline"], n=2)
    response = client.get(f"/api/sessions/{session_id}/runs/small_panel/representative")
    assert response.status_code == 404


def test_an_unknown_session_is_a_404(client: TestClient) -> None:
    assert client.get("/api/sessions/deadbeef").status_code == 404
    assert client.get("/api/sessions/deadbeef/summary").status_code == 404
    assert client.get("/api/sessions/deadbeef/events").status_code == 404


# ---------------------------------------------------------------------------
# Reading a citation. A citation is only checkable against its claim if it can be read,
# and RunRecord stores the ids rather than the block — deliberately, since storing the
# block would mean storing what went into a prompt.
# ---------------------------------------------------------------------------


def test_a_cited_id_resolves_to_its_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    import artsoc.retrieval as retrieval_module

    store = tmp_path / "brodie"
    store.mkdir(parents=True)
    (store / "chunks.jsonl").write_text(
        json.dumps(
            {
                "passage_id": "brodie:wikipedia:11",
                "section": "Deterrence",
                "text": "Its chief purpose must be to avert wars.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_module, "CORPUS_ROOT", tmp_path)

    body = client.get("/api/passages/brodie", params={"ids": "brodie:wikipedia:11"}).json()
    assert body["passages"][0]["text"].startswith("Its chief purpose")
    assert body["passages"][0]["source"] == "wikipedia"
    assert body["unresolved"] == []


def test_an_invented_citation_comes_back_as_unresolved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Reported, never filled in. A placeholder would erase the citation-integrity
    finding that `unsupported_citations` exists to record."""
    import artsoc.retrieval as retrieval_module

    monkeypatch.setattr(retrieval_module, "CORPUS_ROOT", tmp_path)
    body = client.get("/api/passages/brodie", params={"ids": "brodie:wikipedia:404"}).json()
    assert body["passages"] == []
    assert body["unresolved"] == ["brodie:wikipedia:404"]
    assert "never filled in" in body["note"]


def test_the_passage_endpoint_will_not_serve_another_personas_text(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """One store per persona holds in the reader as well as in the loop."""
    import artsoc.retrieval as retrieval_module

    store = tmp_path / "schelling"
    store.mkdir(parents=True)
    (store / "chunks.jsonl").write_text(
        json.dumps({"passage_id": "schelling:wikipedia:9", "section": "s", "text": "theirs"})
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(retrieval_module, "CORPUS_ROOT", tmp_path)

    body = client.get("/api/passages/brodie", params={"ids": "schelling:wikipedia:9"}).json()
    assert body["passages"] == []
    assert body["unresolved"] == ["schelling:wikipedia:9"]


def test_asking_for_no_ids_is_empty_rather_than_a_dump(client: TestClient) -> None:
    """The endpoint resolves ids that are already in a record. It is not a corpus browser,
    and an empty query must not become a way to page through copyrighted source text."""
    body = client.get("/api/passages/brodie").json()
    assert body["passages"] == []
    assert body["unresolved"] == []


# ---------------------------------------------------------------------------
# The three hard rules.
# ---------------------------------------------------------------------------


def test_host_ground_truth_is_withheld_unless_it_is_asked_for(
    client: TestClient,
) -> None:
    """It is in the record so an analyst can score misperception. A demo viewer seeing it
    unasked would mistake it for something the President knew."""
    session_id = _run_session(client, ["baseline"], n=2)
    body = client.get(f"/api/sessions/{session_id}/runs/baseline/representative").json()

    assert body["host_ground_truth"] is None
    assert body["representative"]["record"]["host_ground_truth"] == {}


def test_revealing_ground_truth_labels_it_as_host_only(client: TestClient) -> None:
    session_id = _run_session(client, ["baseline"], n=2)
    body = client.get(
        f"/api/sessions/{session_id}/runs/baseline/representative",
        params={"reveal_ground_truth": True},
    ).json()

    assert body["host_ground_truth"]
    assert "HOST-ONLY" in body["host_only_note"]
    assert "No agent in the simulation saw it" in body["host_only_note"]


def test_no_response_carries_a_prompt(client: TestClient) -> None:
    """Invariant 10. `call_log` holds every system and user prompt and is what the
    access-matrix tests scan; shipping one to a browser would create a second surface where
    context can cross a boundary, outside the tests that guard the first."""
    session_id = _run_session(client, [CONTROL_ARM, "baseline"], n=2)
    paths = [
        "/api/scenarios",
        "/api/arms",
        "/api/sessions",
        f"/api/sessions/{session_id}",
        f"/api/sessions/{session_id}/summary",
        f"/api/sessions/{session_id}/runs/baseline/representative",
        f"/api/sessions/{session_id}/runs/baseline/representative?reveal_ground_truth=true",
    ]
    for path in paths:
        body = client.get(path).text
        assert "[[ROLE:" not in body, path
        assert "[[WHO:" not in body, path
        assert "call_log" not in body, path
        assert "system_prompt" not in body, path


def test_the_openapi_surface_exposes_no_run_config_fields(client: TestClient) -> None:
    """A schema advertising `panel_size` would invite a client to send one, and the next
    person to add an endpoint would read that as permission."""
    schema = client.get("/openapi.json").json()
    spec_fields = set(schema["components"]["schemas"]["SessionSpec"]["properties"])
    assert spec_fields == {"session_id", "label", "scenario_id", "arms", "n", "seed0"}

    # `scenario_id` overlaps RunConfig and is allowed to: it selects a committed scenario
    # file and is cross-checked against every arm's own config, so it cannot introduce a
    # setting no file describes. Everything else experimental must be absent.
    assert not spec_fields & (set(RunConfig.model_fields) - {"arm", "scenario_id"})
