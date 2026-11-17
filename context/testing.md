# Tests

Host scripts need Python 3.11+ and `PYTHONIOENCODING=utf-8` on Windows. The
merge baseline below was recorded on November 17, 2026, after both feature merges.

## Final stabilization candidate

November 18, 2026. Image `nxtbi/superset-fork:stabilization-final`, ID
`sha256:e8c6d3e617875c5b9eacd15c88ef2588129301457906bbc0d787bd6604eec270`.
The preceding candidate, `ce098dfd11aa`, differs from this image in the classic
dashboard's viewport cleanup. The broader candidate results and the release
rechecks are listed below. The 14 changed Python source files matched their
packaged copies byte-for-byte.

| Check | Result |
|---|---|
| `pytest` for Dashboard V2, dashboard document storage, Widgets, widget security, and MCP widget/dashboard writers, using packaged source | Baseline 868 passed. Candidate 891 passed. |
| `pytest tests/integration_tests/embedded/test_view.py` with fresh SQLite test metadata and isolated Redis | 8 passed |
| `npx tsc --build` in the production Node build stage | Passed |
| `npm run test -- --ci --maxWorkers=4 packages/superset-widgets/src src/core/dashboard src/pages/DashboardBuilderV2 src/dashboard/components/DashboardBuilder src/dashboard/components/Header src/extensions` | 73 suites, 910 tests passed |
| Focused Jest for final RTL and extension source | 6 suites, 170 tests passed |
| Release image startup with fresh PostgreSQL and Redis | Init exited 0, migration head `3c9e1a7b5d2f`, and `http://localhost:28089/health` returned 200 |
| `IMAGE=nxtbi/superset-fork:stabilization-final bash nxtbi/widgets/scripts/migration_cycle.sh` | PostgreSQL upgraded to single head `3c9e1a7b5d2f`, downgraded to `b8f3a2c91d64`, and upgraded again |
| `python nxtbi/widgets/scripts/dashboard_v2_concurrency.py` with the isolated URL, env file and PostgreSQL container | Three distinct database sessions overlapped. The two V2 saves returned 200 and 409 at revision 2, the classic metadata write survived, and a cyclic save returned 422 without a write. |
| Concurrent overwrite import and classic save; web-only restart | Both writes survived on the candidate. The stored Arabic edit, classic metadata and revision 2 survived restart. Stale saves still returned 409 with ETag 2. |
| `python nxtbi/widgets/scripts/widgets_e2e.py --only a,b,c,d,e1-,e2-,e3-,f2-,f3-,f6-,f7-,f8-,f9-,g,h` | 22 passed on both the baseline and candidate |
| `python nxtbi/widgets/scripts/widgets_e2e.py --only a,b,f6-,f7-,h` | 7 release-image checks passed, covering builder save/reopen, concurrent-edit UI, RLS, feature flags, Arabic rendering, and MCP |
| `bash nxtbi/widgets/scripts/run_upstream_playwright.sh` | 20 passed on both the baseline and candidate |
| `python nxtbi/scripts/browser_check.py` on the isolated Keycloak demo | 15 passed on both the baseline and candidate, including login, reauthentication after logout and tenant-scoped dashboard access |
| `python nxtbi/out/stabilization/smoke-demo-selected.py` | 40 checks passed on the candidate, including authenticated REST/MCP, tenant RLS, Celery, and email report delivery |
| `python nxtbi/scripts/rtl_e2e.py --only 10b` and pointer checks on the release image | Arabic and English touch: 2 passed. Pointer: 4 width/locale combinations passed. Touch checked direct and SPA entry, drawer placement, and viewport restoration on Back. |
| Compiled Webpack Module Federation extension in Chromium | Candidate and release reopened saved extension widgets and applied a sibling filter. Separate session and guest-token providers shared the fetched bundle while keeping data, filter updates and lifecycle state separate. |
| `python nxtbi/out/stabilization/oidc-browser.py --base http://localhost:18088` | 4 passed on the release image. Verified Admin and two organization roles, reload, app and SSO logout, and rejection of an unmapped user. |
| Optional Widgets Keycloak mode | Admin, organization administrator and editor mapped to the documented built-in roles. Sessions survived reload, logout ended SSO, and an unmapped user was refused. |
| `ruff check` and `ruff format --check` on changed server code, unit tests, and concurrency harness | 24 paths passed |
| `pre-commit run --files …`, then baseline comparison | The same 23 mypy diagnostics reproduced on the baseline. The custom frontend rules passed when run directly with Git Bash and Node on its PATH. |

The immutable baseline and candidate each passed all 18 SQLite extension
cases from a writable temporary working directory. The same BigQuery test
failed on both images without its optional driver. An isolated test-only
overlay with the repository-pinned BigQuery driver passed all 19 cases.
The wider baseline-only pytest sweep was interrupted after the focused
comparison completed. Its partial result was 11,289 passed, 31 failed and
15 skipped. It included unrelated upstream tests that require fixture assets or
optional packages. The baseline and candidate counts in the table use the
same focused test paths.

Local logs, isolated Compose overrides and temporary browser fixtures are under
`nxtbi/out/stabilization/`. Keep its generated credential files local.

The wider RTL functional run on the preceding candidate recorded 21 passes,
one navigation timeout during rollout, and one English image-export skip.
The English responsive check passed on retry, and Arabic JPG export passed.

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
