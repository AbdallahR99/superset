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

Both merges were made with `--no-ff` and had no conflicts (master was an ancestor of both branches).
After the second merge the tree was identical to `feature/nxtbi-widgets`, the tree the final image was
built and tested from. Run `git log --oneline --first-parent -5 master` for the exact tip.

On November 18, fetching the fork's `master` confirmed that both merges and the
context commit had reached GitHub. Local `master` matched `origin/master` at
`7bbaf70890`. Final stabilization started from this commit on
`fix/nxtbi-final-stabilization`.

## Branches

| Branch | Tip | State |
|---|---|---|
| `feature/nxtbi-arabic-rtl` | `1ed4423fca` | Merged into master |
| `feature/nxtbi-widgets` | `4b6702f0ce` | Merged into master |
| `nxtbi-demo` | `976e975e99` | Original demo branch; its work is contained in the RTL branch |
| `fix/nxtbi-final-stabilization` | `git rev-parse fix/nxtbi-final-stabilization` | Local stabilization branch |

The stabilization branch contains the widget contract fix (`190eed4720`),
extension view registration fix (`be98f86a2f`), concurrent metadata fix
(`fbaff1425d`), phone dashboard fix (`c1beece899`), and touch viewport fix
(`3fd6fef423`). The validation harness changes are in `41e235b5c2`.

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
