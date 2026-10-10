"""Request correlation and opt-in OpenTelemetry tracing with secret-safe logs."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from contextvars import ContextVar
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
request_id_context: ContextVar[str] = ContextVar("opspilot_request_id", default="-")
logger = logging.getLogger("opspilot_ai.http")


class RequestContextMiddleware:
    """ASGI middleware that correlates requests without logging query strings or bodies."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw_headers = dict(scope.get("headers", []))
        supplied = raw_headers.get(b"x-request-id", b"").decode("latin-1", errors="ignore")
        request_id = supplied if _REQUEST_ID.fullmatch(supplied) else uuid4().hex
        token = request_id_context.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = list(message.get("headers", []))
                headers = [(key, value) for key, value in headers if key.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except Exception as exc:
            logger.error(json.dumps({
                "event": "http_request_failed",
                "request_id": request_id,
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status_code": 500,
                "error_type": type(exc).__name__,
                "duration_ms": max(0, int((time.perf_counter() - started) * 1000)),
            }, separators=(",", ":")))
            raise
        else:
            logger.info(json.dumps({
                "event": "http_request_completed",
                "request_id": request_id,
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status_code": status_code,
                "duration_ms": max(0, int((time.perf_counter() - started) * 1000)),
            }, separators=(",", ":")))
        finally:
            request_id_context.reset(token)


def configure_opentelemetry(app: ASGIApp) -> bool:
    """Enable OTLP tracing only with explicit opt-in and an exporter endpoint."""
    if os.getenv("OPSPILOT_OTEL_ENABLED", "false").lower() not in {"1", "true", "yes"}:
        return False
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        raise RuntimeError("OPSPILOT_OTEL_ENABLED requires OTEL_EXPORTER_OTLP_ENDPOINT")
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "Install the optional 'otel' dependencies to enable OpenTelemetry tracing"
        ) from exc

    provider = TracerProvider(resource=Resource.create({"service.name": "opspilot-ai"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    return True
