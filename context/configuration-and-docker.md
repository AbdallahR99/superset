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
| `nxtbi/superset-fork:local` | What the main demo runs. Built from `master` (same image as `:widgets`) |
| `nxtbi/superset-fork:widgets` | What the widgets stack runs. Built from `master` |
| `nxtbi/superset-fork:rtl-only` | Previous main-demo image (RTL branch only); kept for rollback |
| `nxtbi/fe-build:local` | Node toolchain for webpack, tsc and Jest on Linux (`--target superset-node-ci`) |

Build (about 15 minutes cold, 12 GB of memory):

```bash
docker build --target superset --build-arg BUILD_TRANSLATIONS=true -t nxtbi/superset-fork:local .
```

Without `BUILD_TRANSLATIONS=true` Arabic pages are right-to-left with English text.

## Start

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
