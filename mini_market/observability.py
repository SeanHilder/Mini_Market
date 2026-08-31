"""Allowlisted JSON telemetry; no raw URLs, cookies, payloads or bearer links."""

import json
import logging
import secrets
import time
from datetime import datetime, timezone

from flask import Response, g, request
from prometheus_client import CollectorRegistry, Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest


class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Deliberately exclude arbitrary messages/exception strings, which can contain SQL parameters.
        output = {"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname}
        for field in ("event", "request_id", "route", "method", "status", "duration_ms", "order_id", "outcome", "error_type"):
            if hasattr(record, field):
                output[field] = getattr(record, field)
        return json.dumps(output, separators=(",", ":"))


def emit(app, event, **fields):
    app.logger.info("", extra={"event": event, "request_id": getattr(g, "request_id", None), **fields})


def checkout_event(app, outcome, order_id=None):
    app.extensions["telemetry"]["checkouts"].labels(outcome).inc()
    emit(app, "checkout", outcome=outcome, order_id=order_id)


def init_app(app):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False
    # Werkzeug's default access line includes the receipt bearer URL. Our safe
    # completion event replaces it. Configure proxy/WSGI access logs similarly.
    logging.getLogger("werkzeug").disabled = True
    registry = CollectorRegistry()
    telemetry = {
        "registry": registry,
        "requests": Counter("mini_market_http_requests", "Completed HTTP requests", ["method", "route", "status"], registry=registry),
        "latency": Histogram("mini_market_http_duration_seconds", "HTTP request duration", ["method", "route"], registry=registry),
        "checkouts": Counter("mini_market_checkouts", "Checkout results", ["outcome"], registry=registry),
        "cart_conflicts": Counter("mini_market_cart_conflicts", "Rejected conflicting cart mutations", registry=registry),
    }
    app.extensions["telemetry"] = telemetry

    @app.before_request
    def start_request():
        g.request_id = secrets.token_hex(16)  # Never trust a caller-provided identifier.
        g.started_at = time.perf_counter()

    @app.after_request
    def finish_request(response):
        response.headers["X-Request-ID"] = g.request_id
        if request.endpoint != "metrics":
            duration = time.perf_counter() - g.started_at
            route = request.url_rule.rule if request.url_rule else "unmatched"
            method = request.method if request.method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
            telemetry["requests"].labels(method, route, str(response.status_code)).inc()
            telemetry["latency"].labels(method, route).observe(duration)
            emit(app, "http_request", route=route, method=method, status=response.status_code, duration_ms=round(duration * 1000, 3))
        return response

    @app.get("/metrics")
    def metrics():
        configured = app.config.get("METRICS_TOKEN")
        if not configured:
            return "Not found", 404
        supplied = request.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied.encode(), ("Bearer " + configured).encode()):
            return "Unauthorized", 401
        return Response(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
