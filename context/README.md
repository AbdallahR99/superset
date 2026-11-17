# Project context (start here)

This repository is the NxtBI fork of Apache Superset (`AbdallahR99/superset`).
The upstream sync at `1908387364` incorporated Apache Superset `6e54f477a0`
and preserved three pieces of NxtBI work.

1. **NxtBI demo stack** in `nxtbi/`: Docker Compose, Keycloak single sign-on, tenant isolation, demo
   dashboards, theme, scripts. No upstream file is changed by it.
2. **Arabic and right-to-left support** across the application (changes upstream frontend and backend).
3. **Dashboard V2 and embeddable widgets**, adopted from upstream PR apache/superset#44471 and repaired.
   Behind the feature flag `DASHBOARD_V2`, off by default.

See the [upstream sync verification](testing.md#upstream-sync-verification)
for the current development baseline.

Stabilization merged at `82b2dcd1c4` and is live on the main demo with Dashboard
V2 disabled. After rollout, all 34 smoke checks and both Arabic and English
touch checks passed. See the [running image and rollback](configuration-and-docker.md#images),
[verification results](testing.md), and [Git state](git-state.md).

Read in this order:

| File | What it answers |
|---|---|
| [architecture.md](architecture.md) | How the three pieces are built and where the code lives |
| [features.md](features.md) | What works today |
| [decisions-and-fixes.md](decisions-and-fixes.md) | Why things are the way they are; defects already fixed |
| [configuration-and-docker.md](configuration-and-docker.md) | Stacks, ports, images, config keys, build loop |
| [testing.md](testing.md) | Every check, how to run it, last results |
| [known-limitations.md](known-limitations.md) | What is not done or not verified |
| [git-state.md](git-state.md) | Branches, merges, what is pushed |

Longer documents, all under `nxtbi/docs/`: `I18N-RTL.md`, `WIDGETS.md`, `TEST-RESULTS.md`,
`CAPABILITY-MATRIX.md`, `rtl/` (RTL research), `widgets/` (PR review, API contract, security model).

## Rules for working here

- Never restart, recreate or reconfigure the shared Keycloak container `ld-shared-keycloak-1`, the
  `nxtbi-web` client or the NxtDash realm file. `nxtbi/scripts/keycloak_setup.py apply` only adds.
- Never run `docker compose down -v` on project `nxtbi-superset` (it holds the demo data).
- Secrets live in git-ignored `.env` files (`nxtbi/.env`, `nxtbi/widgets/.env`); never print or commit them.
- Frontend formatting is `oxfmt`, linting `oxlint`; Python is `ruff`. Do not run prettier.
- On Windows, build and test the frontend in the Linux container (`nxtbi/dev/fe-build.sh`), run backend
  tests in the image, and prefix docker commands in Git Bash with `MSYS_NO_PATHCONV=1` when they take
  container paths.
- The upstream guide for agents is the root `CLAUDE.md` / `AGENTS.md`.
