"""Local session and request boundaries; no provider credentials or JWTs."""

import asyncio
import hashlib
import hmac
import json
import secrets
import threading
import time
from dataclasses import dataclass

from starlette.responses import JSONResponse

from .domain import Invalid, require

COOKIE = "orchestrator_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
BODY_LIMIT = 1_048_576
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
}


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def nonfinite(_value):
        raise Invalid("nonfinite JSON value")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)


@dataclass(frozen=True)
class Session:
    csrf: str
    expires: float


class Sessions:
    def __init__(self, token, *, clock=time.monotonic, ttl=3600, maximum=32):
        require(
            type(token) is str and 32 <= len(token) <= 128, "invalid local access token"
        )
        self.token_hash = hashlib.sha256(token.encode()).digest()
        self.clock, self.ttl, self.maximum = clock, ttl, maximum
        self.lock = threading.RLock()
        self.sessions = {}

    def login(self, token):
        if type(token) is not str or not hmac.compare_digest(
            hashlib.sha256(token.encode()).digest(), self.token_hash
        ):
            return None
        with self.lock:
            now = self.clock()
            self.sessions = {
                key: row for key, row in self.sessions.items() if row.expires > now
            }
            if len(self.sessions) >= self.maximum:
                del self.sessions[next(iter(self.sessions))]
            key = secrets.token_urlsafe(32)
            row = Session(secrets.token_urlsafe(32), now + self.ttl)
            self.sessions[key] = row
            return key, row

    def lookup(self, key):
        with self.lock:
            row = self.sessions.get(key)
            if row is None:
                return None
            if row.expires <= self.clock():
                del self.sessions[key]
                return None
            return row

    def logout(self, key):
        with self.lock:
            self.sessions.pop(key, None)


class LocalBoundary:
    """Check canonical host/origin and bounded JSON before request dispatch."""

    def __init__(self, app, *, host, origin):
        self.app, self.host, self.origin = app, host, origin

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {}
        for key, value in scope["headers"]:
            headers.setdefault(key.lower(), []).append(value.decode("latin-1"))

        async def secured_send(message):
            if message["type"] == "http.response.start":
                keys = {k.lower().encode() for k in SECURITY_HEADERS}
                message["headers"] = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() not in keys
                ]
                message["headers"] += [
                    (k.lower().encode(), v.encode())
                    for k, v in SECURITY_HEADERS.items()
                ]
            await send(message)

        async def refuse(status, message):
            await JSONResponse(
                {"error": "RequestBoundary", "message": message}, status_code=status
            )(scope, receive, secured_send)

        if headers.get(b"host") != [self.host]:
            return await refuse(400, "Use the configured local workspace address")
        if headers.get(b"sec-fetch-site", ["none"])[0] == "cross-site":
            return await refuse(403, "Cross site requests are refused")
        origins = headers.get(b"origin", [])
        if (origins and origins != [self.origin]) or (
            scope["method"] in UNSAFE and origins != [self.origin]
        ):
            return await refuse(403, "A matching local Origin is required")
        lengths = headers.get(b"content-length", [])
        if len(lengths) > 1 or (lengths and not lengths[0].isdigit()):
            return await refuse(400, "Invalid request length")
        if lengths and int(lengths[0]) > BODY_LIMIT:
            return await refuse(413, "Request exceeds one MiB")
        if scope["method"] in UNSAFE:
            content_types = headers.get(b"content-type", [])
            if (
                len(content_types) != 1
                or content_types[0].split(";", 1)[0].strip().lower()
                != "application/json"
            ):
                return await refuse(415, "Use application/json")
            body = bytearray()
            try:
                async with asyncio.timeout(5):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > BODY_LIMIT:
                            return await refuse(413, "Request exceeds one MiB")
                        if not message.get("more_body", False):
                            break
                value = strict_json(bytes(body))
                if type(value) is not dict:
                    raise Invalid("object required")
            except TimeoutError:
                return await refuse(408, "Request body timed out")
            except (Invalid, ValueError, UnicodeError, RecursionError):
                return await refuse(
                    422, "Use a JSON object without duplicate or nonfinite fields"
                )
            sent = False

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return await receive()

            return await self.app(scope, replay, secured_send)
        return await self.app(scope, receive, secured_send)
