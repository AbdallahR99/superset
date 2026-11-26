# Git state (2026-11-26)

Remotes: `origin` = `https://github.com/AbdallahR99/superset.git` (the fork), `upstream` =
`https://github.com/apache/superset.git`.

## November 26 upstream sync

Apache Superset master was fetched at `2c58859901008793230c541e7d309642e516c577`.
The previous common upstream base was `6e54f477a0`. The 278 upstream commits
were merged into the Copilot polish tip `bd321bce92` on
`codex/upstream-sync-2c58859901`. The polish tip includes all 12 local
Copilot, Widget SDK, and Dashboard V2 commits carried beyond the existing
fork master, `e381689b86`.

| Commit | Purpose |
|---|---|
| `8bcbd67337` | Two-parent upstream merge and compatibility work |
| `16aede256c` | Copilot test typing, optional standalone peer type-check scope, and Dashboard V2 type cleanup |
| `abfa2645d8` | Dashboard history regression test waits for the expanded details |
| `4d0edafc64` | Direct Authlib dependency restores MCP startup and Keycloak support in the packaged runtime |
| `1cf9ceeee6` | Scoped Dashboard V2 test fixture for direct command calls |

Alembic revision `9fefac24f1cc` joins the earlier installed NxtBI widget
revision `3c9e1a7b5d2f` with upstream head `7b9d2f8a6c31`. Both parent
histories are preserved. The Copilot Docker overlay defaults to the synced
base tag `nxtbi/superset-fork:upstream-sync-2c58859901` and keeps the existing
override. The NxtBI Keycloak configuration preserves the branded login
screen while stock Superset retains its single-provider redirect.

Inspect the published tip with `git ls-remote origin refs/heads/master`.
The prior deployment verification below is historical.

## master

| Commit | What |
|---|---|
| `f3f3d10d5cc3b934c9966d9ae9da7a09aee4d261` | Original Apache Superset base (post 7.0.0rc2) |
| `1febd3c5fa` | Merge of `feature/nxtbi-arabic-rtl` (12 commits; includes the NxtBI demo in `nxtbi/`) |
| `a91f8e8181` | Merge of `feature/nxtbi-widgets` (36 commits; includes the `--no-ff` merge of upstream PR 44471 at `71be990689`) |
| `7bbaf70890` | Context folder and refreshed demo screenshots |
| `82b2dcd1c44aa87d0f44f298e863d6a3845bd951` | Merge of `fix/nxtbi-final-stabilization`. Pushed to `origin/master` and verified on GitHub on November 18, 2026. |
| `a49ed5afa3543a5cd0b6b9ad1555ac0499ba620b` | Fork tip before the upstream sync, including the stabilization closeout |
| `19083873642fcf1a9dc7d8185690d544a5eba494` | Sync merge of Apache Superset master at `6e54f477a0fe9531d143007dd46d4db98a0911e0` |

The feature merges were conflict-free. The widgets merge produced the same tree
as `feature/nxtbi-widgets` and supplied the application baseline. Stabilization
started at `7bbaf70890` after confirming that local and remote `master` matched.
The stabilization merge used `--no-ff`. Its packaged application code matches
the [verified release on the main demo](configuration-and-docker.md#images).
Run `git ls-remote origin refs/heads/master` for the published tip.

## Branches

| Branch | Tip | State |
|---|---|---|
| `feature/nxtbi-arabic-rtl` | `1ed4423fca` | Merged into master |
| `feature/nxtbi-widgets` | `4b6702f0ce` | Merged into master |
| `nxtbi-demo` | `976e975e99` | Original demo branch; its work is contained in the RTL branch |
| `fix/nxtbi-final-stabilization` | `06e1042058893328f9e6a46cddef2547fe503744` | Merged into `master` |

The stabilization branch contains the widget contract fix (`190eed4720`),
extension view registration fix (`be98f86a2f`), concurrent metadata fix
(`fbaff1425d`), phone dashboard fix (`c1beece899`), and touch viewport fix
(`3fd6fef423`). The validation harness changes are in `41e235b5c2`, with an RTL
test-only type annotation in `06e1042058` after the build. The prior validation
documentation is in `92435d62eb`.

Local worktrees used during the work (safe to remove once no longer needed):
`../nxtbi-superset-widgets` (on `feature/nxtbi-widgets`) and `../nxtbi-superset-pr44471` (read-only
checkout of the PR head).

## November 18 upstream sync

`origin/master` and local `master` initially matched at `a49ed5afa3`. From the
common base `f3f3d10d5c`, there were 61 fork-only commits and five upstream-only
commits. The merge preview found zero overlapping paths. The two-parent merge on
`codex/upstream-master-sync-6e54f477a0` completed without conflicts.

The eight changed files cover GitHub Actions, Ant Design 6.7.0 for the docs
site, and Vitest 5.1.0 for WebSocket development. The application, product
frontend lockfile, NxtBI configuration and tests, and migrations match the
pre-sync fork exactly. The existing single migration head remains
`3c9e1a7b5d2f`. The verification image was built with the repository Dockerfile
so it includes the WebSocket bundle from the updated lockfile.
