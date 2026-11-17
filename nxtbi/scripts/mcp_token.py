"""Mint a bearer token for the NxtBI Superset MCP server (NXTBI_MCP_AUTH=local-jwt).

    python nxtbi/scripts/mcp_token.py                                   # service account, 1 hour
    python nxtbi/scripts/mcp_token.py --user planning.admin@nxtbi.local --ttl 28800

The token is an HS256 JWT signed with MCP_JWT_SECRET from nxtbi/.env. The MCP server maps
its `preferred_username` to an existing Superset user (the user must have signed in once),
so every tool call runs with that user's roles and row level security.

The token is printed to stdout and is a credential: anyone holding it can act as that user
through MCP until it expires. Standard library only.

Client configuration (Claude Code):
    claude mcp add --transport http nxtbi-superset http://localhost:5008/mcp \
        --header "Authorization: Bearer $(python nxtbi/scripts/mcp_token.py)"
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "nxtbi-superset-demo"       # must match MCP_JWT_ISSUER in config/superset_config.py
AUDIENCE = "nxtbi-superset-mcp"      # must match MCP_JWT_AUDIENCE


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint(username: str, ttl: int, secret: str) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": username, "preferred_username": username,
              "client_id": "nxtbi-mcp-token", "iat": now, "nbf": now - 5, "exp": now + ttl,
              "jti": uuid.uuid4().hex}
    signing_input = f"{b64(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{b64(json.dumps(claims, separators=(',', ':')).encode())}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return f"{signing_input}.{b64(signature)}"


def main() -> int:
    env = read_env()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--user", default=env.get("SUPERSET_SERVICE_USERNAME", "nxtbi-service"),
                        help="Superset username the token acts as (default: the service account)")
    parser.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds (default 3600)")
    args = parser.parse_args()
    secret = env.get("MCP_JWT_SECRET", "")
    if not secret or secret == "__GENERATE__":
        print("MCP_JWT_SECRET is missing in nxtbi/.env: run python nxtbi/scripts/gen_env.py --add-missing",
              file=sys.stderr)
        return 2
    print(mint(args.user, args.ttl, secret))
    return 0


if __name__ == "__main__":
    sys.exit(main())
