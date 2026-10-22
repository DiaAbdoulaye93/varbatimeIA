"""Optional HTTP Basic auth in front of the whole app (API and dashboard).

The browser asks for the credentials once, then sends them with every request of the
dashboard (same origin). /health stays open for the hosting platform's checks.
"""

import base64
import binascii
import secrets
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from starlette.responses import PlainTextResponse

OPEN_PATHS = frozenset({"/health"})
REALM = "Analyseur de verbatims"


def _credentials(header: str) -> tuple[str, str] | None:
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        username, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return username, password


def add_basic_auth(app: FastAPI, username: str, password: str) -> None:
    expected = (username.encode(), password.encode())

    @app.middleware("http")
    async def basic_auth(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in OPEN_PATHS:
            return await call_next(request)
        given = _credentials(request.headers.get("authorization", ""))
        # compare_digest on both parts: no timing hint on which one is wrong.
        if given is not None and all(
            secrets.compare_digest(a, b)
            for a, b in zip((given[0].encode(), given[1].encode()), expected, strict=True)
        ):
            return await call_next(request)
        return PlainTextResponse(
            "Authentification requise.",
            status_code=401,
            headers={"WWW-Authenticate": f'Basic realm="{REALM}", charset="UTF-8"'},
        )
