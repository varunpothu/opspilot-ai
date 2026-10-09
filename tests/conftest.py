from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def local_api_auth_disabled_for_unit_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests of individual API behaviours opt into this explicit local-only mode.
    # Dedicated security tests override this to exercise required authentication.
    monkeypatch.setenv("OPSPILOT_AUTH_MODE", "disabled")
    monkeypatch.delenv("OPSPILOT_API_TOKEN_HASHES", raising=False)
