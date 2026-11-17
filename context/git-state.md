# Git state (2026-11-18)

Remotes: `origin` = `https://github.com/AbdallahR99/superset.git` (the fork), `upstream` =
`https://github.com/apache/superset.git`.

## master

| Commit | What |
|---|---|
| `f3f3d10d5c` | Upstream master the work is based on (post 7.0.0rc2) |
| `1febd3c5fa` | Merge of `feature/nxtbi-arabic-rtl` (12 commits; includes the NxtBI demo in `nxtbi/`) |
| `a91f8e8181` | Merge of `feature/nxtbi-widgets` (36 commits; includes the `--no-ff` merge of upstream PR 44471 at `71be990689`) |
| `7bbaf70890` | Context folder and refreshed demo screenshots |
| `82b2dcd1c44aa87d0f44f298e863d6a3845bd951` | Merge of `fix/nxtbi-final-stabilization`. Pushed to `origin/master` and verified on GitHub on November 18, 2026. |

The feature merges were conflict-free. The widgets merge produced the same tree
as `feature/nxtbi-widgets` and supplied the application baseline. Stabilization
started at `7bbaf70890` after confirming that local and remote `master` matched.
The stabilization merge used `--no-ff`. Its packaged application code matches
the [verified release on the main demo](configuration-and-docker.md#images).
Run `git ls-remote origin refs/heads/master` for the published tip, which also
includes the documentation closeout after the application merge.

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

## Updating from upstream

`git fetch upstream && git merge upstream/master`. Expect conflicts only where the RTL and widgets work
touch upstream files: shared UI wrappers in `packages/superset-ui-core/src/components`, the theme
provider, `superset/security/manager.py`, `superset/config.py`, `superset-frontend/src/views/routes.tsx`,
`superset-frontend/package.json` and the lockfile, and the translation catalogues. A new upstream
migration needs `3c9e1a7b5d2f_add_saved_widgets` re-parented so there is a single head. If upstream
lands its own Dashboard V2, prefer theirs and re-apply the fixes listed in `decisions-and-fixes.md`.
