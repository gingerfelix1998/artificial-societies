"""Suite-wide guarantees that hold however an individual test is written.

`make test` must run on a disconnected machine, with no API key, and must never spend
money. That promise has been protected three different ways as the project changed, and
each protection was weaker than it looked:

1. Originally, by there being no live backend to construct. ADR 0002 retired that.
2. Then by every arm declaring `backend: mock`. That stops being true the moment
   `configs/base.yaml` is switched over for a live run — which is a normal thing to do,
   and would have quietly turned the test suite into a billable workload.
3. Now, here: constructing a live backend anywhere inside the suite raises.

The third is the only one that holds regardless of configuration, because it does not
depend on a config file staying in a particular state. A test that needs the loop uses the
mock explicitly; a test that reaches for a live backend by accident fails loudly rather
than silently making network calls.
"""

from __future__ import annotations

import pytest

import artsoc.llm as llm


@pytest.fixture(autouse=True)
def _no_live_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse to construct a live backend inside the test suite.

    Autouse and unconditional. There is no opt-out, because the whole point is that no
    individual test can decide to spend money on the suite's behalf.
    """

    def _refuse(self: object, *args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a test tried to construct a live backend. `make test` runs offline with no "
            "API key and must never spend money. Pin `backend='mock'` on the config the "
            "test uses; arms may declare a live backend for real runs without the suite "
            "inheriting it."
        )

    monkeypatch.setattr(llm.AnthropicBackend, "__init__", _refuse)
