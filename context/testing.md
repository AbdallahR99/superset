# Tests

Host scripts need Python 3.11+ and `PYTHONIOENCODING=utf-8` on Windows.

## Upstream sync verification

November 18, 2026. The repository Dockerfile's `superset` target built with
`BUILD_TRANSLATIONS=true` at merge `19083873642fcf1a9dc7d8185690d544a5eba494`.
The image `nxtbi/superset-fork:upstream-sync-6e54f477a0` has ID
`sha256:ffd12f9d56bb0393d2dfa7f3835d7254a2ddf3ed5ef63e1b97a82719832d7c90`.

| Area | Check and result |
|---|---|
| Backend and authorization | Pytest ran against packaged application code with read-only test mounts. All 873 selected tests passed across Dashboard V2, dashboard document storage, Widgets, widget data permissions, and the MCP widget and dashboard tools. |
| Fresh startup and migrations | The isolated PostgreSQL 17 and Redis startup reached health on port 28189 after init exited 0. `superset db current` reported `3c9e1a7b5d2f (head)`. `nxtbi/widgets/scripts/migration_cycle.sh` passed all four checks, including downgrade to `b8f3a2c91d64` and re-upgrade. |
| Concurrent dashboard saves | `nxtbi/widgets/scripts/dashboard_v2_concurrency.py` overlapped three PostgreSQL sessions on the same row. One V2 save won, one returned a conflict, the classic metadata save survived, and a cyclic update left the stored document intact. |
| Keycloak and worker | All four isolated OIDC browser cases passed for role mapping, session continuity, application and SSO logout, and refusal of an unmapped user. The isolated Celery worker responded to `inspect ping`. |
| Arabic and English | The isolated `rtl_e2e.py --only 03,04,10-theme,10b` selection passed all seven Chromium cases. It covered locale switching, mirrored popups, responsive navigation, and touch dashboard entry and exit in both directions. |
| Dashboard V2 and Widgets | The isolated `widgets_e2e.py` selection passed 20 of 20 with zero skips. Coverage included save and reopen, stale revisions, session and guest embedding, CORS, tenant RLS, guest grant and dataset binding, flag-off routes, invalid documents, and MCP widget access. |
| Dashboard V2 Playwright | `nxtbi/widgets/scripts/run_upstream_playwright.sh` passed all 20 Chromium specs against the isolated synced image. |
| Compiled extension | Both browser checks passed. The builder persisted and reopened the compiled widget with real rows and a sibling filter. Session and guest hosts kept filters and row results separate across remounts while loading the same remote bundle. |
| WebSocket | `npm ci`, `npm test`, `npm run type`, and `npm run build` passed in Node 24. Vitest passed 92 tests on both the baseline and the merge. The old and new bundles matched byte for byte in both the Node test environment and the production image. |
| WebSocket dependency audit | Audits of both lockfiles reported the same five high-severity development findings and zero production findings with `npm audit --omit=dev`. |
| Docs dependencies | `yarn install --frozen-lockfile --ignore-scripts --non-interactive` succeeded and Ant Design 6.7.0 rendered a Button with React 18. This check covered dependency resolution and component rendering. |
| Workflows and Helm | The changed-path YAML and Zizmor hooks passed. `helm lint helm/superset` passed with a warning about missing local chart dependencies. Windows pre-commit failed to resolve the Helm Docs script path. The pinned `helm-docs` 1.14.2 hook passed in dry-run mode through Git Bash. |

The main demo web and MCP health checks passed on the stabilization image.
The main demo app, PostgreSQL, Redis, and shared Keycloak container identities
and start times matched the pre-sync snapshot. Logs are in the git-ignored
`nxtbi/out/upstream-sync-6e54f477a0/` directory.

The production build completed with MapLibre and bundle-size warnings.
The sync gates use focused suites. See [known limitations](known-limitations.md)
for the prior stabilization coverage and remaining product gaps.

## Main demo after rollout

On November 18, 2026, the main demo web, worker, beat, and MCP containers
switched to the verified image below. The demo uses Keycloak and runs with
`DASHBOARD_V2` off. Both the [web health endpoint](http://localhost:8088/health)
and the [MCP health endpoint](http://localhost:5008/health) returned HTTP 200.

| Check | Result |
|---|---|
| `python nxtbi/out/stabilization/main-demo-rollout/smoke-preserving.py` | 34 passed, 0 failed, 0 skipped. Covered login and logout, tenant RLS, Arabic assets, REST and MCP reads, cached data, and existing demo dashboards. |
| `python nxtbi/out/stabilization/main-demo-rollout/touch-smoke.py` | 2 passed, 0 failed, 0 skipped. Arabic and English at 390px, direct and in-app entry, filter drawer edge, and viewport restoration on Back. Repeat the touch cases with `python nxtbi/scripts/rtl_e2e.py --only 10b`. |
| Celery worker ping | One node responded `pong`. |
| Flag-off routes | `GET /api/v1/dashboard_v2/1` and `GET /dashboard/v2/new/` both returned 404. |
| Deployment and persistence | All four app services ran the release image. Config, mounts, named volumes, eight metadata fingerprints, and PostgreSQL, Redis, init, and Keycloak container instances matched the pre-rollout snapshot. Migration remained at `3c9e1a7b5d2f`. |

The main demo smoke selection omits checks that modify saved content or demo
configuration. The full checks that need disposable data ran on isolated
stacks. The local wrappers and receipts are under the git-ignored directory
`nxtbi/out/stabilization/main-demo-rollout/`.

## Final stabilization release verification

November 18, 2026. Image `nxtbi/superset-fork:stabilization-final`, ID
`sha256:e8c6d3e617875c5b9eacd15c88ef2588129301457906bbc0d787bd6604eec270`.
The preceding candidate, `ce098dfd11aa`, differs from this image in the classic
dashboard's viewport cleanup. The broader candidate results and the release
rechecks are listed below. The 14 changed Python source files matched their
packaged copies byte-for-byte.

| Check | Result |
|---|---|
| `pytest` for Dashboard V2, dashboard document storage, Widgets, widget security, and MCP widget/dashboard writers, using packaged source | Baseline 868 passed. Release image 891 passed. |
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
| `python -u nxtbi/widgets/scripts/widgets_e2e.py --api-only --only f2-,f3-,f8-,f9-,g4-` with `NXTBI_WIDGETS_ENV_FILE` pointing to the isolated release settings | 5 passed, 0 failed, 0 skipped on the release image at port 18089. Covered dashboard and dataset grant scope, widget dataset binding, guest role permissions, and REST rejection of invalid documents. |
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

## Historical feature-merge baseline

Before stabilization, the November 17 main demo at port 8088 used Keycloak with
`DASHBOARD_V2` off.

| Check | Command | Baseline result |
|---|---|---|
| API and stack smoke | `python nxtbi/scripts/smoke_test.py` | 48 / 48 |
| Browser walk-through | `python nxtbi/scripts/browser_check.py` | 15 / 15 |
| RTL functional, Arabic and English | `python nxtbi/scripts/rtl_e2e.py` | 21 passed, 2 failed (390px dashboard header overflow in both languages, upstream) |
| RTL visual audit, 53 screens | `python nxtbi/scripts/rtl_audit.py [--locales ar] [--themes dark] [--viewports mobile] [--compare]` | Last full run on the RTL branch image: 106 / 106 clean in light, 53 / 53 per language in dark; baseline in `nxtbi/tests/rtl-visual/baseline` |
| V2 routes with the flag off | `GET /api/v1/dashboard_v2/1` | 404 |
| Migration head | `superset db current` in the web container | `3c9e1a7b5d2f (head)` |

### Widgets stack (port 8089, flag on, production CSP)

| Check | Command | Baseline result |
|---|---|---|
| End to end: builder, conflict dialog, filters, example app (session and guest), guest-token scoping, RLS, REST validation, Arabic builder, MCP | `python nxtbi/widgets/scripts/widgets_e2e.py` (start the example app first, see `nxtbi/widgets/README.md`) | 25 / 25, none skipped |
| Upstream Playwright `dashboard-v2` specs | `bash nxtbi/widgets/scripts/run_upstream_playwright.sh` | 20 / 20 |
| Migration upgrade, downgrade, upgrade on a disposable PostgreSQL | `IMAGE=nxtbi/superset-fork:widgets bash nxtbi/widgets/scripts/migration_cycle.sh` | pass, single head |

### Unit and static checks

| Check | How | Baseline result |
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

The feature-merge baseline did not include a repository-wide pre-commit,
integration, Jest, or pytest run. The scoped comparisons and release rechecks
above supply the stabilization evidence.
