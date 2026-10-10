from __future__ import annotations

import json

import pytest

from opspilot_ai.github_connector import GitHubReadOnlyConnector
from opspilot_ai.http_connector import HTTPFetchResult, ReadOnlyHTTPError
from opspilot_ai.sync_state import SyncStateStore


def _http_result(payload: dict, *, etag: str | None = '"rev-1"', status: int = 200) -> HTTPFetchResult:
    return HTTPFetchResult(
        url="https://api.github.com/test", status_code=status,
        body=json.dumps(payload).encode("utf-8"), etag=etag,
        last_modified=None, content_type="application/json", from_cache=False,
    )


def test_github_connector_returns_only_allowlisted_repository_metadata(tmp_path, monkeypatch):
    connector = GitHubReadOnlyConnector(SyncStateStore(tmp_path / "github.sqlite3"))
    monkeypatch.setattr(connector._http, "fetch", lambda url: _http_result({
        "id": 123, "name": "sample", "full_name": "owner/sample",
        "private": False, "default_branch": "main", "description": "Public demo",
        "token": "should-not-be-returned", "secrets": {"key": "never"},
    }))
    result = connector.get_repository("owner", "sample")
    assert result.data["full_name"] == "owner/sample"
    assert result.data["default_branch"] == "main"
    assert "token" not in result.data and "secrets" not in result.data
    assert result.etag == '"rev-1"' and connector.writable is False


def test_github_connector_summarizes_workflow_runs_and_validates_pagination(tmp_path, monkeypatch):
    connector = GitHubReadOnlyConnector(SyncStateStore(tmp_path / "github.sqlite3"))
    seen = {}
    def fake_fetch(url):
        seen["url"] = url
        return _http_result({
            "total_count": 1,
            "workflow_runs": [{
                "id": 42, "name": "CI", "status": "completed", "conclusion": "success",
                "head_sha": "abc", "html_url": "https://github.com/owner/sample/actions/runs/42",
                "token": "omit-this",
            }],
        })
    monkeypatch.setattr(connector._http, "fetch", fake_fetch)
    result = connector.list_workflow_runs("owner", "sample", per_page=5, page=1, branch="main/feature")
    assert result.data["items"][0]["id"] == 42
    assert "token" not in result.data["items"][0]
    assert "branch=main%2Ffeature" in seen["url"]
    with pytest.raises(ValueError, match="per_page"):
        connector.list_workflow_runs("owner", "sample", per_page=101)


def test_github_connector_rejects_path_injection_and_bad_json(tmp_path, monkeypatch):
    connector = GitHubReadOnlyConnector(SyncStateStore(tmp_path / "github.sqlite3"))
    with pytest.raises(ValueError, match="owner"):
        connector.get_repository("../attacker", "repo")
    monkeypatch.setattr(connector._http, "fetch", lambda url: HTTPFetchResult(
        url=url, status_code=200, body=b"<html>", etag=None,
        last_modified=None, content_type="text/html", from_cache=False,
    ))
    with pytest.raises(ReadOnlyHTTPError, match="non-JSON"):
        connector.get_repository("owner", "repo")
