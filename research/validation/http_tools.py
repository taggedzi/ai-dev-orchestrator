"""Bounded loopback-only synthetic HTTP endpoints; no model forwarding."""

import hashlib
import http.client
import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from .bundle import load_json
from .fixture import POLICY, canonical
from .phase_policy import (
    INPUT_MICRO_USD_PER_TOKEN,
    OUTPUT_MICRO_USD_PER_TOKEN,
    TOKEN_CAPS,
    admit_request,
    validate_turn,
)
from .store import Hold

MAX_BODY = 1024**2


def endpoint(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("expected plain loopback http URL without credentials")
    if not parsed.hostname or not ipaddress.ip_address(parsed.hostname).is_loopback:
        raise ValueError("only literal loopback addresses are allowed")
    if parsed.path not in ("", "/"):
        raise ValueError("endpoint must not contain a path")
    return parsed.hostname, parsed.port or 80


def request(url, method, path, body=b"", headers=None):
    host, port = endpoint(url)
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read(MAX_BODY + 1)
        if len(data) > MAX_BODY:
            raise Hold("upstream response exceeds limit")
        return (
            response.status,
            data,
            response.getheader("Content-Type", "application/json"),
        )
    finally:
        connection.close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(2)

    def log_message(self, *_):
        pass

    def body(self):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise ValueError("one Content-Length and no transfer encoding required")
        size = int(lengths[0])
        if size < 0 or size > MAX_BODY:
            raise ValueError("request body exceeds limit")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise ValueError("truncated request body")
        return raw

    def reply(self, status, raw, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def reject(self, status, reason):
        self.reply(status, canonical({"error": reason}))


class LocalServer(HTTPServer):
    allow_reuse_address = False

    def __init__(self, address, handler):
        if not ipaddress.ip_address(address[0]).is_loopback or ":" in address[0]:
            raise ValueError("server binds IPv4 loopback only")
        super().__init__(address, handler)

    def start(self):
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread


def broker(store, transcript, address=("127.0.0.1", 0)):
    """Frozen counts/roles, exact raw requests and atomically bound one-use permits."""
    if not isinstance(transcript, list) or not transcript or len(transcript) > 32:
        raise ValueError("transcript must have 1..32 frozen entries")
    # Validate and serve the same detached snapshot of caller-owned data.
    transcript = load_json(canonical(transcript))
    for row in transcript:
        if not isinstance(row, dict):
            raise TypeError("transcript row must be an object")
        if (
            not isinstance(row.get("request_sha256"), str)
            or len(row["request_sha256"]) != 64
        ):
            raise ValueError("missing exact request hash")
        if row.get("mode", "json") not in ("json", "sse", "interrupt"):
            raise ValueError("unknown scripted mode")
        if type(row.get("settled")) is not int or row["settled"] < 0:
            raise ValueError("invalid synthetic settlement")
        if not row.get("generation_id") or not isinstance(row.get("response"), dict):
            raise ValueError("missing response or generation")
        bound = validate_turn(row.get("admission"))
        if row["settled"] > bound:
            raise ValueError("scripted settlement exceeds the phase reservation")
        if len(canonical(row)) > MAX_BODY:
            raise ValueError("transcript row exceeds limit")
    binding = hashlib.sha256(
        canonical(
            {
                "format": "mcli1-phase-broker-v1",
                "token_caps": TOKEN_CAPS,
                "money_limits": POLICY["limits"],
                "micro_usd_per_token": [
                    INPUT_MICRO_USD_PER_TOKEN,
                    OUTPUT_MICRO_USD_PER_TOKEN,
                ],
                "transcript": transcript,
            }
        )
    ).hexdigest()
    store.bind_broker_transcript(binding)

    class Broker(Handler):
        def do_POST(self):
            try:
                if (
                    self.path != "/v1/chat/completions"
                    or self.headers.get("Authorization") != "Bearer fixture-dummy"
                ):
                    self.reject(403, "route or credential denied")
                    return
                raw = self.body()
                payload = load_json(raw)
                if not isinstance(payload, dict):
                    raise TypeError("Chat request must be a JSON object")
                if payload.get("model") != "fixture/model-v1" or any(
                    key in payload
                    for key in ("provider", "models", "route", "fallbacks")
                ):
                    self.reject(403, "model override or fallback denied")
                    return
                request_hash = hashlib.sha256(raw).hexdigest()
                # Count durable submissions, including interrupted ones, across restart.
                used = sum(row["kind"] == "submission-intent" for row in store.audit())
                if (
                    used >= len(transcript)
                    or transcript[used]["request_sha256"] != request_hash
                ):
                    raise Hold("unexpected transcript request or turn order")
                row = transcript[used]
                admission = admit_request(raw, request_hash, row["admission"])
                permit = store.consume(request_hash, admission)
                mode = row.get("mode", "json")
                if mode == "interrupt":
                    store.event(
                        "scripted-interruption",
                        {
                            "permit": permit["id"],
                            "generation_id": row["generation_id"],
                            "simulated": True,
                        },
                    )
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                store.settle(permit["id"], row["settled"], row["generation_id"])
                response = canonical(row["response"])
                if mode == "sse":
                    # Frozen Chat chunk supplied by caller; no generated provider behavior.
                    response = b"data: " + response + b"\n\ndata: [DONE]\n\n"
                self.reply(
                    200,
                    response,
                    "text/event-stream" if mode == "sse" else "application/json",
                )
            except Hold as error:
                self.reject(409, str(error))
            except (ValueError, TypeError, KeyError) as error:
                self.reject(400, str(error))

        def do_GET(self):
            self.reject(403, "route denied")

    return LocalServer(address, Broker)


def fault_proxy(store, upstream, faults, address=("127.0.0.1", 0)):
    """Record response before dropping ACK; faults bind explicit operation IDs."""
    endpoint(upstream)
    if any(
        mode not in ("before-forward", "after-response") for mode in faults.values()
    ):
        raise ValueError("unknown fault mode")

    class Proxy(Handler):
        def dispatch(self):
            operation = self.headers.get("X-Fixture-Operation", "")
            try:
                import re

                allowed = (
                    self.command == "POST" and self.path == "/api/conversations"
                ) or re.fullmatch(
                    r"/api/conversations/[0-9a-f-]{36}(?:/(?:events|run|interrupt|pause|runtime|events/search)(?:\?[^\r\n]*)?)?",
                    self.path,
                )
                if not allowed or self.command not in ("GET", "POST"):
                    self.reject(403, "executor route denied")
                    return
                raw = self.body() if self.command == "POST" else b""
                binding = hashlib.sha256(
                    canonical(
                        [self.command, self.path, hashlib.sha256(raw).hexdigest()]
                    )
                ).hexdigest()
                if self.command == "POST":
                    store.begin(operation, binding)
                else:
                    store.event("lookup-intent", {"path": self.path})
                fault = faults.get(operation)
                if fault == "before-forward":
                    store.event("proven-not-forwarded", {"operation": operation})
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                store.event(
                    "forward-intent",
                    {
                        "operation": operation,
                        "method": self.command,
                        "path": self.path,
                        "request_sha256": hashlib.sha256(raw).hexdigest(),
                    },
                )
                status, response, content_type = request(
                    upstream,
                    self.command,
                    self.path,
                    raw,
                    {
                        "Content-Type": "application/json",
                        "X-Session-API-Key": "fixture-dummy",
                    },
                )
                if self.command == "POST":
                    store.receipt(operation, status, response)
                else:
                    store.event(
                        "lookup-receipt",
                        {
                            "path": self.path,
                            "status": status,
                            "response_sha256": hashlib.sha256(response).hexdigest(),
                        },
                    )
                if fault == "after-response":
                    store.event(
                        "suppressed-ack", {"operation": operation, "status": status}
                    )
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                self.reply(status, response, content_type)
            except Hold as error:
                self.reject(409, str(error))
            except (ValueError, TypeError) as error:
                self.reject(400, str(error))
            except (OSError, http.client.HTTPException) as error:
                store.event(
                    "transport-unknown",
                    {"operation": operation, "error_type": type(error).__name__},
                )
                self.reject(502, "delivery outcome unknown; mutation not retried")

        do_POST = dispatch
        do_GET = dispatch

    return LocalServer(address, Proxy)
