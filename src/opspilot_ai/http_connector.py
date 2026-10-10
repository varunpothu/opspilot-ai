"""Read-only HTTPS connector with ETag conditional requests and strict host allowlists."""
from __future__ import annotations

import hashlib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .sync_state import SyncStateStore


class ReadOnlyHTTPError(RuntimeError):
    """A remote read failed or violated connector safety constraints."""


@dataclass(frozen=True)
class HTTPFetchResult:
    url: str
    status_code: int
    body: bytes
    etag: str | None
    last_modified: str | None
    content_type: str | None
    from_cache: bool


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if new.scheme != "https" or (new.hostname or "").lower() not in self.allowed_hosts:
            raise ReadOnlyHTTPError("redirect destination is outside the HTTPS host allowlist")
        if old.scheme != "https":
            raise ReadOnlyHTTPError("HTTPS downgrade redirects are forbidden")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class ConditionalHTTPConnector:
    """Fetch bounded public resources with ETag/Last-Modified revalidation.

    The connector deliberately has no write method and does not accept arbitrary
    authorization headers. Use a dedicated secret manager and connector adapter
    before adding authenticated source systems.
    """

    name = "conditional-http"
    writable = False

    def __init__(
        self, state: SyncStateStore, *, allowed_hosts: set[str] | frozenset[str],
        timeout_seconds: float = 8.0, max_response_bytes: int = 2_000_000,
    ):
        hosts = frozenset(host.lower().rstrip(".") for host in allowed_hosts)
        if not hosts or any(not host or "/" in host or ":" in host for host in hosts):
            raise ValueError("allowed_hosts must contain plain hostnames")
        if timeout_seconds <= 0 or max_response_bytes < 1:
            raise ValueError("timeout and response-size limits must be positive")
        self.state = state
        self.allowed_hosts = hosts
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._opener = urllib.request.build_opener(_AllowlistedRedirectHandler(hosts))

    def fetch(self, url: str) -> HTTPFetchResult:
        parsed = urllib.parse.urlsplit(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme != "https" or host not in self.allowed_hosts
            or parsed.username is not None or parsed.password is not None
            or parsed.fragment
        ):
            raise ReadOnlyHTTPError("URL must be HTTPS, credential-free, fragment-free and host-allowlisted")

        # Hash the URL to avoid persisting query-string values in the cache key.
        resource_key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cached = self.state.get_cached_representation(resource_key)
        headers = {"Accept": "application/json, text/plain, */*", "User-Agent": "OpsPilotAI/0.1"}
        if cached and cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached and cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]
        request = urllib.request.Request(url, headers=headers, method="GET")

        try:
            response = self._opener.open(request, timeout=self.timeout_seconds)
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                if cached is None:
                    raise ReadOnlyHTTPError("server returned 304 but no cached representation exists") from exc
                return HTTPFetchResult(
                    url=url, status_code=304, body=cached["body"],
                    etag=exc.headers.get("ETag") or cached.get("etag"),
                    last_modified=exc.headers.get("Last-Modified") or cached.get("last_modified"),
                    content_type=exc.headers.get("Content-Type") or cached.get("content_type"),
                    from_cache=True,
                )
            raise ReadOnlyHTTPError(f"remote endpoint returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ReadOnlyHTTPError("remote endpoint could not be reached") from exc

        with response:
            status = getattr(response, "status", response.getcode())
            if status != 200:
                raise ReadOnlyHTTPError(f"unexpected HTTP status: {status}")
            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    if int(declared) > self.max_response_bytes:
                        raise ReadOnlyHTTPError("remote response exceeds configured size limit")
                except ValueError as exc:
                    raise ReadOnlyHTTPError("remote response has invalid Content-Length") from exc
            body = response.read(self.max_response_bytes + 1)
            if len(body) > self.max_response_bytes:
                raise ReadOnlyHTTPError("remote response exceeds configured size limit")
            etag = response.headers.get("ETag")
            modified = response.headers.get("Last-Modified")
            content_type = response.headers.get("Content-Type")
        self.state.put_cached_representation(
            resource_key, etag=etag, last_modified=modified,
            content_type=content_type, body=body,
        )
        return HTTPFetchResult(
            url=url, status_code=200, body=body, etag=etag,
            last_modified=modified, content_type=content_type, from_cache=False,
        )
