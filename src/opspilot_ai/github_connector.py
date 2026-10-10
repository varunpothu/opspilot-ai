"""Read-only public GitHub metadata adapter built on conditional HTTP caching."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from .http_connector import ConditionalHTTPConnector, ReadOnlyHTTPError
from .sync_state import SyncStateStore

_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


@dataclass(frozen=True)
class GitHubReadResult:
    resource: str
    status_code: int
    etag: str | None
    from_cache: bool
    data: dict


class GitHubReadOnlyConnector:
    """Read public repository metadata and workflow-run summaries; never writes.

    This adapter intentionally has no token or arbitrary-header parameter. It is
    for public GitHub data only; private repositories require a separate,
    secret-manager-backed adapter with a dedicated read-only credential.
    """

    name = "github-read-only"
    writable = False

    def __init__(self, state: SyncStateStore, *, timeout_seconds: float = 8.0):
        self._http = ConditionalHTTPConnector(
            state, allowed_hosts={"api.github.com"}, timeout_seconds=timeout_seconds,
            max_response_bytes=2_000_000,
        )

    def get_repository(self, owner: str, repo: str) -> GitHubReadResult:
        path = self._repository_path(owner, repo)
        result = self._fetch_json(path, resource=f"repository:{owner}/{repo}")
        data = result["payload"]
        return GitHubReadResult(
            resource=f"repository:{owner}/{repo}",
            status_code=result["status_code"],
            etag=result["etag"],
            from_cache=result["from_cache"],
            data={
                key: data.get(key)
                for key in (
                    "id", "node_id", "name", "full_name", "private", "html_url",
                    "description", "default_branch", "archived", "visibility",
                    "language", "created_at", "updated_at", "pushed_at",
                    "stargazers_count", "open_issues_count",
                )
            },
        )

    def get_latest_commit(self, owner: str, repo: str, branch: str | None = None) -> GitHubReadResult:
        base = self._repository_path(owner, repo)
        if branch is None:
            repository = self.get_repository(owner, repo)
            branch = repository.data.get("default_branch")
        if not isinstance(branch, str) or not branch.strip() or len(branch) > 255:
            raise ValueError("branch/ref must contain 1 to 255 characters")
        path = f"{base}/commits/{quote(branch, safe='')}"
        result = self._fetch_json(path, resource=f"latest-commit:{owner}/{repo}:{branch}")
        data = result["payload"]
        commit = data.get("commit") if isinstance(data.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        return GitHubReadResult(
            resource=f"latest-commit:{owner}/{repo}:{branch}",
            status_code=result["status_code"],
            etag=result["etag"],
            from_cache=result["from_cache"],
            data={
                "sha": data.get("sha"),
                "html_url": data.get("html_url"),
                "message": commit.get("message"),
                "author_name": author.get("name"),
                "author_date": author.get("date"),
            },
        )

    def list_workflow_runs(
        self, owner: str, repo: str, *, per_page: int = 20, page: int = 1,
        branch: str | None = None,
    ) -> GitHubReadResult:
        if not 1 <= per_page <= 100 or page < 1:
            raise ValueError("per_page must be 1..100 and page must be positive")
        path = f"{self._repository_path(owner, repo)}/actions/runs"
        query: dict[str, str | int] = {"per_page": per_page, "page": page}
        if branch is not None:
            if not branch.strip() or len(branch) > 255:
                raise ValueError("branch must contain 1 to 255 characters")
            query["branch"] = branch
        result = self._fetch_json(f"{path}?{urlencode(query)}", resource=f"workflow-runs:{owner}/{repo}:{urlencode(query)}")
        payload = result["payload"]
        raw_runs = payload.get("workflow_runs", [])
        if not isinstance(raw_runs, list):
            raise ReadOnlyHTTPError("GitHub workflow-runs response has an invalid schema")
        items = []
        for run in raw_runs[:per_page]:
            if not isinstance(run, dict):
                continue
            items.append({
                key: run.get(key)
                for key in (
                    "id", "name", "event", "status", "conclusion", "head_branch",
                    "head_sha", "created_at", "updated_at", "run_attempt", "html_url",
                )
            })
        return GitHubReadResult(
            resource=f"workflow-runs:{owner}/{repo}",
            status_code=result["status_code"],
            etag=result["etag"],
            from_cache=result["from_cache"],
            data={"total_count": payload.get("total_count", len(items)), "items": items},
        )

    def _fetch_json(self, path: str, *, resource: str) -> dict:
        response = self._http.fetch(f"https://api.github.com{path}")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReadOnlyHTTPError("GitHub returned a non-JSON response") from exc
        if not isinstance(payload, dict):
            raise ReadOnlyHTTPError("GitHub returned an unexpected JSON shape")
        return {
            "resource": resource,
            "status_code": response.status_code,
            "etag": response.etag,
            "from_cache": response.from_cache,
            "payload": payload,
        }

    @staticmethod
    def _repository_path(owner: str, repo: str) -> str:
        if not isinstance(owner, str) or not _SLUG.fullmatch(owner):
            raise ValueError("owner must be a valid GitHub account slug")
        if not isinstance(repo, str) or not _SLUG.fullmatch(repo):
            raise ValueError("repo must be a valid GitHub repository slug")
        return f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}"
