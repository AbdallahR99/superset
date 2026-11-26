# Configuration and Docker

## Stacks

| Compose project | File | Ports (127.0.0.1) | Purpose |
|---|---|---|---|
| `nxtbi-superset` | `nxtbi/docker-compose.yml` | 8088 web, 5008 MCP | Main demo, Keycloak login, `DASHBOARD_V2` off |
| `nxtbi-widgets` | `nxtbi/widgets/docker-compose.yml` | 8089 web, 8099 flag-off copy, 5009 MCP | Dashboard V2 and widgets, database login, own database |
| (dev overlay) | `nxtbi/docker-compose.dev.yml` | none | `fe-build` runner and source mounts for the main demo |

External, not managed here: Keycloak `ld-shared-keycloak-1` (port 8180, realm `nxtbi`), Mailpit (8025).

## Images

| Tag | Content |
|---|---|
| `nxtbi/superset-fork:local` | Main demo Compose tag. Points to the verified stabilization image. |
| `nxtbi/superset-fork:stabilization-final`, `nxtbi/superset-fork:stabilization-release` | Verified release image, ID `sha256:e8c6d3e617875c5b9eacd15c88ef2588129301457906bbc0d787bd6604eec270`. |
| `nxtbi/superset-fork:upstream-sync-2c58859901` | Current upstream-sync base. PostgreSQL and browser verification used the corrected artifact. See the [November 26 checks](testing.md#november-26-upstream-sync). |
| `nxtbi/superset-fork:copilot-upstream-sync-2c58859901` | Verification Copilot web overlay built on the corrected upstream-sync base. |
| `nxtbi/superset-fork:upstream-sync-6e54f477a0` | Previous baseline built from `1908387364` for isolated verification. See [upstream sync verification](testing.md#upstream-sync-verification). |
| `nxtbi/superset-fork:main-demo-pre-stabilization` | Immediate main demo rollback, ID `sha256:03ab240d8c365b6aa2281707335860451d40a41d14b907a3df305b66b77d07bc`. |
| `nxtbi/superset-fork:widgets` | Image for the existing widgets stack. Shares the pre-stabilization image ID. |
| `nxtbi/superset-fork:rtl-only` | Older RTL-branch image retained locally. |
| `nxtbi/fe-build:local` | Node toolchain for webpack, tsc and Jest on Linux (`--target superset-node-ci`) |

Build (about 15 minutes cold, 12 GB of memory):

```bash
docker build --target superset --build-arg BUILD_TRANSLATIONS=true -t nxtbi/superset-fork:local .
```

Without `BUILD_TRANSLATIONS=true` Arabic pages are right-to-left with English text.

## Start or refresh the existing main demo

Run from the repository root with the existing `nxtbi/.env`, config, and volumes.
For a full start, including the standard init job, use the first command. To
refresh an already running stack with the verified image, use the tag and
application-only commands below. The November 18 rollout refreshed only the
four listed app services and kept PostgreSQL, Redis, init, and shared Keycloak
in place. The database was already at `3c9e1a7b5d2f`.

```bash
docker compose -p nxtbi-superset -f nxtbi/docker-compose.yml up -d --no-build --pull never --wait --wait-timeout 180
```

```bash
docker tag nxtbi/superset-fork:stabilization-final nxtbi/superset-fork:local
docker compose -p nxtbi-superset -f nxtbi/docker-compose.yml up -d --no-deps --no-build --pull never --wait --wait-timeout 180 superset superset-worker superset-beat superset-mcp
```

To roll back the application, tag `nxtbi/superset-fork:main-demo-pre-stabilization`
as `nxtbi/superset-fork:local` and rerun the same four-service Compose command.
The release and rollback images use the same migration head. Check the
[web health endpoint](http://localhost:8088/health) and
[MCP health endpoint](http://localhost:5008/health) after either change.

## First-time setup

Generate settings and provision the demo Keycloak entries only when setting up
a fresh main demo. Existing deployments use the startup commands above.

```bash
python nxtbi/scripts/gen_env.py
```

```bash
python nxtbi/scripts/keycloak_setup.py apply
```

```bash
docker compose -f nxtbi/docker-compose.yml up -d
```

Widgets stack:

```bash
python nxtbi/widgets/scripts/gen_env.py
```

```bash
docker compose -f nxtbi/widgets/docker-compose.yml --profile flag-off --profile mcp up -d
```

Builder: `http://localhost:8089/dashboard/v2/new/`. Example app:
`python nxtbi/widgets/scripts/example_app.py` (port 5173) and with `--guest` (port 5174).

## Stabilization validation

The verified release is `nxtbi/superset-fork:stabilization-final`. It reuses the
merged production image's dependency layers and packages the stabilization
source, freshly built production webpack assets, and compiled browser
translations inside the image. The validation containers mount stack
configuration and the test extension bundle as read-only files.

The local validation commands below run from the repository root on this
workstation. The ignored validation directory holds the Compose overlays and
generated credentials for the isolated projects. The demo helper uses the
seeded validation database and its running isolated Keycloak and Mailpit.

```powershell
pwsh -File nxtbi/out/stabilization/start-widgets-final.ps1
pwsh -File nxtbi/out/stabilization/start-demo-final.ps1
```

| Validation endpoint | Purpose |
|---|---|
| `http://localhost:18088` | Demo with isolated Keycloak, Dashboard V2 disabled |
| `http://localhost:18089/dashboard/v2/new/` | Dashboard V2 builder with production CSP |
| `http://localhost:18099` | Widgets flag-off control |
| `http://localhost:15009/mcp` | Widgets MCP |
| `http://localhost:18180` | Disposable Keycloak realm |
| `http://localhost:15173`, `http://localhost:15174` | Session and guest-token widget hosts |
| `http://localhost:28089/health` | Separate cold-start check using fresh PostgreSQL and Redis |

## Key configuration

Main demo (`nxtbi/config/superset_config.py`): `AUTH_TYPE = AUTH_OAUTH` with provider `keycloak`,
`AUTH_ROLES_SYNC_AT_LOGIN`, feature flags `EMBEDDED_SUPERSET`, `ENABLE_TEMPLATE_PROCESSING`,
`THUMBNAILS`, `ALERT_REPORTS`, `RLS_IN_SQLLAB`; Redis caches; `LANGUAGES` with `ar`.

Fork-level keys in `superset/config.py`:

| Key | Default | Meaning |
|---|---|---|
| `RTL_LAYOUT_ENABLED` | `True` | `False` keeps every locale left-to-right |
| `FEATURE_FLAGS["DASHBOARD_V2"]` | `False` | Enables the V2 API, the builder and the widget routes |
| `DASHBOARD_V2_MAX_NODES`, `_MAX_DEPTH`, `_MAX_DOCUMENT_BYTES`, `_MAX_VALUE_DEPTH` | 500, 16, 1048576, 32 | Document limits (the first two reach the client through bootstrap) |
| `GUEST_TOKEN_WIDGET_RLS_GUARD` | `True` | Mint-time RLS check for `widget` / `dataset` guest resources |

Widgets stack (`nxtbi/widgets/config/superset_config.py`, switches in `nxtbi/widgets/.env`):
`NXTBI_WIDGETS_AUTH=db|keycloak`, `NXTBI_WIDGETS_DASHBOARD_V2=on|off`, `NXTBI_WIDGETS_CORS_ORIGINS`,
`NXTBI_WIDGETS_EXTENSIONS`, a `WidgetGuest` role with only `can read on Chart`, a guest-token validator
hook, and a raised rate limit (400 per second; the default 50 per second per address is too low for an
embedding page).

To embed in production a host needs: `DASHBOARD_V2` and `EMBEDDED_SUPERSET` on; CORS for its origin
with headers `Content-Type`, `X-GuestToken`, `X-CSRFToken`, `If-Match`; a guest role; and a service
account with `can grant guest token` that is an admin or not RLS-restricted on what it grants. The main
demo config does not have these yet (it uses `GUEST_ROLE_NAME = "Public"` and no CORS); port them from
the widgets config before enabling `DASHBOARD_V2` for guests there.

## Frontend build loop (no image rebuild)

```bash
docker compose -f nxtbi/docker-compose.yml -f nxtbi/docker-compose.dev.yml run --rm fe-build dev
```

Modes: `dev`, `prod`, `translations`, `type`, `test <jest args>` (see `nxtbi/dev/fe-build.sh`).
