# Upstream-compatible NxtBI monorepo plan

Keep the existing Git repository and Apache directory layout. Build new NxtBI
features as installable extensions and private services under `nxtbi/`. Maintain
small, owned changes to the Superset host for behavior that needs native hooks.
Merge Apache history into the fork regularly and qualify the combined build with
the same workflows used to release it.

The monorepo keeps feature, adapter, and deployment changes reviewable together.
Separate extension bundles give teams independent build and dependency boundaries
without subdividing the Git history. Keep the host layout to preserve ordinary
three-way merges with Apache.

## What the repository shows

On November 26, 2026, fork `master` and `origin/master` both pointed to
`eba884bb3524bc61dfddfef072ee05e1b22a4f94`. Relative to the last integrated Apache
commit, `2c58859901008793230c541e7d309642e516c577`, the fork had 90 additional
commits, 750 added files, and 339 modified upstream files. The previous merge
`8bcbd67337` had 83 overlapping paths and 18 content conflicts when replayed.
Conflicts included the npm lockfile, shared view and menu code, locale catalogs,
chart RTL rendering, and dashboard and MCP changes. Most additions under
`nxtbi/` were isolated from this overlap.

The live Apache tip was `d2598e2d551b8156b457838eed70da2d1d83f276`, one commit
beyond the integrated base. `git merge-tree --write-tree --name-only --messages`
returned 0 against the fork. That establishes a clean Git merge for those SHAs.
The candidate still needs a build and runtime verification. No branch was updated
by the preview. [Git merge preview documentation](https://git-scm.com/docs/git-merge-tree)

## Where new work goes

| Work | Default location | Integration boundary |
|---|---|---|
| New screens, tools, settings, and Copilot interactions | Extension under `nxtbi/extensions/<feature>/`, or the existing Copilot extension | Register namespaced pages, menu items, commands, and supported views through `@apache-superset/core`. Use host navigation and application-root handling. Keep the page and its data endpoint protected. |
| Shared components and domain logic | NxtBI-owned packages under `nxtbi/` when they have multiple consumers | Pass theme, locale, navigation, and data access through host adapters. Keep domain packages usable from the standalone React host. Declare and test compatible Superset host versions at the adapter boundary. |
| New same-origin APIs, MCP tools, and small extension state | Extension backend under `nxtbi/` using `apache-superset-core` | Register protected endpoints and explicit MCP contributions. Use scoped extension storage for suitable state. Superset owns the effective user, native object permissions, RLS, and writes to dashboards, charts, and datasets. |
| LLM calls, external integrations, and long-running work | A private NxtBI service, following `nxtbi/copilot/agent` | Exchange typed requests with a narrow host adapter. Pass scoped identity and authorization, retain explicit approvals for writes, and test retries and version compatibility. |
| Native RTL, Classic dashboard behavior, Dashboard V2, and embedded Widgets | Existing native modules and narrow host adapters | Maintain these as owned host changes. Treat V2 and Widget SDK APIs as fork capabilities. Keep their imports behind optional, flag-aware adapters. Propose general-purpose missing extension points upstream. |

Use `.supx` artifacts for packaged features, with `LOCAL_EXTENSIONS` for local
iteration and `EXTENSIONS_PATH` for deployment. A Python extension runs inside
Superset's trust boundary. Use the service boundary for work that needs process
isolation. An embedded UI or a menu permission does not authorize data access.
[Extension architecture](https://superset.apache.org/developer-docs/extensions/architecture/)
[Contribution types](https://superset.apache.org/developer-docs/extensions/contribution-types/)
[Deployment](https://superset.apache.org/developer-docs/extensions/deployment/)
[MCP integration](https://superset.apache.org/developer-docs/extensions/mcp/)
[Extension storage](https://superset.apache.org/developer-docs/extensions/storage/)

Keep new NxtBI dependencies out of the Apache frontend lockfile where feasible.
Start with the existing package tooling and put a NxtBI npm workspace and its own
lockfile under `nxtbi/` once multiple new packages need shared tasks. Reuse the
existing Copilot SDK in place while the first extension proves the boundary.
Consider Turborepo for the NxtBI workspace after measuring repeated build costs.
Keep the Apache build and package-manager configuration aligned with upstream.
[Turborepo repository structure](https://turborepo.dev/docs/crafting-your-repository/structuring-a-repository)

For an existing native slot without a runtime extension API, use the supported
build-time override hook only when it covers the behavior. The legacy registry
is local to the host bundle. A federated extension needs a public slot or a thin
adapter for anything beyond it. Avoid dependencies on private `src/` imports,
Redux stores, or DOM scraping from product packages. When editing an existing
Apache path, record the owner, the missing extension point, and the regression
test in the PR. Keep general-purpose host fixes in separate commits so they can be
upstreamed and retired when equivalent behavior lands.
[Native override documentation](../docs/developer_docs/extensions/extension-points/version-history.md)

## Upstream sync and release workflow

1. Check the Apache tip on a schedule and on demand. Open one integration branch
   per target SHA, usually weekly while Apache is active. Shorten the interval for
   upstream fixes we need. Keep `upstream/master` as the Apache tracking ref and
   `origin/master` as the verified NxtBI integration branch.
2. Pin both heads and run `git merge-tree --write-tree --name-only --messages`.
   Include the two SHAs, conflicts, and affected feature areas in the result.
   Keep the scheduled preview advisory. Give conflicts an owner and rerun if
   either head moves.
3. Merge Apache into `sync/apache-<sha>` in its own worktree. Resolve and review
   conflicts by area. Reconcile package manifests before regenerating a conflicted
   lockfile with the pinned toolchain. Use rerere as a reviewed suggestion. Preserve
   the upstream parent when landing the sync PR so the next merge starts from the
   right ancestor. Feature teams can work in separate worktrees. One integration
   owner sequences shared lockfile, migration, startup, and authorization changes.
4. Test and package the actual combined commit. Use immutable references for the
   host image, `.supx` bundles, and sidecars. Record fork and Apache SHAs and artifact
   digests as build output. If the tested tree changes, rerun affected checks before
   promoting artifacts. Install the required bundles on web, MCP, or workers that
   load them and probe module registration and a representative protected operation.
5. Upgrade a disposable PostgreSQL database from the previous release and test a
   fresh install. Check the expected Alembic head and keep published revisions
   immutable. Use extension-owned, versioned storage for compatible product state
   and separate migrations for independent services. Reserve Superset migrations
   for native data changes. Separate `superset db upgrade` and `superset init` from
   demo seeding. Keep the tested prior artifact set and check compatibility with
   the upgraded schema before using it as rollback.

Example sync preparation in PowerShell, from the repository root:

```powershell
git fetch --no-tags upstream refs/heads/master:refs/remotes/upstream/master
if ($LASTEXITCODE -ne 0) { throw 'Apache fetch failed' }
git fetch --no-tags origin refs/heads/master:refs/remotes/origin/master
if ($LASTEXITCODE -ne 0) { throw 'Fork fetch failed' }
$forkBase = git rev-parse origin/master
$apacheHead = git rev-parse upstream/master
git merge-tree --write-tree --name-only --messages $forkBase $apacheHead
# Exit 0 means a clean text merge. Exit 1 lists conflicts to review.
if ($LASTEXITCODE -notin 0, 1) { throw 'Merge preview failed' }
$syncBranch = 'sync/apache-' + $apacheHead.Substring(0, 10)
$syncPath = Join-Path (Split-Path -Parent (Get-Location).Path) ($syncBranch.Replace('/', '-'))
git worktree add -b $syncBranch $syncPath $forkBase
if ($LASTEXITCODE -ne 0) { throw 'Could not create the sync worktree' }
git -C $syncPath -c rerere.enabled=true -c rerere.autoupdate=false merge --no-ff --no-commit $apacheHead
```

[Git rerere documentation](https://git-scm.com/docs/git-rerere) ·
[GitHub scheduled and manual events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## Verification and rollout order

| Gate | What it proves |
|---|---|
| Feature PR | The touched NxtBI packages build and test against the supported host. The extension bundle installs, registers its contributions, handles app-root routing and feature flags, and enforces endpoint permissions. |
| Native host change or upstream sync | The combined frontend and backend build. Clean and prior-release PostgreSQL migrations pass. The compiled extension works with real services. Browser smoke covers English and Arabic, Classic with V2 off, V2 editing and publishing, Copilot drafting and saving, and session and guest Widget SDK behavior. Isolated auth tests cover Keycloak, per-user authorization, and expected denials. |
| Release promotion | The exact tested image and matching bundle/sidecar artifacts load in the target environment. Smoke checks include extension registration and a protected workflow. The prior release's schema compatibility and rollback path are recorded. |

Use one always-reporting PR status check for the selected jobs. Put path selection
inside that workflow so a required check is still reported on unrelated PRs. Enable
rulesets after the check has run successfully on the fork. Keep scheduled previews
separate from PR checks and give the preview a manual trigger.
[GitHub required checks](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)

1. **Add the preview workflow and rehearse one upstream sync.** Use the current
   clean candidate to prove the workflow end to end. Record merge owner time,
   overlapping paths, conflicts, and runtime regressions for each sync.
2. **Pilot one real feature in a `.supx`.** Choose a new page with a protected API.
   Package it from `nxtbi/` and verify direct and nested navigation, app-root prefix,
   profile permissions, English/Arabic direction, and flag-off behavior. The pilot
   succeeds when it needs no new edits to Apache source or its lockfile. Smoke-test
   it on stock Apache too if it relies only on public Apache APIs.
3. **Harden the existing boundaries before expanding Copilot or Widgets.** The
   Classic page adapter currently calls `dashboard.getDashboardId()` while the
   host omits that namespace with V2 disabled. Reproduce this in the flag-off
   browser test and guard the optional capability. Use a supported route or REST
   lookup for Classic dashboard context. Move existing gateway behavior only in
   parity-tested slices that preserve session/CSRF, authorization, and approvals.
4. **Scale feature delivery through the proven split.** Assign each workstream its
   feature package and tests. Let the host owner review changes to native paths and
   use measured overlap and sync time to prioritize extraction or upstream PRs.

This plan deliberately starts with an extension pilot and a sync rehearsal. Both
are needed before deciding whether larger changes warrant extra tooling or moving
the existing implementation.
