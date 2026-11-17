# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Protected same-origin gateway for the standalone NxtBI Copilot demo."""

from __future__ import annotations

import base64
import binascii
import hmac
import json  # noqa: TID251 - The standalone gateway has no Superset runtime.
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from anyio import CancelScope
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.staticfiles import StaticFiles

from nxtbi.copilot.agent.contracts import MAX_BODY_BYTES, sign_context

RELAY_TIMEOUT = httpx.Timeout(90, connect=5)
AUTH_CHALLENGE = {"WWW-Authenticate": 'Basic realm="NxtBI Copilot", charset="UTF-8"'}
STREAM_HEADERS = {"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no"}


@dataclass(frozen=True)
class Settings:
    """Standalone gateway settings supplied by the deployment."""

    username: str
    password: str = field(repr=False)
    origin: str
    shared_secret: str = field(repr=False)
    agent_url: str
    static_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        """Load the demo credentials, agent address, and built web application."""
        base = os.getenv("NXTBI_COPILOT_AGENT_URL", "http://localhost:8000").rstrip("/")
        default_static = Path(__file__).parent / "dist"
        return cls(
            username=os.getenv("NXTBI_COPILOT_DEMO_USERNAME", ""),
            password=os.getenv("NXTBI_COPILOT_DEMO_PASSWORD", ""),
            origin=os.getenv("NXTBI_COPILOT_DEMO_ORIGIN", "").rstrip("/"),
            shared_secret=os.getenv("NXTBI_COPILOT_SHARED_SECRET", ""),
            agent_url=base if base.endswith("/ag-ui") else f"{base}/ag-ui",
            static_dir=Path(os.getenv("NXTBI_COPILOT_STATIC_DIR", str(default_static))),
        )

    @property
    def configured(self) -> bool:
        """Return whether the demo can authenticate its user and sign runs."""
        return bool(
            1 <= len(self.username) <= 200
            and ":" not in self.username
            and self.password
            and self.origin
            and len(self.shared_secret) >= 32
        )

    def accepts_basic(self, authorization: str) -> bool:
        """Check one configured credential pair without exposing it to the agent."""
        scheme, _, material = authorization.partition(" ")
        if scheme.casefold() != "basic" or len(material) > 8_192:
            return False
        try:
            candidate = base64.b64decode(material, validate=True)
        except (binascii.Error, ValueError):
            return False
        expected = f"{self.username}:{self.password}".encode()
        return hmac.compare_digest(candidate, expected)


async def _signed_input(request: Request, config: Settings) -> tuple[bytes, str]:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, "Copilot input is too large")
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
        token = sign_context(
            config.shared_secret,
            {
                "sub": config.username,
                "aud": "nxtbi-copilot",
                "host": "standalone",
                "exp": int(time.time()) + 120,
                "run_id": payload.get("runId"),
                "thread_id": payload.get("threadId"),
            },
        )
    except (ValueError, RecursionError) as exc:
        raise HTTPException(422, "Invalid Copilot run context") from exc
    return bytes(body), token


async def _relay(
    client: httpx.AsyncClient, url: str, token: str, body: bytes
) -> StreamingResponse:
    outbound = client.build_request(
        "POST",
        url,
        content=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
        },
    )
    try:
        upstream = await client.send(outbound, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "The Copilot agent is unavailable") from exc
    if upstream.status_code != 200:
        await upstream.aclose()
        if upstream.status_code in (413, 422, 429, 503):
            raise HTTPException(upstream.status_code, "The Copilot run could not start")
        raise HTTPException(502, "The Copilot agent is unavailable")
    if not upstream.headers.get("Content-Type", "").startswith("text/event-stream"):
        await upstream.aclose()
        raise HTTPException(502, "The Copilot agent returned an invalid stream")

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            with CancelScope(shield=True):
                await upstream.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )


def create_app(
    settings: Settings | None = None,
    *,
    agent_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Create one standalone gateway with a bounded relay and protected assets."""
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(api: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            timeout=RELAY_TIMEOUT,
            transport=agent_transport,
            trust_env=False,
        ) as client:
            api.state.agent_client = client
            yield

    api = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @api.middleware("http")
    async def protect(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method == "GET" and request.url.path == "/health":
            return await call_next(request)
        if not config.configured:
            return JSONResponse({"detail": "The demo gateway is unconfigured"}, 503)
        if not config.accepts_basic(request.headers.get("Authorization", "")):
            return JSONResponse(
                {"detail": "Demo authentication is required"},
                401,
                headers=AUTH_CHALLENGE,
            )
        response = await call_next(request)
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @api.get("/health")
    async def health() -> dict[str, str]:
        """Return gateway liveness without exposing deployment settings."""
        return {"status": "ok"}

    @api.post("/api/run")
    async def run(request: Request) -> StreamingResponse:
        """Sign the authenticated demo user and stream the agent response."""
        if request.headers.get("Origin") != config.origin:
            raise HTTPException(403, "The request did not come from the demo origin")
        body, token = await _signed_input(request, config)
        return await _relay(
            request.app.state.agent_client, config.agent_url, token, body
        )

    api.mount("/", StaticFiles(directory=config.static_dir, html=True, check_dir=False))
    return api


app = create_app()
