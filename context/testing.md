# Tests

Host scripts need Python 3.11+ and `PYTHONIOENCODING=utf-8` on Windows. Results below are from
2026-11-17 on the image built from `master` after both merges.

## Main demo (`http://localhost:8088`, Keycloak login, `DASHBOARD_V2` off)

| Check | Command | Last result |
|---|---|---|
| API and stack smoke | `python nxtbi/scripts/smoke_test.py` | 48 / 48 |
| Browser walk-through | `python nxtbi/scripts/browser_check.py` | 15 / 15 |
| RTL functional, Arabic and English | `python nxtbi/scripts/rtl_e2e.py` | 21 passed, 2 failed (390px dashboard header overflow in both languages, upstream) |
| RTL visual audit, 53 screens | `python nxtbi/scripts/rtl_audit.py [--locales ar] [--themes dark] [--viewports mobile] [--compare]` | Last full run on the RTL branch image: 106 / 106 clean in light, 53 / 53 per language in dark; baseline in `nxtbi/tests/rtl-visual/baseline` |
| V2 routes with the flag off | `GET /api/v1/dashboard_v2/1` | 404 |
| Migration head | `superset db current` in the web container | `3c9e1a7b5d2f (head)` |

## Widgets stack (`http://localhost:8089`, flag on, production CSP)

| Check | Command | Last result |
|---|---|---|
| End to end: builder, conflict dialog, filters, example app (session and guest), guest-token scoping, RLS, REST validation, Arabic builder, MCP | `python nxtbi/widgets/scripts/widgets_e2e.py` (start the example app first, see `nxtbi/widgets/README.md`) | 25 / 25, none skipped |
| Upstream Playwright `dashboard-v2` specs | `bash nxtbi/widgets/scripts/run_upstream_playwright.sh` | 20 / 20 |
| Migration upgrade, downgrade, upgrade on a disposable PostgreSQL | `IMAGE=nxtbi/superset-fork:widgets bash nxtbi/widgets/scripts/migration_cycle.sh` | pass, single head |

## Unit and static checks

| Check | How | Last result |
|---|---|---|
| TypeScript | `fe-build type` (runs `npx tsc --build`) | clean |
| oxlint on the widgets paths | in the `fe-build` container | clean |
| Jest: widgets package, core, builder, extensions, home, routes | `fe-build test <paths>` | 109 suites, 1,308 tests pass (`safety.parity.test.ts` must run where `superset/widgets/safety.py` is reachable, i.e. on the host) |
| Jest sweep of RTL-touched areas (RTL branch) | same | 11,645 passed; `MetadataBar` and `ProgressBar` fail on upstream master too |
| Backend unit suites: dashboard_v2, dashboards, widgets, security, extensions, MCP, versioning, importers, DAOs, translations | pytest inside the image, see below | 5,318 tests: 5,302 pass, 2 skipped, 1 failure (missing BigQuery driver), 13 setup errors in `extensions/test_sqlalchemy.py` (environment) |
| ruff check and format on changed backend paths | `ruff --no-cache` in the image | clean |

Backend tests in the image (the image has no test dependencies):

```bash
MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/superset:/app/superset:ro" -v "$PWD/superset-core/src/superset_core:/app/superset-core/src/superset_core:ro" -v "$PWD/tests:/app/tests:ro" -v "$PWD/pytest.ini:/app/pytest.ini:ro" -v "$PWD/pyproject.toml:/app/pyproject.toml:ro" -v "$PWD/superset-frontend/src/features/apiKeys:/app/superset-frontend/src/features/apiKeys:ro" -w /app --entrypoint bash nxtbi/superset-fork:local -c "pip install -q --target /tmp/p pytest pytest-mock pytest-xdist pytest-asyncio flask-testing polib 'python-dateutil==2.9.0.post0' && pip install -q --no-deps --target /tmp/p freezegun && PYTHONPATH=/tmp/p python -m pytest -q -p no:cacheprovider tests/unit_tests/dashboard_v2"
```

Not run: `mypy`, `pre-commit`, `tests/integration_tests`, the full upstream Jest and pytest suites.
