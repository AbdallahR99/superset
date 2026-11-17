#!/usr/bin/env python3
"""Provision the existing NxtBI Keycloak realm for the NxtBI Superset demo.

Python 3.11+, standard library only. Runs on the host and needs the docker CLI.

The script never starts, stops or reconfigures Keycloak. All admin work runs through
``kcadm.sh`` INSIDE the Keycloak container, authenticated with the bootstrap admin
credentials that already live in that container's environment, so no admin secret is
read by, stored on or printed from the host. Request bodies travel over stdin, so no
secret ever shows up in a process argument list.

Commands
--------
apply (default)    Idempotent, additive provisioning:
                     1. client scope ``groups`` (created from the canonical realm file when absent)
                     2. canonical group tree and canonical users (Keycloak partialImport with
                        ifResourceExists=SKIP, explicit calls for whatever partialImport skips)
                     3. demo-user password discovery -> NXTBI_DEMO_USER_PASSWORD in nxtbi/.env
                     4. platform admin user (NXTBI_PLATFORM_ADMINS[0], password SUPERSET_SSO_ADMIN_PASSWORD)
                     5. confidential OIDC client KEYCLOAK_CLIENT_ID (create or update)
                   Nothing that existed before the first run is modified or deleted.
status             Read-only report of what exists / is missing. Prints no secret.
                   ``--probe-logins`` additionally tries a password grant per demo user.
verify             Checks that change no configuration: example id/access tokens from Keycloak's
                   evaluate-scopes endpoints, authorize-endpoint scope acceptance, a real
                   authorization-code + PKCE login as the Superset client (userinfo and RP logout
                   included; skip with --no-login-flow) and password grants.
teardown           Deletes ONLY what nxtbi/.keycloak-state.json says this script created
                   (asks nothing; ``--dry-run`` only prints what would be removed).
show-credentials   Demo usernames, group paths and where the passwords are stored.
                   Password values are printed only with ``--reveal``.

Demo-user password
------------------
The canonical realm file stores HASHED credentials. ``apply`` looks for the documented
NxtDash dev default (``NXT_SEED_PASSWORD`` in the NxtDash repo's scripts and ``*.example``
files) and confirms it with a resource-owner password grant against a public
direct-grant client of the realm (``admin-cli``). A confirmed password is written to
NXTBI_DEMO_USER_PASSWORD in nxtbi/.env. If no documented password works, a fresh password
is generated and set ONLY on users that this script created (tracked in the state file);
the password of a pre-existing user is never changed.

Configuration (process environment overrides nxtbi/.env)
--------------------------------------------------------
KEYCLOAK_CONTAINER (ld-shared-keycloak-1), KEYCLOAK_REALM (nxtbi),
KEYCLOAK_CLIENT_ID (nxtbi-superset), KEYCLOAK_CLIENT_SECRET, NXTBI_REALM_FILE,
KEYCLOAK_BROWSER_URL (host-reachable base URL, used for the login probes),
SUPERSET_PUBLIC_URL (http://localhost:8088), NXTBI_PLATFORM_ADMINS,
SUPERSET_SSO_ADMIN_PASSWORD, NXTBI_DEMO_USER_PASSWORD (written by this script),
KEYCLOAK_ADMIN_SERVER (in-container admin URL, default http://localhost:8080),
KEYCLOAK_PROBE_CLIENT_ID (admin-cli).

State: nxtbi/.keycloak-state.json (git-ignored, holds resource ids, never a secret).
The Keycloak container has no data volume; a stale state file is detected and repaired.

Facts the Superset side depends on (all checked by ``verify``)
--------------------------------------------------------------
* Keycloak rejects an authorize request that names a scope not assigned to the client
  (``invalid_scope``). A realm without the built-in ``profile`` / ``email`` scopes therefore only
  accepts ``openid groups``; the same string keeps working once those scopes exist, because they
  are then default scopes of the client. ``status`` prints the string to request.
* Tokens carry the issuer of the host the BROWSER logged in on (KEYCLOAK_BROWSER_URL), also when
  the code is exchanged on another host name (KEYCLOAK_INTERNAL_URL). The userinfo endpoint
  answers 401 when it is called on a host that differs from that issuer.
* The ``groups`` claim is absent (not an empty list) for a user without any group.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import string
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html import unescape as html_unescape
from pathlib import Path
from typing import Any

NXTBI_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = NXTBI_DIR / ".env"
STATE_FILE = NXTBI_DIR / ".keycloak-state.json"
STATE_VERSION = 1

KCADM = "/opt/keycloak/bin/kcadm.sh"
DEMO_PASSWORD_KEY = "NXTBI_DEMO_USER_PASSWORD"
ADMIN_PASSWORD_KEY = "SUPERSET_SSO_ADMIN_PASSWORD"
CLIENT_SECRET_KEY = "KEYCLOAK_CLIENT_SECRET"
PLACEHOLDERS = {"", "__GENERATE__"}
GENERATED_SOURCE = "generated by keycloak_setup.py"

GROUPS_SCOPE = "groups"
# Realm client scopes the client wants as defaults when the live realm has them.
WANTED_DEFAULT_SCOPES = ["web-origins", "acr", "roles", "profile", "basic", "email", GROUPS_SCOPE]
WANTED_OPTIONAL_SCOPES = ["offline_access", "organization"]
FALLBACK_PREFIX = "nxtbi-fallback-"
PROVIDER_CALLBACK = "/oauth-authorized/keycloak"
POST_LOGOUT_PATH = "/login/"

_CLAIM_ON = {"id.token.claim": "true", "access.token.claim": "true",
             "userinfo.token.claim": "true", "introspection.token.claim": "true"}


def _attr_mapper(name: str, attribute: str, claim: str, json_type: str = "String",
                 mapper: str = "oidc-usermodel-attribute-mapper") -> dict[str, Any]:
    return {"name": FALLBACK_PREFIX + name, "protocol": "openid-connect", "protocolMapper": mapper,
            "consentRequired": False,
            "config": {"user.attribute": attribute, "claim.name": claim, "jsonType.label": json_type, **_CLAIM_ON}}


# Client-level protocol mappers that replace a built-in realm client scope the live realm lacks.
# The definitions mirror Keycloak 26 built-in scopes (same as the canonical realm file).
FALLBACK_MAPPERS: dict[str, list[dict[str, Any]]] = {
    "profile": [
        _attr_mapper("username", "username", "preferred_username"),
        _attr_mapper("given-name", "firstName", "given_name"),
        _attr_mapper("family-name", "lastName", "family_name"),
        {"name": FALLBACK_PREFIX + "full-name", "protocol": "openid-connect",
         "protocolMapper": "oidc-full-name-mapper", "consentRequired": False, "config": dict(_CLAIM_ON)},
    ],
    "email": [
        _attr_mapper("email", "email", "email"),
        _attr_mapper("email-verified", "emailVerified", "email_verified", "boolean",
                     "oidc-usermodel-property-mapper"),
    ],
    "basic": [
        {"name": FALLBACK_PREFIX + "sub", "protocol": "openid-connect", "protocolMapper": "oidc-sub-mapper",
         "consentRequired": False, "config": {"access.token.claim": "true", "introspection.token.claim": "true"}},
        {"name": FALLBACK_PREFIX + "auth-time", "protocol": "openid-connect",
         "protocolMapper": "oidc-usersessionmodel-note-mapper", "consentRequired": False,
         "config": {"user.session.note": "AUTH_TIME", "claim.name": "auth_time", "jsonType.label": "long",
                    "id.token.claim": "true", "access.token.claim": "true", "introspection.token.claim": "true"}},
    ],
}

# Built-in definition used only when the canonical realm file has no 'groups' client scope.
BUILTIN_GROUPS_SCOPE: dict[str, Any] = {
    "name": GROUPS_SCOPE, "description": "NxtBI role mapping: full group paths", "protocol": "openid-connect",
    "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
    "protocolMappers": [{
        "name": "groups", "protocol": "openid-connect", "protocolMapper": "oidc-group-membership-mapper",
        "consentRequired": False,
        "config": {"full.path": "true", "claim.name": "groups", "id.token.claim": "true",
                   "access.token.claim": "true", "userinfo.token.claim": "true",
                   "introspection.token.claim": "true"}}],
}


class SetupError(RuntimeError):
    """A problem the operator has to fix (reported without a traceback)."""


# --------------------------------------------------------------------------- env / state files


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser (comments, blank lines, optional matching quotes)."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def write_env_value(path: Path, key: str, value: str) -> None:
    """Replace (or append) exactly one KEY=VALUE line, leaving every other byte alone. LF endings."""
    rendered = value
    if re.search(r"[\s#'\"$\\`]", value):
        if "'" in value:
            raise SetupError(f"refusing to write a value containing a single quote to {key}")
        rendered = f"'{value}'"
    text = path.read_bytes().decode("utf-8") if path.is_file() else ""
    lines = text.split("\n")
    pattern = re.compile(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=")
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = f"{key}={rendered}"
            break
    else:
        if lines and lines[-1] == "":
            lines.insert(len(lines) - 1, f"{key}={rendered}")
        else:
            lines.append(f"{key}={rendered}")
            lines.append("")
    path.write_bytes("\n".join(lines).encode("utf-8"))


def empty_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "created": {"client_scopes": {}, "groups": {}, "users": {}},
            "admin_user": None, "client": None, "demo_password": None, "oauth": None}


def load_state() -> dict[str, Any]:
    state = empty_state()
    if STATE_FILE.is_file():
        try:
            loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SetupError(f"cannot read {STATE_FILE}: {exc} (delete the file to start clean)") from exc
        if isinstance(loaded, dict):
            for key, value in loaded.items():
                if key == "created" and isinstance(value, dict):
                    for kind in state["created"]:
                        if isinstance(value.get(kind), dict):
                            state["created"][kind] = value[kind]
                else:
                    state[key] = value
    return state


def save_state(state: dict[str, Any]) -> None:
    state["version"] = STATE_VERSION
    state["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    STATE_FILE.write_bytes(payload.encode("utf-8"))


def state_is_empty(state: dict[str, Any]) -> bool:
    created = state["created"]
    return not (created["client_scopes"] or created["groups"] or created["users"]
                or state.get("admin_user") or state.get("client"))


# --------------------------------------------------------------------------- configuration


class Config:
    def __init__(self, args: argparse.Namespace) -> None:
        self.env_file = parse_env_file(ENV_FILE)
        self.container = self._get("KEYCLOAK_CONTAINER", "ld-shared-keycloak-1", args.container)
        self.realm = self._get("KEYCLOAK_REALM", "nxtbi", args.realm)
        self.client_id = self._get("KEYCLOAK_CLIENT_ID", "nxtbi-superset", args.client_id)
        self.realm_file = Path(self._get(
            "NXTBI_REALM_FILE", "D:/DDWork/nxtdash-w4-int/docker/keycloak/realm-nxtbi.json", args.realm_file))
        self.admin_server = self._get("KEYCLOAK_ADMIN_SERVER", "http://localhost:8080")
        self.probe_client_id = self._get("KEYCLOAK_PROBE_CLIENT_ID", "admin-cli")
        browser_url = self._get("KEYCLOAK_BROWSER_URL", "http://localhost:8180", args.keycloak_url).rstrip("/")
        # 'localhost' may resolve to ::1 first while the port is published on 127.0.0.1 only.
        self.probe_url = re.sub(r"^(https?://)localhost(?=[:/]|$)", r"\g<1>127.0.0.1", browser_url)
        self.public_url = self._get("SUPERSET_PUBLIC_URL", "http://localhost:8088").rstrip("/")
        admins = [a.strip() for a in self._get("NXTBI_PLATFORM_ADMINS", "superset.admin@nxtbi.local").split(",")]
        self.admin_username = ([a for a in admins if a] or ["superset.admin@nxtbi.local"])[0].lower()

    def _get(self, key: str, default: str = "", override: str | None = None) -> str:
        if override:
            return override
        return os.environ.get(key) or self.env_file.get(key) or default

    def secret(self, key: str) -> str:
        """Secret from the environment / nxtbi/.env ('' when unset or still a placeholder)."""
        value = os.environ.get(key) or self.env_file.get(key) or ""
        return "" if value in PLACEHOLDERS else value

    def superset_origins(self) -> list[str]:
        """SUPERSET_PUBLIC_URL plus its loopback twin (localhost <-> 127.0.0.1)."""
        origins = [self.public_url]
        parsed = urllib.parse.urlsplit(self.public_url)
        twin = {"localhost": "127.0.0.1", "127.0.0.1": "localhost"}.get(parsed.hostname or "")
        if twin:
            netloc = twin + (f":{parsed.port}" if parsed.port else "")
            origins.append(urllib.parse.urlunsplit((parsed.scheme, netloc, "", "", "")))
        return origins


# --------------------------------------------------------------------------- Keycloak admin (kcadm in container)


class Kc:
    """Thin wrapper around ``docker exec <container> kcadm.sh``; paths are relative to the realm."""

    _LOGIN = (
        'u="${KC_BOOTSTRAP_ADMIN_USERNAME:-$KEYCLOAK_ADMIN}"; '
        'p="${KC_BOOTSTRAP_ADMIN_PASSWORD:-$KEYCLOAK_ADMIN_PASSWORD}"; '
        'if [ -z "$u" ] || [ -z "$p" ]; then echo "no bootstrap admin credentials in the container environment" >&2; '
        "exit 64; fi; "
        f'KC_CLI_PASSWORD="$p" exec {KCADM} config credentials --server "$1" --realm master --user "$u" --config "$2"'
    )

    def __init__(self, cfg: Config) -> None:
        self.container = cfg.container
        self.realm = cfg.realm
        self.server = cfg.admin_server
        self.config_path = f"/tmp/kcadm-nxtbi-superset-{os.getpid()}.config"
        self.logged_in = False

    # -- plumbing
    def _docker(self, argv: list[str], stdin: str | None = None, timeout: int = 180) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(["docker", *argv], input=stdin, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise SetupError("the 'docker' CLI was not found on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise SetupError(f"docker {argv[0]} timed out after {timeout}s") from exc

    def preflight(self) -> None:
        result = self._docker(["inspect", "-f", "{{.State.Running}}", self.container])
        if result.returncode != 0:
            raise SetupError(
                f"Keycloak container '{self.container}' does not exist (or the docker daemon is not reachable). "
                "Start the NxtBI Keycloak or set KEYCLOAK_CONTAINER.")
        if result.stdout.strip() != "true":
            raise SetupError(f"Keycloak container '{self.container}' exists but is not running.")

    def login(self) -> None:
        result = self._docker(["exec", self.container, "sh", "-c", self._LOGIN, "sh", self.server, self.config_path])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["no output"]
            raise SetupError(
                f"Keycloak admin login failed inside '{self.container}' ({detail[0][:300]}). The script uses the "
                "bootstrap admin from the container environment (KC_BOOTSTRAP_ADMIN_USERNAME / _PASSWORD) "
                f"against {self.server}.")
        self.logged_in = True

    def close(self) -> None:
        if self.logged_in:
            self._docker(["exec", self.container, "rm", "-f", self.config_path])
            self.logged_in = False

    def _kcadm(self, args: list[str], body: Any = None, retry: bool = True) -> subprocess.CompletedProcess[str]:
        argv = ["exec"] + (["-i"] if body is not None else []) + [self.container, KCADM, *args,
                                                                 "--config", self.config_path]
        stdin = json.dumps(body, ensure_ascii=True) if body is not None else None
        result = self._docker(argv, stdin=stdin)
        if result.returncode != 0 and retry and re.search(
                r"Session not active|Token is not active|invalid_grant|HTTP 401|Unauthorized", result.stderr):
            self.login()
            return self._kcadm(args, body, retry=False)
        return result

    @staticmethod
    def _query(query: dict[str, Any] | None) -> list[str]:
        out: list[str] = []
        for key, value in (query or {}).items():
            out += ["-q", f"{key}={value}"]
        return out

    @staticmethod
    def _fail(action: str, path: str, result: subprocess.CompletedProcess[str]) -> SetupError:
        detail = " ".join((result.stderr or result.stdout).split())[:400]
        return SetupError(f"Keycloak {action} {path} failed: {detail}")

    # -- verbs
    def get(self, path: str, query: dict[str, Any] | None = None, fields: str | None = None,
            absolute: bool = False) -> Any:
        """GET; returns parsed JSON, or None when the resource does not exist."""
        args = ["get", path] + ([] if absolute else ["-r", self.realm]) + self._query(query)
        args += ["--fields", fields] if fields else ["-c"]
        result = self._kcadm(args)
        if result.returncode != 0:
            if "Resource not found" in result.stderr or "404" in result.stderr:
                return None
            raise self._fail("GET", path, result)
        text = result.stdout.strip()
        return json.loads(text) if text else None

    def get_many(self, requests: list[tuple[str, dict[str, Any] | None]]) -> list[Any]:
        """Several independent GETs, a few at a time (each kcadm call starts a JVM)."""
        if not requests:
            return []
        with ThreadPoolExecutor(max_workers=4) as pool:
            return list(pool.map(lambda req: self.get(req[0], req[1]), requests))

    def create(self, path: str, body: Any) -> str:
        """POST a new resource; returns its id."""
        result = self._kcadm(["create", path, "-r", self.realm, "-i", "-f", "-"], body=body)
        if result.returncode != 0:
            raise self._fail("POST", path, result)
        return result.stdout.strip()

    def post(self, path: str, body: Any) -> Any:
        """POST and return the JSON response body."""
        result = self._kcadm(["create", path, "-r", self.realm, "-o", "-c", "-f", "-"], body=body)
        if result.returncode != 0:
            raise self._fail("POST", path, result)
        text = result.stdout.strip()
        return json.loads(text) if text else None

    def put(self, path: str, body: Any = None, merge: bool = False) -> None:
        """PUT. merge=True lets kcadm overlay the body on the current representation server-side."""
        args = ["update", path, "-r", self.realm, "-m" if merge else "-n", "-f", "-"]
        result = self._kcadm(args, body={} if body is None else body)
        if result.returncode != 0:
            raise self._fail("PUT", path, result)

    def delete(self, path: str) -> bool:
        result = self._kcadm(["delete", path, "-r", self.realm])
        if result.returncode != 0:
            if "Resource not found" in result.stderr or "404" in result.stderr:
                return False
            raise self._fail("DELETE", path, result)
        return True


# --------------------------------------------------------------------------- canonical realm file


class Canonical:
    """The groups, users and 'groups' client scope of the canonical NxtBI realm definition."""

    def __init__(self, path: Path) -> None:
        if not path.is_file():
            raise SetupError(f"canonical realm file not found: {path} (set NXTBI_REALM_FILE)")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SetupError(f"canonical realm file is not valid JSON: {path}: {exc}") from exc
        self.path = path
        self.top_groups: list[dict[str, Any]] = data.get("groups") or []
        self.group_paths: list[str] = []  # parents before children
        self._walk(self.top_groups, "")
        self.users: list[dict[str, Any]] = [
            u for u in (data.get("users") or []) if u.get("username") and not u.get("serviceAccountClientId")]
        scope = next((s for s in data.get("clientScopes") or [] if s.get("name") == GROUPS_SCOPE), None)
        self.groups_scope_from_file = scope is not None
        self.groups_scope = self._strip_ids(scope) if scope else copy.deepcopy(BUILTIN_GROUPS_SCOPE)

    def _walk(self, groups: list[dict[str, Any]], parent: str) -> None:
        for group in groups:
            path = f"{parent}/{group['name']}"
            self.group_paths.append(path)
            self._walk(group.get("subGroups") or [], path)

    @classmethod
    def _strip_ids(cls, obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: cls._strip_ids(v) for k, v in obj.items() if k not in ("id", "parentId")}
        if isinstance(obj, list):
            return [cls._strip_ids(v) for v in obj]
        return obj

    def usernames(self) -> list[str]:
        return [u["username"].lower() for u in self.users]

    def user_groups(self, username: str) -> list[str]:
        user = next(u for u in self.users if u["username"].lower() == username)
        return sorted(user.get("groups") or [])

    def import_group(self, group: dict[str, Any], live_roles: set[str], parent: str = "") -> dict[str, Any]:
        """Group representation for partialImport: no ids (Keycloak generates fresh ones).

        'path' is mandatory: Keycloak's GroupsPartialImport looks the new group up by it.
        """
        path = f"{parent}/{group['name']}"
        return {"name": group["name"], "path": path, "attributes": group.get("attributes") or {},
                "realmRoles": [r for r in group.get("realmRoles") or [] if r in live_roles],
                "subGroups": [self.import_group(g, live_roles, path) for g in group.get("subGroups") or []]}

    def import_user(self, user: dict[str, Any], live_roles: set[str]) -> dict[str, Any]:
        """User representation for partialImport: hashed credentials kept, ids dropped."""
        rep: dict[str, Any] = {
            "username": user["username"].lower(), "enabled": user.get("enabled", True),
            "emailVerified": user.get("emailVerified", False), "totp": False,
            "requiredActions": user.get("requiredActions") or [],
            "groups": list(user.get("groups") or []),
            "realmRoles": [r for r in user.get("realmRoles") or [] if r in live_roles],
            "credentials": [{k: v for k, v in cred.items() if k != "id"} for cred in user.get("credentials") or []],
        }
        for key in ("email", "firstName", "lastName", "attributes"):
            if user.get(key):
                rep[key] = user[key]
        return rep


# --------------------------------------------------------------------------- live realm snapshot


CLIENT_FIELDS = ("id,clientId,name,description,enabled,protocol,publicClient,bearerOnly,clientAuthenticatorType,"
                 "standardFlowEnabled,implicitFlowEnabled,directAccessGrantsEnabled,serviceAccountsEnabled,"
                 "consentRequired,frontchannelLogout,fullScopeAllowed,rootUrl,baseUrl,redirectUris,webOrigins,"
                 "attributes(*),defaultClientScopes,optionalClientScopes,"
                 "protocolMappers(id,name,protocol,protocolMapper,consentRequired,config(*))")
# kcadm's --fields filter returns nested maps empty unless they are spelled 'name(*)'.
USER_FIELDS = "id,username,email,firstName,lastName,enabled,emailVerified,createdTimestamp,requiredActions"


class Live:
    """Read-only view of the realm, limited to what this script manages. Holds no secret."""

    def __init__(self, kc: Kc, cfg: Config, canonical: Canonical) -> None:
        self.kc, self.cfg, self.canonical = kc, cfg, canonical
        self.realm: dict[str, Any] = {}
        self.roles: set[str] = set()
        self.scopes: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, str] = {}  # canonical path -> live id
        self.users: dict[str, dict[str, Any]] = {}  # username -> representation
        self.user_groups: dict[str, list[dict[str, str]]] = {}  # username -> [{id, path}]
        self.client: dict[str, Any] | None = None
        self.probe_client: dict[str, Any] | None = None
        self.refresh()

    def refresh(self) -> None:
        kc, cfg = self.kc, self.cfg
        realm = kc.get(f"realms/{cfg.realm}", absolute=True,
                       fields="id,realm,enabled,sslRequired,bruteForceProtected,passwordPolicy,organizationsEnabled")
        if not realm:
            raise SetupError(f"realm '{cfg.realm}' does not exist in container '{cfg.container}'")
        self.realm = realm
        roles, scopes, top_groups, users = kc.get_many([
            ("roles", {"max": 1000}), ("client-scopes", None), ("groups", {"max": 1000}), ("users", {"max": 2000})])
        self.roles = {r["name"] for r in roles or []}
        self.scopes = {s["name"]: s for s in scopes or []}
        self.refresh_client()
        probe = kc.get("clients", {"clientId": cfg.probe_client_id},
                       fields="id,clientId,enabled,publicClient,directAccessGrantsEnabled")
        self.probe_client = probe[0] if probe else None
        self._load_groups(top_groups or [])
        self._load_users(users or [])

    def refresh_client(self) -> None:
        found = self.kc.get("clients", {"clientId": self.cfg.client_id}, fields=CLIENT_FIELDS)
        self.client = found[0] if found else None

    def _load_groups(self, top_groups: list[dict[str, Any]]) -> None:
        wanted = set(self.canonical.group_paths)
        self.groups = {f"/{g['name']}": g["id"] for g in top_groups if f"/{g['name']}" in wanted}
        frontier = list(self.groups)
        while frontier:
            parents = [p for p in frontier if any(c.startswith(p + "/") for c in wanted)]
            results = self.kc.get_many([(f"groups/{self.groups[p]}/children", {"max": 1000}) for p in parents])
            frontier = []
            for parent, children in zip(parents, results):
                for child in children or []:
                    path = f"{parent}/{child['name']}"
                    if path in wanted:
                        self.groups[path] = child["id"]
                        frontier.append(path)

    def _load_users(self, users: list[dict[str, Any]]) -> None:
        keep = (USER_FIELDS.split(","))
        wanted = set(self.canonical.usernames()) | {self.cfg.admin_username}
        by_name = {u["username"].lower(): u for u in users}
        if len(users) >= 2000:  # large realm: look the wanted users up one by one
            lookups = self.kc.get_many([("users", {"username": name, "exact": "true"}) for name in sorted(wanted)])
            by_name = {u["username"].lower(): u for found in lookups for u in found or []}
        self.users = {name: {k: by_name[name].get(k) for k in keep} for name in wanted if name in by_name}
        self.emails = {(u.get("email") or "").lower(): u["username"].lower() for u in users if u.get("email")}
        names = sorted(self.users)
        memberships = self.kc.get_many([(f"users/{self.users[n]['id']}/groups", {"max": 1000}) for n in names])
        self.user_groups = {n: [{"id": g["id"], "path": g["path"]} for g in m or []]
                            for n, m in zip(names, memberships)}

    def scope_names(self) -> set[str]:
        return set(self.scopes)

    def groups_scope_problem(self) -> str | None:
        """None when the live 'groups' scope emits full group paths in a 'groups' id-token claim."""
        scope = self.scopes.get(GROUPS_SCOPE)
        if not scope:
            return "missing"
        for mapper in scope.get("protocolMappers") or []:
            config = mapper.get("config") or {}
            if (mapper.get("protocolMapper") == "oidc-group-membership-mapper"
                    and config.get("claim.name") == "groups" and config.get("full.path") == "true"
                    and config.get("id.token.claim") == "true"):
                return None
        return "has no oidc-group-membership-mapper with full.path=true, claim 'groups', id.token.claim=true"


# --------------------------------------------------------------------------- desired client


def desired_client(cfg: Config, scope_names: set[str]) -> dict[str, Any]:
    """Client representation per research section 7, adapted to the scopes the live realm has."""
    origins = cfg.superset_origins()
    mappers: list[dict[str, Any]] = [{
        "name": f"audience-{cfg.client_id}", "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
        "config": {"included.client.audience": cfg.client_id, "access.token.claim": "true",
                   "id.token.claim": "false", "introspection.token.claim": "true"}}]
    for scope, fallback in FALLBACK_MAPPERS.items():
        if scope not in scope_names:
            mappers += copy.deepcopy(fallback)
    return {
        "clientId": cfg.client_id,
        "name": "NxtBI Superset Demo",
        "description": "Apache Superset (NxtBI demo). Managed by nxtbi/scripts, do not edit by hand.",
        "enabled": True, "protocol": "openid-connect",
        "publicClient": False, "bearerOnly": False, "clientAuthenticatorType": "client-secret",
        "standardFlowEnabled": True, "implicitFlowEnabled": False, "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False, "consentRequired": False, "frontchannelLogout": False,
        "fullScopeAllowed": False,
        "rootUrl": origins[0], "baseUrl": "/",
        "redirectUris": [o + PROVIDER_CALLBACK for o in origins],
        "webOrigins": list(origins),
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "post.logout.redirect.uris": "##".join(o + POST_LOGOUT_PATH for o in origins),
            "backchannel.logout.session.required": "true",
            "backchannel.logout.revoke.offline.tokens": "false",
        },
        "defaultClientScopes": [s for s in WANTED_DEFAULT_SCOPES if s in scope_names],
        "optionalClientScopes": [s for s in WANTED_OPTIONAL_SCOPES if s in scope_names],
        "protocolMappers": mappers,
    }


def client_field_drift(desired: dict[str, Any], live: dict[str, Any]) -> list[str]:
    drift = []
    for key, want in desired.items():
        if key in ("protocolMappers", "defaultClientScopes", "optionalClientScopes"):
            continue
        have = live.get(key)
        if key == "attributes":
            drift += [f"attributes.{k}" for k, v in want.items() if (have or {}).get(k) != v]
        elif isinstance(want, list):
            if sorted(have or []) != sorted(want):
                drift.append(key)
        elif have != want:
            drift.append(key)
    return drift


def mapper_drift(desired: list[dict[str, Any]], live: list[dict[str, Any]]) -> dict[str, list[Any]]:
    live_by_name = {m["name"]: m for m in live}
    wanted_names = {m["name"] for m in desired}
    plan: dict[str, list[Any]] = {"create": [], "update": [], "delete": [], "unmanaged": []}
    for mapper in desired:
        have = live_by_name.get(mapper["name"])
        if not have:
            plan["create"].append(mapper)
        elif (have.get("protocolMapper") != mapper["protocolMapper"]
              or any((have.get("config") or {}).get(k) != v for k, v in mapper["config"].items())):
            plan["update"].append({**mapper, "id": have["id"]})
    for mapper in live:
        if mapper["name"] not in wanted_names:
            plan["delete" if mapper["name"].startswith(FALLBACK_PREFIX) else "unmanaged"].append(mapper)
    return plan


def recommended_scope(default_scopes: list[str], optional_scopes: list[str]) -> str:
    """Scope string Superset can safely request: Keycloak rejects scopes not assigned to the client."""
    assigned = set(default_scopes) | set(optional_scopes)
    return " ".join(["openid"] + [s for s in ("profile", "email", GROUPS_SCOPE) if s in assigned])


# --------------------------------------------------------------------------- login probes (host -> Keycloak)


class ProbeUnavailable(RuntimeError):
    pass


def _http_post(url: str, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(form).encode("utf-8"), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 (operator-configured URL)
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (urllib.error.URLError, OSError) as exc:
        raise ProbeUnavailable(f"{url} not reachable: {exc}") from exc
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        return status, {}


def password_grant(cfg: Config, username: str, password: str) -> tuple[str, dict[str, Any]]:
    """Try a resource-owner password grant. Returns (outcome, tokens).

    outcome: 'ok' | 'invalid' (wrong password) | 'blocked' (right or unknown password, account not usable).
    Raises ProbeUnavailable when the probe itself cannot work (client missing, grant disabled, network).
    The session a successful grant opens is closed again right away.
    """
    base = f"{cfg.probe_url}/realms/{cfg.realm}/protocol/openid-connect"
    status, body = _http_post(f"{base}/token", {
        "grant_type": "password", "client_id": cfg.probe_client_id, "username": username, "password": password})
    if status == 200 and body.get("access_token"):
        if body.get("refresh_token"):
            try:
                _http_post(f"{base}/logout", {"client_id": cfg.probe_client_id, "refresh_token": body["refresh_token"]})
            except ProbeUnavailable:
                pass
        return "ok", body
    error, description = body.get("error", ""), body.get("error_description", "")
    if error == "invalid_grant" and "Invalid user credentials" in description:
        return "invalid", {}
    if error == "invalid_grant":
        return "blocked", {"reason": description}
    raise ProbeUnavailable(f"password grant via client '{cfg.probe_client_id}' not possible: "
                           f"HTTP {status} {error} {description}".strip())


def probe_ready(live: Live, cfg: Config) -> str | None:
    client = live.probe_client
    if not client:
        return f"realm has no client '{cfg.probe_client_id}' for login probes"
    if not (client.get("enabled") and client.get("publicClient") and client.get("directAccessGrantsEnabled")):
        return f"client '{cfg.probe_client_id}' is not an enabled public client with direct grants"
    return None


def discover_documented_passwords(realm_file: Path) -> list[tuple[str, str]]:
    """Documented NxtDash dev-default passwords: [(value, where it is documented)]. Values are never printed."""
    found: list[tuple[str, str]] = []
    try:
        root = realm_file.resolve().parents[2]  # <repo>/docker/keycloak/<file>
    except IndexError:
        return found
    sources: list[tuple[Path, str]] = [
        (root / "scripts" / "nxt-keycloak-token.sh", r"\$\{NXT_SEED_PASSWORD:-([^}]+)\}"),
        (root / "scripts" / "nxt-verify-keycloak.sh", r"\$\{NXT_SEED_PASSWORD:-([^}]+)\}"),
        (root / "packages" / "backend" / "src" / "database" / "nxtSeedConstants.ts",
         r"NXT_SEED_PASSWORD_DEFAULT\s*=\s*['\"]([^'\"]+)['\"]"),
    ]
    sources += [(p, r"(?m)^\s*(?:export\s+)?NXT_SEED_PASSWORD\s*=\s*['\"]?([^'\"\s#]+)")
                for p in sorted(root.glob("*.example")) + sorted(root.glob(".*.example"))]
    for path, pattern in sources:
        try:
            if not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            if value and not value.startswith("<") and value not in [v for v, _ in found]:
                found.append((value, f"NxtDash dev default NXT_SEED_PASSWORD ({path.relative_to(root).as_posix()})"))
    return found


def generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(24))
        if any(c.islower() for c in candidate) and any(c.isupper() for c in candidate) \
                and any(c.isdigit() for c in candidate):
            return candidate + "-Nx1"


# --------------------------------------------------------------------------- reporting


class Report:
    def __init__(self, title: str) -> None:
        self.title = title
        self.rows: list[tuple[str, str, str]] = []
        self.notes: list[str] = []

    def add(self, item: str, status: str, detail: str = "") -> None:
        self.rows.append((item, status, detail))

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def statuses(self) -> set[str]:
        return {status for _, status, _ in self.rows}

    def render(self) -> None:
        print(self.title)
        width = max((len(item) for item, _, _ in self.rows), default=0)
        swidth = max((len(status) for _, status, _ in self.rows), default=0)
        for item, status, detail in self.rows:
            print(f"  {item.ljust(width)}  {status.ljust(swidth)}  {detail}".rstrip())
        for note in self.notes:
            print(f"  NOTE: {note}")


def prune_stale_state(state: dict[str, Any], live: Live, cfg: Config) -> list[str]:
    """Drop state entries whose resource no longer exists under the recorded id."""
    dropped: list[str] = []
    recorded_realm = state.get("realm_id")
    created = state["created"]
    for name in list(created["client_scopes"]):
        if (live.scopes.get(name) or {}).get("id") != created["client_scopes"][name].get("id"):
            dropped.append(f"client scope {name}")
            del created["client_scopes"][name]
    for path in list(created["groups"]):
        if live.groups.get(path) != created["groups"][path].get("id"):
            dropped.append(f"group {path}")
            del created["groups"][path]
    for name in list(created["users"]):
        if (live.users.get(name) or {}).get("id") != created["users"][name].get("id"):
            dropped.append(f"user {name}")
            del created["users"][name]
    admin = state.get("admin_user")
    if admin and (live.users.get(admin.get("username", "")) or {}).get("id") != admin.get("id"):
        dropped.append(f"user {admin.get('username')}")
        state["admin_user"] = None
    client = state.get("client")
    if client and ((live.client or {}).get("id") != client.get("id") or client.get("clientId") != cfg.client_id):
        dropped.append(f"client {client.get('clientId')}")
        state["client"] = None
    if recorded_realm and recorded_realm != live.realm.get("id"):
        dropped.append("realm id changed")
    return dropped


# --------------------------------------------------------------------------- apply


def apply_groups_scope(kc: Kc, live: Live, canonical: Canonical, state: dict[str, Any], report: Report) -> None:
    owned = GROUPS_SCOPE in state["created"]["client_scopes"]
    problem = live.groups_scope_problem()
    if problem == "missing":
        scope_id = kc.create("client-scopes", canonical.groups_scope)
        state["created"]["client_scopes"][GROUPS_SCOPE] = {"id": scope_id}
        save_state(state)
        source = "canonical realm file" if canonical.groups_scope_from_file else "built-in definition"
        report.add("client scope 'groups'", "created", f"from the {source}")
    elif problem and owned:
        scope_id = live.scopes[GROUPS_SCOPE]["id"]
        existing = {m["name"]: m for m in live.scopes[GROUPS_SCOPE].get("protocolMappers") or []}
        for mapper in canonical.groups_scope.get("protocolMappers") or []:
            if mapper["name"] in existing:
                kc.put(f"client-scopes/{scope_id}/protocol-mappers/models/{existing[mapper['name']]['id']}",
                       {**mapper, "id": existing[mapper["name"]]["id"]})
            else:
                kc.create(f"client-scopes/{scope_id}/protocol-mappers/models", mapper)
        report.add("client scope 'groups'", "updated", "mapper restored to the canonical definition")
    elif problem:
        report.add("client scope 'groups'", "unchanged", f"pre-existing, NOT modified, but it {problem}")
        report.note("the pre-existing 'groups' client scope does not emit full group paths; Superset role mapping "
                    "needs claim 'groups' with full paths")
    else:
        report.add("client scope 'groups'", "unchanged", "created by this script" if owned else "pre-existing")
    live.scopes = {s["name"]: s for s in kc.get("client-scopes") or []}


def apply_groups(kc: Kc, live: Live, canonical: Canonical, state: dict[str, Any], report: Report) -> None:
    total = len(canonical.group_paths)
    before = set(live.groups)
    missing_top = [g for g in canonical.top_groups if f"/{g['name']}" not in live.groups]
    detail = []
    if missing_top:
        result = kc.post("partialImport", {
            "ifResourceExists": "SKIP",
            "groups": [canonical.import_group(g, live.roles) for g in missing_top]}) or {}
        detail.append(f"partialImport added={result.get('added', 0)} skipped={result.get('skipped', 0)} "
                      f"errors={result.get('errors', 0)}")
        if result.get("errors"):
            report.note(f"partialImport reported {result['errors']} error(s) for groups; falling back to explicit calls")
        live._load_groups(kc.get("groups", {"max": 1000}) or [])
    explicit = 0
    for path in canonical.group_paths:  # parents first; fills what partialImport skipped
        if path in live.groups:
            continue
        parent, _, name = path.rpartition("/")
        if parent:
            live.groups[path] = kc.create(f"groups/{live.groups[parent]}/children", {"name": name})
        else:
            live.groups[path] = kc.create("groups", {"name": name})
        explicit += 1
    if explicit:
        detail.append(f"{explicit} created with explicit calls")
    new = [p for p in canonical.group_paths if p in live.groups and p not in before]
    for path in new:
        state["created"]["groups"][path] = {"id": live.groups[path]}
    if new:
        save_state(state)
        report.add("groups", "created", f"{len(new)} of {total} canonical groups ({'; '.join(detail)})")
    else:
        owned = len(state["created"]["groups"])
        report.add("groups", "unchanged", f"{total}/{total} canonical groups present "
                                           f"({owned} created by this script, {total - owned} pre-existing)")


def apply_users(kc: Kc, live: Live, canonical: Canonical, state: dict[str, Any], report: Report) -> None:
    total = len(canonical.users)
    missing = []
    for user in canonical.users:
        name = user["username"].lower()
        if name in live.users:
            continue
        clash = live.emails.get((user.get("email") or "").lower())
        if clash:
            report.add(f"user {name}", "skipped", f"e-mail already used by pre-existing user '{clash}'")
            continue
        missing.append(user)
    if missing:
        payload = {"ifResourceExists": "SKIP", "users": [canonical.import_user(u, live.roles) for u in missing]}
        detail = ""
        try:
            result = kc.post("partialImport", payload) or {}
            detail = (f"partialImport added={result.get('added', 0)} skipped={result.get('skipped', 0)} "
                      f"errors={result.get('errors', 0)}")
        except SetupError as exc:
            report.note(f"partialImport of users failed ({str(exc)[:200]}); falling back to explicit calls")
        live._load_users(kc.get("users", {"max": 2000}) or [])
        explicit = 0
        for user in missing:  # whatever partialImport did not create
            name = user["username"].lower()
            if name not in live.users:
                rep = canonical.import_user(user, live.roles)
                rep.pop("realmRoles", None)  # POST /users applies the realm default role itself
                kc.create("users", rep)
                explicit += 1
        if explicit:
            detail = (detail + "; " if detail else "") + f"{explicit} created with explicit calls"
            live._load_users(kc.get("users", {"max": 2000}) or [])
        created = []
        for user in missing:
            name = user["username"].lower()
            if name in live.users:
                state["created"]["users"][name] = {
                    "id": live.users[name]["id"], "created_timestamp": live.users[name].get("createdTimestamp")}
                created.append(name)
        save_state(state)
        # memberships of the users created by this script
        fixed = 0
        for name in created:
            have = {g["path"] for g in live.user_groups.get(name, [])}
            for path in canonical.user_groups(name):
                if path not in have:
                    kc.put(f"users/{live.users[name]['id']}/groups/{live.groups[path]}")
                    fixed += 1
        if fixed:
            detail += f"; {fixed} group membership(s) added with explicit calls"
            live._load_users(kc.get("users", {"max": 2000}) or [])
        report.add("users", "created", f"{len(created)} of {total} canonical users ({detail})")
    else:
        owned = len(state["created"]["users"])
        report.add("users", "unchanged", f"{len([u for u in canonical.usernames() if u in live.users])}/{total} "
                                          f"canonical users present ({owned} created by this script)")
    # membership check (repair only users created by this script)
    for name in canonical.usernames():
        if name not in live.users:
            continue
        want = canonical.user_groups(name)
        have = sorted(g["path"] for g in live.user_groups.get(name, []))
        if have == want:
            continue
        if name in state["created"]["users"]:
            for path in set(want) - set(have):
                kc.put(f"users/{live.users[name]['id']}/groups/{live.groups[path]}")
            report.add(f"user {name}", "updated", "missing group membership(s) restored")
        else:
            report.add(f"user {name}", "unchanged",
                       f"pre-existing, NOT modified; groups {have} differ from canonical {want}")


def apply_demo_password(kc: Kc, live: Live, cfg: Config, canonical: Canonical, state: dict[str, Any],
                        report: Report) -> None:
    present = [n for n in canonical.usernames() if n in live.users]
    if not present:
        report.add("demo password", "skipped", "no canonical user present")
        return
    unavailable = probe_ready(live, cfg)
    current = cfg.secret(DEMO_PASSWORD_KEY)
    candidates: list[tuple[str, str]] = []
    if current:
        candidates.append((current, f"{DEMO_PASSWORD_KEY} in nxtbi/.env"))
    if os.environ.get("NXT_SEED_PASSWORD"):
        candidates.append((os.environ["NXT_SEED_PASSWORD"], "NXT_SEED_PASSWORD in the process environment"))
    documented = discover_documented_passwords(cfg.realm_file)
    candidates += [c for c in documented if c[0] not in [v for v, _ in candidates]]
    documented_values = {v for v, _ in documented}
    if unavailable:
        report.add("demo password", "unverified", unavailable)
        return
    if live.realm.get("bruteForceProtected") and len(candidates) > 2:
        candidates = candidates[:2]  # stay far below any lockout threshold
    works: dict[str, int] = {}  # username -> index of the working candidate
    blocked: dict[str, str] = {}
    try:
        for name in present:
            for index, (value, _) in enumerate(candidates):
                outcome, info = password_grant(cfg, name, value)
                if outcome == "ok":
                    works[name] = index
                    break
                if outcome == "blocked":
                    blocked[name] = info.get("reason", "account not usable")
                    break
    except ProbeUnavailable as exc:
        report.add("demo password", "unverified", str(exc))
        return
    owned = set(state["created"]["users"])
    target_index: int | None = None
    if works:
        counts: dict[int, int] = {}
        for index in works.values():
            counts[index] = counts.get(index, 0) + 1
        # prefer the documented password when it works for somebody, else the most common working candidate
        ranked = sorted(counts, key=lambda i: (candidates[i][0] not in documented_values, -counts[i], i))
        target_index = ranked[0]
    resettable = [n for n in present if n in owned and n not in blocked]
    if target_index is None and not resettable:
        report.add("demo password", "unknown",
                   "no documented password is accepted and every canonical user is pre-existing: nothing changed, "
                   f"{DEMO_PASSWORD_KEY} left as is")
        report.note("demo-user logins are NOT usable: set the password of the canonical users in Keycloak yourself "
                    f"and put it into {DEMO_PASSWORD_KEY}")
        return
    previously_generated = (state.get("demo_password") or {}).get("source") == GENERATED_SOURCE
    if target_index is not None:
        target = candidates[target_index][0]
    else:
        target = current or generate_password()
    if target in documented_values:
        source = next(s for v, s in documented if v == target)
    elif target != current or previously_generated:
        source = GENERATED_SOURCE
    else:
        source = f"{DEMO_PASSWORD_KEY} in nxtbi/.env (origin unknown)"
    generated = target not in documented_values  # i.e. not the NxtDash dev default
    changed, foreign = [], []
    for name in present:
        if works.get(name) == target_index and target_index is not None:
            continue
        if name in blocked:
            foreign.append(f"{name} ({blocked[name]})")
        elif name in owned:
            kc.put(f"users/{live.users[name]['id']}/reset-password",
                   {"type": "password", "temporary": False, "value": target})
            changed.append(name)
        else:
            foreign.append(f"{name} (pre-existing user, password unknown and NOT changed)")
    env_changed = not hmac.compare_digest(current.encode(), target.encode())
    if env_changed:
        write_env_value(ENV_FILE, DEMO_PASSWORD_KEY, target)
        cfg.env_file[DEMO_PASSWORD_KEY] = target
    kind = "non-NxtDash" if generated else "documented"
    state["demo_password"] = {
        "env_key": DEMO_PASSWORD_KEY, "source": source,
        "differs_from_nxtdash": generated,
        "verified_users": sorted(set(n for n in present if works.get(n) == target_index) | set(changed)),
        "unverified_users": sorted(f.split(" ")[0] for f in foreign)}
    save_state(state)
    if changed or env_changed:
        bits = []
        if changed:
            bits.append(f"password set on {len(changed)} user(s) created by this script")
        if env_changed:
            bits.append(f"{DEMO_PASSWORD_KEY} written to nxtbi/.env")
        report.add("demo password", "updated", f"{kind}; " + "; ".join(bits))
    else:
        report.add("demo password", "unchanged",
                   f"{kind} password accepted for {len(present) - len(foreign)}/{len(present)} canonical users; "
                   f"stored in {DEMO_PASSWORD_KEY}")
    if generated:
        report.note(f"the demo-user password ({source}) DIFFERS from the NxtDash dev default")
    else:
        report.note(f"demo-user password source: {source}")
    for item in foreign:
        report.note(f"demo password does not work for {item}")


def apply_admin_user(kc: Kc, live: Live, cfg: Config, state: dict[str, Any], report: Report) -> None:
    name = cfg.admin_username
    password = cfg.secret(ADMIN_PASSWORD_KEY)
    if not password:
        raise SetupError(f"{ADMIN_PASSWORD_KEY} is not set in nxtbi/.env (run: python nxtbi/scripts/gen_env.py)")
    desired = {"username": name, "email": name, "firstName": "Superset", "lastName": "Admin",
               "emailVerified": True, "enabled": True, "requiredActions": []}
    item = f"user {name}"
    user = live.users.get(name)
    if not user:
        if name in live.emails:
            raise SetupError(f"cannot create {name}: the e-mail is used by pre-existing user '{live.emails[name]}'")
        user_id = kc.create("users", {**desired, "credentials": [
            {"type": "password", "value": password, "temporary": False}]})
        state["admin_user"] = {"username": name, "id": user_id, "origin": "created"}
        save_state(state)
        live.users[name] = {**desired, "id": user_id}
        live.user_groups[name] = []
        report.add(item, "created", f"platform admin, no groups, password = {ADMIN_PASSWORD_KEY}")
        return
    changes = []
    if not state.get("admin_user"):
        state["admin_user"] = {"username": name, "id": user["id"], "origin": "adopted"}
        save_state(state)
        report.note(f"{name} existed without a state entry; adopted (teardown keeps it unless --include-adopted)")
    drift = [k for k, v in desired.items() if (user.get(k) or ([] if k == "requiredActions" else None)) != v]
    if drift:
        kc.put(f"users/{user['id']}", {k: desired[k] for k in drift}, merge=True)
        changes.append("fields " + ",".join(drift))
    for group in live.user_groups.get(name, []):
        kc.delete(f"users/{user['id']}/groups/{group['id']}")
        changes.append(f"left group {group['path']}")
    unavailable = probe_ready(live, cfg)
    verified = "password not verified"
    if not unavailable:
        try:
            outcome, info = password_grant(cfg, name, password)
            if outcome == "invalid":
                kc.put(f"users/{user['id']}/reset-password", {"type": "password", "temporary": False, "value": password})
                changes.append(f"password reset to {ADMIN_PASSWORD_KEY}")
                verified = "password set"
            elif outcome == "ok":
                verified = f"password = {ADMIN_PASSWORD_KEY} (login verified)"
            else:
                verified = f"login blocked: {info.get('reason')}"
        except ProbeUnavailable as exc:
            verified = f"password not verified ({exc})"
    if changes:
        report.add(item, "updated", "; ".join(changes))
    else:
        report.add(item, "unchanged", f"no groups; {verified}")


def apply_client(kc: Kc, live: Live, cfg: Config, state: dict[str, Any], report: Report) -> None:
    secret = cfg.secret(CLIENT_SECRET_KEY)
    if not secret:
        raise SetupError(f"{CLIENT_SECRET_KEY} is not set in nxtbi/.env (run: python nxtbi/scripts/gen_env.py)")
    if GROUPS_SCOPE not in live.scopes:
        raise SetupError("client scope 'groups' is missing; cannot configure the client")
    desired = desired_client(cfg, live.scope_names())
    item = f"client {cfg.client_id}"
    changes: list[str] = []
    created = False
    if not live.client:
        client_uuid = kc.create("clients", {**desired, "secret": secret})
        state["client"] = {"clientId": cfg.client_id, "id": client_uuid, "origin": "created"}
        save_state(state)
        created = True
        live.refresh_client()
    elif not state.get("client"):
        state["client"] = {"clientId": cfg.client_id, "id": live.client["id"], "origin": "adopted"}
        save_state(state)
        report.note(f"client {cfg.client_id} existed without a state entry; adopted "
                    "(teardown keeps it unless --include-adopted)")
    client = live.client
    assert client is not None
    client_uuid = client["id"]
    body: dict[str, Any] = {}
    drift = client_field_drift(desired, client)
    if drift:
        for key in drift:
            if key.startswith("attributes."):
                body.setdefault("attributes", {})[key.split(".", 1)[1]] = desired["attributes"][key.split(".", 1)[1]]
            else:
                body[key] = desired[key]
        changes.append("fields " + ",".join(drift))
    if not created:
        current = (kc.get(f"clients/{client_uuid}/client-secret") or {}).get("value") or ""
        if not hmac.compare_digest(current.encode(), secret.encode()):
            body["secret"] = secret
            changes.append(f"secret set from {CLIENT_SECRET_KEY}")
        del current
    if body:
        kc.put(f"clients/{client_uuid}", body, merge=True)
    # client scopes: exact reconciliation (scope lists in a client update are ignored by Keycloak)
    scope_ids = {name: scope["id"] for name, scope in live.scopes.items()}
    have_default = {s["name"] for s in kc.get(f"clients/{client_uuid}/default-client-scopes") or []}
    have_optional = {s["name"] for s in kc.get(f"clients/{client_uuid}/optional-client-scopes") or []}
    want_default, want_optional = set(desired["defaultClientScopes"]), set(desired["optionalClientScopes"])
    for name in sorted(have_default - want_default):
        kc.delete(f"clients/{client_uuid}/default-client-scopes/{scope_ids[name]}")
        changes.append(f"default scope -{name}")
    for name in sorted(have_optional - want_optional):
        kc.delete(f"clients/{client_uuid}/optional-client-scopes/{scope_ids[name]}")
        changes.append(f"optional scope -{name}")
    for name in sorted(want_default - have_default):
        kc.put(f"clients/{client_uuid}/default-client-scopes/{scope_ids[name]}")
        changes.append(f"default scope +{name}")
    for name in sorted(want_optional - have_optional):
        kc.put(f"clients/{client_uuid}/optional-client-scopes/{scope_ids[name]}")
        changes.append(f"optional scope +{name}")
    # protocol mappers
    plan = mapper_drift(desired["protocolMappers"], client.get("protocolMappers") or [])
    for mapper in plan["create"]:
        kc.create(f"clients/{client_uuid}/protocol-mappers/models", mapper)
        changes.append(f"mapper +{mapper['name']}")
    for mapper in plan["update"]:
        kc.put(f"clients/{client_uuid}/protocol-mappers/models/{mapper['id']}", mapper)
        changes.append(f"mapper ~{mapper['name']}")
    for mapper in plan["delete"]:
        kc.delete(f"clients/{client_uuid}/protocol-mappers/models/{mapper['id']}")
        changes.append(f"mapper -{mapper['name']} (realm scope now exists)")
    for mapper in plan["unmanaged"]:
        report.note(f"client has an unmanaged protocol mapper '{mapper['name']}' (left alone)")
    missing_scopes = [s for s in WANTED_DEFAULT_SCOPES if s not in live.scopes]
    fallback = [m["name"] for m in desired["protocolMappers"] if m["name"].startswith(FALLBACK_PREFIX)]
    state["oauth"] = {
        "default_client_scopes": desired["defaultClientScopes"],
        "optional_client_scopes": desired["optionalClientScopes"],
        "realm_scopes_missing": missing_scopes,
        "fallback_protocol_mappers": fallback,
        "recommended_scope_parameter": recommended_scope(desired["defaultClientScopes"],
                                                         desired["optionalClientScopes"]),
        "redirect_uris": desired["redirectUris"],
        "post_logout_redirect_uris": desired["attributes"]["post.logout.redirect.uris"].split("##"),
    }
    save_state(state)
    if created:
        report.add(item, "created", f"default scopes {desired['defaultClientScopes']}, "
                                    f"{len(desired['protocolMappers'])} protocol mapper(s)")
    elif changes:
        report.add(item, "updated", "; ".join(changes))
    else:
        report.add(item, "unchanged", f"default scopes {desired['defaultClientScopes']}")
    if missing_scopes:
        report.note(f"live realm lacks the client scope(s) {missing_scopes}; client-level fallback mappers: "
                    f"{fallback or 'none needed'}")
    report.note("OAuth scope parameter that Keycloak accepts for this client: "
                f"'{state['oauth']['recommended_scope_parameter']}' (unassigned scopes are rejected as invalid_scope)")
    live.refresh_client()


def cmd_apply(cfg: Config, args: argparse.Namespace) -> int:
    canonical = Canonical(cfg.realm_file)
    state = load_state()
    kc = Kc(cfg)
    kc.preflight()
    kc.login()
    try:
        live = Live(kc, cfg, canonical)
        report = Report(f"apply: realm '{cfg.realm}' in container '{cfg.container}'")
        dropped = prune_stale_state(state, live, cfg)
        if dropped:
            report.note(f"stale state entries dropped ({len(dropped)}): the Keycloak container was probably "
                        f"recreated -> {', '.join(dropped[:6])}{' ...' if len(dropped) > 6 else ''}")
        state.update({"container": cfg.container, "realm": cfg.realm, "realm_id": live.realm.get("id")})
        save_state(state)
        apply_groups_scope(kc, live, canonical, state, report)
        apply_groups(kc, live, canonical, state, report)
        apply_users(kc, live, canonical, state, report)
        apply_demo_password(kc, live, cfg, canonical, state, report)
        apply_admin_user(kc, live, cfg, state, report)
        apply_client(kc, live, cfg, state, report)
        save_state(state)
        report.render()
        changed = report.statuses() & {"created", "updated"}
        print("RESULT: " + ("changes applied" if changed else "unchanged"))
        return 0
    finally:
        kc.close()


# --------------------------------------------------------------------------- status


def build_status(live: Live, cfg: Config, canonical: Canonical, state: dict[str, Any], kc: Kc,
                 probe: bool) -> tuple[Report, bool]:
    report = Report(f"status: realm '{cfg.realm}' in container '{cfg.container}' "
                    f"(sslRequired={live.realm.get('sslRequired')})")
    complete = True
    stale = prune_stale_state(state := copy.deepcopy(state), live, cfg)  # ownership as 'apply' would see it
    created = state["created"]

    def owner(kind: str, key: str) -> str:
        return "created by this script" if key in created[kind] else "pre-existing"

    problem = live.groups_scope_problem()
    if problem == "missing":
        report.add("client scope 'groups'", "missing")
        complete = False
    elif problem:
        report.add("client scope 'groups'", "drift", f"{owner('client_scopes', GROUPS_SCOPE)}; {problem}")
        complete = False
    else:
        report.add("client scope 'groups'", "present", owner("client_scopes", GROUPS_SCOPE))
    builtin = [s for s in WANTED_DEFAULT_SCOPES if s != GROUPS_SCOPE]
    report.add("built-in client scopes", "info",
               f"present {[s for s in builtin if s in live.scopes]}, absent {[s for s in builtin if s not in live.scopes]}")
    missing_groups = [p for p in canonical.group_paths if p not in live.groups]
    total = len(canonical.group_paths)
    if missing_groups:
        report.add("groups", "missing", f"{total - len(missing_groups)}/{total} present; missing {missing_groups}")
        complete = False
    else:
        report.add("groups", "present", f"{total}/{total} canonical groups "
                                        f"({len(created['groups'])} created by this script)")
    for name in canonical.usernames():
        want = canonical.user_groups(name)
        if name not in live.users:
            report.add(f"user {name}", "missing", f"canonical groups {want}")
            complete = False
            continue
        have = sorted(g["path"] for g in live.user_groups.get(name, []))
        detail = f"{owner('users', name)}; groups {have}"
        if have != want:
            report.add(f"user {name}", "drift", f"{detail}; canonical {want}")
            complete = False
        else:
            report.add(f"user {name}", "present", detail)
    admin = live.users.get(cfg.admin_username)
    if admin:
        origin = (state.get("admin_user") or {}).get("origin", "not in state file")
        groups = sorted(g["path"] for g in live.user_groups.get(cfg.admin_username, []))
        ok = admin.get("enabled") and admin.get("emailVerified") and not groups
        report.add(f"user {cfg.admin_username}", "present" if ok else "drift",
                   f"{origin}; enabled={admin.get('enabled')} emailVerified={admin.get('emailVerified')} groups {groups}")
        complete = complete and bool(ok)
    else:
        report.add(f"user {cfg.admin_username}", "missing", "platform admin")
        complete = False
    client = live.client
    if client:
        desired = desired_client(cfg, live.scope_names())
        drift = client_field_drift(desired, client)
        scopes_ok = (sorted(client.get("defaultClientScopes") or []) == sorted(desired["defaultClientScopes"])
                     and sorted(client.get("optionalClientScopes") or []) == sorted(desired["optionalClientScopes"]))
        plan = mapper_drift(desired["protocolMappers"], client.get("protocolMappers") or [])
        mappers_ok = not (plan["create"] or plan["update"] or plan["delete"])
        origin = (state.get("client") or {}).get("origin", "not in state file")
        ok = not drift and scopes_ok and mappers_ok
        report.add(f"client {cfg.client_id}", "present" if ok else "drift",
                   f"{origin}; id {client['id']}" + (f"; drift in {drift}" if drift else "")
                   + ("" if scopes_ok else "; client scopes differ") + ("" if mappers_ok else "; protocol mappers differ"))
        attributes = client.get("attributes") or {}
        report.add("  confidential / flows", "info",
                   f"publicClient={client.get('publicClient')} standardFlow={client.get('standardFlowEnabled')} "
                   f"directGrants={client.get('directAccessGrantsEnabled')} implicit={client.get('implicitFlowEnabled')} "
                   f"serviceAccounts={client.get('serviceAccountsEnabled')} fullScopeAllowed={client.get('fullScopeAllowed')} "
                   f"pkce={attributes.get('pkce.code.challenge.method')}")
        report.add("  redirectUris", "info", str(sorted(client.get("redirectUris") or [])))
        report.add("  webOrigins", "info", str(sorted(client.get("webOrigins") or [])))
        report.add("  post-logout redirect URIs", "info", str((attributes.get("post.logout.redirect.uris") or "").split("##")))
        report.add("  default client scopes", "info", str(sorted(client.get("defaultClientScopes") or [])))
        report.add("  optional client scopes", "info", str(sorted(client.get("optionalClientScopes") or [])))
        report.add("  protocol mappers", "info", str(sorted(m["name"] for m in client.get("protocolMappers") or [])))
        report.add("  scope parameter to request", "info",
                   f"'{recommended_scope(client.get('defaultClientScopes') or [], client.get('optionalClientScopes') or [])}'")
        complete = complete and ok
    else:
        report.add(f"client {cfg.client_id}", "missing")
        complete = False
    for key in (CLIENT_SECRET_KEY, ADMIN_PASSWORD_KEY, DEMO_PASSWORD_KEY):
        report.add(f"nxtbi/.env {key}", "set" if cfg.secret(key) else "NOT SET")
    demo = state.get("demo_password") or {}
    if demo:
        report.add("demo password source", "info", f"{demo.get('source')}"
                   + ("; DIFFERS from the NxtDash dev default" if demo.get("differs_from_nxtdash") else ""))
    if not cfg.secret(DEMO_PASSWORD_KEY):
        complete = False
    if probe:
        unavailable = probe_ready(live, cfg)
        targets = [(n, DEMO_PASSWORD_KEY) for n in canonical.usernames() if n in live.users]
        if admin:
            targets.append((cfg.admin_username, ADMIN_PASSWORD_KEY))
        for name, key in targets:
            if unavailable or not cfg.secret(key):
                report.add(f"login {name}", "not checked", unavailable or f"{key} not set")
                continue
            try:
                outcome, info = password_grant(cfg, name, cfg.secret(key))
            except ProbeUnavailable as exc:
                report.add(f"login {name}", "not checked", str(exc))
                continue
            report.add(f"login {name}", "ok" if outcome == "ok" else "FAILED",
                       f"password grant with {key}" + (f" ({info.get('reason')})" if outcome == "blocked" else ""))
            complete = complete and outcome == "ok"
    if stale:
        report.note(f"state file is stale for {len(stale)} entr{'y' if len(stale) == 1 else 'ies'} "
                    "(Keycloak container recreated?); 'apply' repairs it")
    if not STATE_FILE.is_file():
        report.note("no state file yet (nxtbi/.keycloak-state.json)")
    return report, complete


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    canonical = Canonical(cfg.realm_file)
    state = load_state()
    kc = Kc(cfg)
    kc.preflight()
    kc.login()
    try:
        live = Live(kc, cfg, canonical)
        report, complete = build_status(live, cfg, canonical, state, kc, args.probe_logins)
        report.render()
        print("RESULT: " + ("complete" if complete else "incomplete (run: python nxtbi/scripts/keycloak_setup.py apply)"))
        return 0 if complete or not args.strict else 2
    finally:
        kc.close()


# --------------------------------------------------------------------------- verify


def _authorize_probe(cfg: Config, scope: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": cfg.client_id, "response_type": "code", "scope": scope,
        "redirect_uri": cfg.superset_origins()[0] + PROVIDER_CALLBACK, "state": "nxtbi-verify",
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM", "code_challenge_method": "S256"})
    url = f"{cfg.probe_url}/realms/{cfg.realm}/protocol/openid-connect/auth?{query}"

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a: Any, **k: Any) -> None:  # noqa: D401
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=15) as response:
            return f"HTTP {response.status} (login page)"
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location", "")
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        error = (params.get("error") or [""])[0]
        if error:
            return f"HTTP {exc.code} error={error} ({(params.get('error_description') or [''])[0]})"
        return f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError) as exc:
        return f"not reachable: {exc}"


def _jwt_claims(token: str) -> dict[str, Any]:
    """Payload of a JWT received straight from the token endpoint (no signature check needed here)."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def code_flow(cfg: Config, username: str, password: str, scope: str, backchannel: str | None = None) -> dict[str, Any]:
    """Real authorization-code + PKCE login as the Superset client, the way a browser would do it.

    Authorize -> post the Keycloak login form -> exchange the code with the client secret ->
    userinfo -> RP-initiated logout. Nothing is sent to Superset: redirects are not followed.
    Returns the id-token claims, the userinfo document and the outcome of each leg.
    'backchannel' sends the token leg to another base URL than the browser legs, which is the
    split-hostname set-up Superset uses. Keycloak (hostname-strict=false) stamps the tokens with the issuer
    of the host the BROWSER logged in on, whatever host the token endpoint is called on, and its userinfo
    endpoint only accepts a token on that same host.
    """
    out: dict[str, Any] = {"ok": False, "step": "authorize"}
    base = f"{cfg.probe_url}/realms/{cfg.realm}/protocol/openid-connect"
    origin = cfg.superset_origins()[0]
    redirect_uri = origin + PROVIDER_CALLBACK
    back = f"{(backchannel or cfg.probe_url).rstrip('/')}/realms/{cfg.realm}"
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a: Any, **k: Any) -> None:
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    # Keycloak marks its cookies 'Secure' even on http://localhost (browsers accept that for loopback,
    # http.cookiejar does not), so the few cookies of this exchange are carried by hand.
    cookies: dict[str, str] = {}

    def remember(headers: Any) -> None:
        for raw in headers.get_all("Set-Cookie") or []:
            name, _, value = raw.split(";", 1)[0].partition("=")
            if value:
                cookies[name.strip()] = value.strip()
            else:
                cookies.pop(name.strip(), None)

    def call(url: str, form: dict[str, str] | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, str, str]:
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        request = urllib.request.Request(url, data=data, headers=dict(headers or {}))
        if cookies and url.startswith(cfg.probe_url + "/"):
            request.add_header("Cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()))
        try:
            with opener.open(request, timeout=20) as response:
                remember(response.headers)
                return response.status, response.read().decode("utf-8", "replace"), ""
        except urllib.error.HTTPError as exc:
            remember(exc.headers)
            return exc.code, exc.read().decode("utf-8", "replace"), exc.headers.get("Location", "")

    try:
        state = secrets.token_urlsafe(12)
        status, html, location = call(base + "/auth?" + urllib.parse.urlencode({
            "client_id": cfg.client_id, "response_type": "code", "scope": scope, "redirect_uri": redirect_uri,
            "state": state, "nonce": secrets.token_urlsafe(12),
            "code_challenge": challenge, "code_challenge_method": "S256"}))
        if status != 200:
            out["error"] = f"no login page (HTTP {status} {location[:160]})"
            return out
        out["step"] = "login"
        pages = 0
        # The realm may ask for the username first and the password on a second page (identity-first login).
        while status == 200 and pages < 4:
            match = re.search(r'<form[^>]*\baction="([^"]+)"', html)
            fields = set(re.findall(r'<input[^>]*\bname="([^"]+)"', html))
            if not match or not fields & {"username", "password"}:
                break
            form = {"credentialId": ""}
            if "username" in fields:
                form["username"] = username
            if "password" in fields:
                form["password"] = password
            pages += 1
            status, html, location = call(html_unescape(match.group(1)), form)
        out["login_pages"] = pages
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(location).query)
        if status not in (302, 303) or not location.startswith(redirect_uri) or "code" not in params:
            out["error"] = (f"login did not end in a redirect with a code (HTTP {status} after {pages} form page(s); "
                            "required action, wrong password or an extra login step?)")
            return out
        out["callback"] = location.split("?", 1)[0]
        out["state_echoed"] = params.get("state") == [state]
        out["step"] = "token"
        status, body, _ = call(back + "/protocol/openid-connect/token", {
            "grant_type": "authorization_code", "code": params["code"][0], "redirect_uri": redirect_uri,
            "client_id": cfg.client_id, "client_secret": cfg.secret(CLIENT_SECRET_KEY), "code_verifier": verifier})
        tokens = json.loads(body) if body.startswith("{") else {}
        if status != 200 or "id_token" not in tokens:
            out["error"] = f"token exchange failed (HTTP {status} {tokens.get('error', '')} {tokens.get('error_description', '')})"
            return out
        out["id_token"] = _jwt_claims(tokens["id_token"])
        out["access_token"] = _jwt_claims(tokens["access_token"])
        out["step"] = "userinfo"
        out["issuer_expected"] = f"{cfg.probe_url}/realms/{cfg.realm}"
        bearer = {"Authorization": "Bearer " + tokens["access_token"]}
        if backchannel:
            out["userinfo_backchannel_status"] = call(back + "/protocol/openid-connect/userinfo", headers=bearer)[0]
        status, body, _ = call(base + "/userinfo", headers={"Authorization": "Bearer " + tokens["access_token"]})
        out["userinfo_status"] = status
        out["userinfo"] = json.loads(body) if status == 200 and body.startswith("{") else {}
        out["step"] = "logout"
        post_logout = origin + POST_LOGOUT_PATH
        status, _, location = call(base + "/logout?" + urllib.parse.urlencode({
            "client_id": cfg.client_id, "id_token_hint": tokens["id_token"],
            "post_logout_redirect_uri": post_logout}))
        out["logout"] = f"HTTP {status} -> {location or '(no redirect: confirmation page)'}"
        out["logout_ok"] = status in (302, 303) and location.startswith(post_logout)
        out["ok"] = True
        return out
    except (urllib.error.URLError, OSError, ValueError) as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


def cmd_verify(cfg: Config, args: argparse.Namespace) -> int:
    canonical = Canonical(cfg.realm_file)
    kc = Kc(cfg)
    kc.preflight()
    kc.login()
    failures = 0
    try:
        live = Live(kc, cfg, canonical)
        if not live.client:
            raise SetupError(f"client {cfg.client_id} does not exist; run 'apply' first")
        client_uuid = live.client["id"]
        names = args.user or ["planning.admin@nxtbi.local", "stats.editor@nxtbi.local", "unaffiliated@nxtbi.local",
                              cfg.admin_username]
        print(f"verify: example tokens for client {cfg.client_id} (scope=openid), from Keycloak evaluate-scopes")
        for name in names:
            name = name.lower()
            user = live.users.get(name)
            if not user:
                found = kc.get("users", {"username": name, "exact": "true"}, fields="id,username")
                user = found[0] if found else None
            if not user:
                print(f"  {name}: MISSING user")
                failures += 1
                continue
            query = {"scope": "openid", "userId": user["id"]}
            id_token, access_token = kc.get_many([
                (f"clients/{client_uuid}/evaluate-scopes/generate-example-id-token", query),
                (f"clients/{client_uuid}/evaluate-scopes/generate-example-access-token", query)])
            id_token, access_token = id_token or {}, access_token or {}
            expected = canonical.user_groups(name) if name in canonical.usernames() else []
            aud = access_token.get("aud")
            aud_list = aud if isinstance(aud, list) else [aud]
            checks = {
                "preferred_username": id_token.get("preferred_username") == name,
                "email": bool(id_token.get("email")),
                "given_name": bool(id_token.get("given_name")),
                "family_name": bool(id_token.get("family_name")),
                "groups": sorted(id_token.get("groups") or []) == expected,
                "sub": bool(id_token.get("sub")),
                "id_token aud": cfg.client_id in (id_token.get("aud") if isinstance(id_token.get("aud"), list)
                                                  else [id_token.get("aud")]),
                "access_token aud": cfg.client_id in aud_list,
            }
            ok = all(checks.values())
            failures += 0 if ok else 1
            print(f"  {name}: {'OK' if ok else 'FAILED ' + str([k for k, v in checks.items() if not v])}")
            shown = {k: id_token.get(k, "(claim absent)") for k in (
                "preferred_username", "email", "email_verified", "given_name", "family_name", "name", "groups",
                "aud", "azp")}
            shown["sub"] = "present" if id_token.get("sub") else "ABSENT"
            print(f"      id_token     {json.dumps(shown, ensure_ascii=True)}")
            print(f"      access_token {json.dumps({'aud': aud, 'azp': access_token.get('azp'), 'scope': access_token.get('scope'), 'groups': access_token.get('groups'), 'sub': 'present' if access_token.get('sub') else 'ABSENT'}, ensure_ascii=True)}")
        print("verify: authorize endpoint scope acceptance (GET, no login performed)")
        assigned = recommended_scope(live.client.get("defaultClientScopes") or [],
                                     live.client.get("optionalClientScopes") or [])
        for scope in dict.fromkeys(["openid", assigned, "openid profile email groups"]):
            outcome = _authorize_probe(cfg, scope)
            marker = "" if scope != assigned or outcome.startswith("HTTP 200") else "  <-- FAILED"
            failures += 1 if marker else 0
            print(f"  scope='{scope}': {outcome}{marker}")
        if args.no_login_flow:
            print("verify: authorization-code login flow skipped (--no-login-flow)")
        else:
            if args.backchannel_url:
                print(f"verify: the token leg goes to the back-channel URL {args.backchannel_url}")
            print(f"verify: real authorization-code + PKCE login as client {cfg.client_id} at {cfg.probe_url} "
                  f"(scope='{assigned}', client secret from {CLIENT_SECRET_KEY}, session logged out again)")
            for name in names:
                name = name.lower()
                key = ADMIN_PASSWORD_KEY if name == cfg.admin_username else DEMO_PASSWORD_KEY
                if not cfg.secret(key) or not cfg.secret(CLIENT_SECRET_KEY):
                    print(f"  {name}: not checked ({key} or {CLIENT_SECRET_KEY} not set)")
                    failures += 1
                    continue
                flow = code_flow(cfg, name, cfg.secret(key), assigned, args.backchannel_url)
                if not flow["ok"]:
                    print(f"  {name}: FAILED at step '{flow['step']}': {flow.get('error')}")
                    failures += 1
                    continue
                claims, userinfo = flow["id_token"], flow["userinfo"]
                expected = canonical.user_groups(name) if name in canonical.usernames() else []
                aud = flow["access_token"].get("aud")
                checks = {
                    "id_token preferred_username": claims.get("preferred_username") == name,
                    "id_token email/given_name/family_name": all(claims.get(k) for k in ("email", "given_name", "family_name")),
                    "id_token sub/aud/nonce": all(claims.get(k) for k in ("sub", "aud", "nonce")),
                    "id_token iss == browser-side issuer": claims.get("iss") == flow["issuer_expected"],
                    "id_token groups": sorted(claims.get("groups") or []) == expected,
                    "userinfo": flow["userinfo_status"] == 200 and userinfo.get("preferred_username") == name
                    and sorted(userinfo.get("groups") or []) == expected,
                    "access_token aud": cfg.client_id in (aud if isinstance(aud, list) else [aud]),
                    "state echoed": flow["state_echoed"],
                    "logout redirect": flow["logout_ok"],
                }
                ok = all(checks.values())
                failures += 0 if ok else 1
                print(f"  {name}: {'OK' if ok else 'FAILED ' + str([k for k, v in checks.items() if not v])}")
                shown = {k: claims.get(k, "(claim absent)") for k in (
                    "iss", "aud", "azp", "preferred_username", "email", "given_name", "family_name", "groups")}
                print(f"      id_token  {json.dumps(shown, ensure_ascii=True)}")
                print(f"      userinfo  HTTP {flow['userinfo_status']} "
                      f"{json.dumps({k: userinfo.get(k, '(claim absent)') for k in ('preferred_username', 'email', 'groups')}, ensure_ascii=True)}")
                print(f"      access    aud={json.dumps(aud)} scope='{flow['access_token'].get('scope')}'")
                if "userinfo_backchannel_status" in flow:
                    print(f"      userinfo on the back-channel host: HTTP {flow['userinfo_backchannel_status']} "
                          "(401 is expected when that host differs from the token issuer)")
                print(f"      callback  {flow['callback']} ({flow['login_pages']} login form page(s))   "
                      f"logout {flow['logout']}")
        print("verify: password grants via the public client "
              f"'{cfg.probe_client_id}' at {cfg.probe_url} (sessions are closed again)")
        unavailable = probe_ready(live, cfg)
        targets = [(n, DEMO_PASSWORD_KEY) for n in canonical.usernames() if n in live.users]
        targets.append((cfg.admin_username, ADMIN_PASSWORD_KEY))
        for name, key in targets:
            if unavailable or not cfg.secret(key):
                print(f"  {name}: not checked ({unavailable or key + ' not set'})")
                failures += 1
                continue
            try:
                outcome, info = password_grant(cfg, name, cfg.secret(key))
            except ProbeUnavailable as exc:
                print(f"  {name}: not checked ({exc})")
                failures += 1
                continue
            failures += 0 if outcome == "ok" else 1
            print(f"  {name}: {'OK' if outcome == 'ok' else 'FAILED'} with {key}"
                  + (f" ({info.get('reason')})" if outcome == "blocked" else ""))
        print("RESULT: " + ("all checks passed" if not failures else f"{failures} check(s) failed"))
        return 0 if not failures else 2
    finally:
        kc.close()


# --------------------------------------------------------------------------- teardown


def cmd_teardown(cfg: Config, args: argparse.Namespace) -> int:
    if not STATE_FILE.is_file():
        print("teardown: no state file (nxtbi/.keycloak-state.json): nothing recorded, nothing removed")
        return 0
    canonical = Canonical(cfg.realm_file)
    state = load_state()
    if state.get("container") and state["container"] != cfg.container:
        raise SetupError(f"state file belongs to container '{state['container']}', not '{cfg.container}'")
    if state.get("realm") and state["realm"] != cfg.realm:
        raise SetupError(f"state file belongs to realm '{state['realm']}', not '{cfg.realm}'")
    kc = Kc(cfg)
    kc.preflight()
    kc.login()
    try:
        live = Live(kc, cfg, canonical)
        dry = args.dry_run
        removed = "would remove" if dry else "removed"
        report = Report(f"teardown{' (dry run, nothing is deleted)' if dry else ''}: realm '{cfg.realm}' "
                        f"in container '{cfg.container}'")

        def persist() -> None:
            if not dry:
                save_state(state)

        def drop(path: str) -> None:
            if not dry:
                kc.delete(path)

        for item in prune_stale_state(state, live, cfg):
            report.add(item, "skipped", "recorded id no longer exists in Keycloak (stale state entry dropped)")
        created = state["created"]
        doomed_users: set[str] = set()
        doomed_clients: set[str] = set()
        client = state.get("client")
        if client:
            if client.get("origin") == "created" or args.include_adopted:
                drop(f"clients/{client['id']}")
                report.add(f"client {client['clientId']}", removed)
                doomed_clients.add(client["clientId"])
                state["client"] = None
                state["oauth"] = None
            else:
                report.add(f"client {client['clientId']}", "kept", "adopted, not created by this script "
                                                                     "(--include-adopted removes it)")
        admin = state.get("admin_user")
        if admin:
            if admin.get("origin") == "created" or args.include_adopted:
                drop(f"users/{admin['id']}")
                report.add(f"user {admin['username']}", removed)
                doomed_users.add(admin["id"])
                state["admin_user"] = None
            else:
                report.add(f"user {admin['username']}", "kept", "adopted, not created by this script "
                                                                  "(--include-adopted removes it)")
        persist()
        for name in sorted(created["users"]):
            drop(f"users/{created['users'][name]['id']}")
            report.add(f"user {name}", removed)
            doomed_users.add(created["users"][name]["id"])
            del created["users"][name]
        if not created["users"]:
            state["demo_password"] = None
        persist()
        # Groups: a group goes only when everything below it and in it was created by this script.
        recorded = created["groups"]
        paths = sorted(recorded)
        lookups = kc.get_many(
            [(f"groups/{recorded[p]['id']}/children", {"max": 1000}) for p in paths]
            + [(f"groups/{recorded[p]['id']}/members", {"max": 1000}) for p in paths])
        children = dict(zip(paths, lookups[:len(paths)]))
        members = dict(zip(paths, lookups[len(paths):]))
        removable: dict[str, bool] = {}
        reason: dict[str, str] = {}
        for path in sorted(paths, key=lambda p: (-p.count("/"), p)):  # deepest first
            foreign = [c["name"] for c in children[path] or [] if not removable.get(f"{path}/{c['name']}")]
            others = [m.get("username", m["id"]) for m in members[path] or [] if m["id"] not in doomed_users]
            removable[path] = not foreign and not others
            if foreign:
                reason[path] = f"subgroup(s) {foreign} are kept or were not created by this script"
            elif others:
                reason[path] = f"it still has {len(others)} member(s) this script did not create"
        for path in paths:  # parents first: Keycloak deletes a group together with its subgroups
            if not removable[path]:
                report.add(f"group {path}", "kept", reason[path])
                continue
            parent = path.rpartition("/")[0]
            if removable.get(parent):
                report.add(f"group {path}", removed, "together with its parent")
            else:
                drop(f"groups/{recorded[path]['id']}")
                report.add(f"group {path}", removed)
            del recorded[path]
        persist()
        for name in sorted(created["client_scopes"]):
            scope_id = created["client_scopes"][name]["id"]
            users_of = [c["clientId"] for c in kc.get(
                "clients", {"max": 1000}, fields="clientId,defaultClientScopes,optionalClientScopes") or []
                if name in (c.get("defaultClientScopes") or []) + (c.get("optionalClientScopes") or [])
                and c["clientId"] not in doomed_clients]
            if users_of:
                report.add(f"client scope {name}", "kept", f"still assigned to client(s) {users_of}")
                continue
            drop(f"client-scopes/{scope_id}")
            report.add(f"client scope {name}", removed)
            del created["client_scopes"][name]
        persist()
        if not report.rows:
            report.add("(nothing)", "unchanged", "the state file lists nothing that still exists")
        if state_is_empty(state) and not dry:
            STATE_FILE.unlink(missing_ok=True)
            report.note("state file removed")
        report.note(f"{DEMO_PASSWORD_KEY} in nxtbi/.env {'is' if dry else 'was'} left as is")
        report.render()
        return 0
    finally:
        kc.close()


# --------------------------------------------------------------------------- show-credentials


def cmd_show_credentials(cfg: Config, args: argparse.Namespace) -> int:
    canonical = Canonical(cfg.realm_file)
    state = load_state()
    demo = state.get("demo_password") or {}
    verified = set(demo.get("verified_users") or [])
    print(f"Keycloak realm '{cfg.realm}' demo logins (login page: {cfg.public_url}/login/)")
    print(f"  password file: {ENV_FILE}")
    print(f"  {'username':<34} {'password key':<28} groups")
    for name in canonical.usernames():
        flag = "" if name in verified or not demo else "  [password NOT verified for this user]"
        print(f"  {name:<34} {DEMO_PASSWORD_KEY:<28} {canonical.user_groups(name) or '(none: login is rejected by Superset)'}{flag}")
    print(f"  {cfg.admin_username:<34} {ADMIN_PASSWORD_KEY:<28} (none; Superset Admin via NXTBI_PLATFORM_ADMINS)")
    if demo:
        print(f"  demo password source: {demo.get('source')}"
              + ("  -> DIFFERS from the NxtDash dev default" if demo.get("differs_from_nxtdash") else ""))
    else:
        print("  demo password source: unknown (run 'apply' first)")
    for key in (DEMO_PASSWORD_KEY, ADMIN_PASSWORD_KEY):
        value = cfg.secret(key)
        if args.reveal:
            print(f"  {key} = {value if value else '(not set)'}")
        else:
            print(f"  {key}: {'set' if value else 'NOT SET'} (value hidden; use --reveal to print it)")
    return 0


# --------------------------------------------------------------------------- entry point


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keycloak_setup.py", formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__)
    parser.add_argument("command", nargs="?", default="apply",
                        choices=["apply", "status", "verify", "teardown", "show-credentials"])
    parser.add_argument("--container", help="Keycloak container name (KEYCLOAK_CONTAINER)")
    parser.add_argument("--realm", help="realm name (KEYCLOAK_REALM)")
    parser.add_argument("--client-id", help="OIDC client id (KEYCLOAK_CLIENT_ID)")
    parser.add_argument("--realm-file", help="canonical realm definition (NXTBI_REALM_FILE)")
    parser.add_argument("--keycloak-url", help="host-reachable Keycloak base URL for login probes (KEYCLOAK_BROWSER_URL)")
    parser.add_argument("--probe-logins", action="store_true", help="status: also try a password grant per demo user")
    parser.add_argument("--strict", action="store_true", help="status: exit code 2 when something is missing")
    parser.add_argument("--user", action="append", help="verify: username to evaluate (repeatable)")
    parser.add_argument("--backchannel-url",
                        help="verify: base URL for the token leg of the login flow when it differs from the "
                             "browser URL (split-hostname check; must be reachable from this host)")
    parser.add_argument("--no-login-flow", action="store_true",
                        help="verify: skip the real authorization-code login (which opens and closes a session)")
    parser.add_argument("--include-adopted", action="store_true",
                        help="teardown: also remove the client / platform admin that existed without a state entry")
    parser.add_argument("--dry-run", action="store_true", help="teardown: only print what would be removed")
    parser.add_argument("--reveal", action="store_true", help="show-credentials: print the password values")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    try:
        cfg = Config(args)
        handler = {"apply": cmd_apply, "status": cmd_status, "verify": cmd_verify, "teardown": cmd_teardown,
                   "show-credentials": cmd_show_credentials}[args.command]
        return handler(cfg, args)
    except SetupError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
