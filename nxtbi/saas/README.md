# NxtBI SaaS pilot

The pilot demonstrates two viewer workspaces served by independent Superset
deployments. A shared Keycloak sign-in grants access to a bilingual workspace
chooser. Each Superset deployment checks its own membership at native login.
Both deployments use one image and one Compose template, with separate metadata
and warehouse databases, database roles, Redis services, sessions, and private
networks. PostgreSQL RLS hides a restricted synthetic row in both warehouses.

## Run locally

Use Docker Compose, Python, and Python Playwright with Chromium or installed
Chrome. Run from the repository root with a built NxtBI Superset image:

```powershell
python -X utf8 -u -m nxtbi.saas.pilot --superset-image nxtbi/superset-fork:copilot-localization-verified --keep
```

The command provisions only synthetic data and generates separate localhost
origins. It prints the portal URL and a local file containing synthetic viewer
passwords after database and Chromium checks pass. The `alpha-viewer` and
`beta-viewer` accounts each have one workspace. The `shared-viewer` account has
both. Data, screenshots, and diagnostics are under the git-ignored
`nxtbi/out/saas-pilot/<run-id>/` directory.

Omit `--keep` for an automatically removed test stack. Stop a retained stack
and delete its synthetic volumes with:

```powershell
python -m nxtbi.saas.pilot --stop <run-id>
```

The disposable realm uses Keycloak development mode and binds only to loopback.
The portal and Superset pilot publish loopback ports only. The tenant cluster
and main demo use separate project, volume, and credential sets. Internal OIDC
token and certificate calls use the container network. Authlib verifies the
fixed browser issuer in the returned ID token. [Keycloak hostname configuration](https://www.keycloak.org/server/hostname)

## Contracts and scope

- `portal.compose.yml` serves the chooser and disposable identity realm.
  The portal lists active tenant memberships from an operator-managed catalog and
  rechecks them before opening the configured analytics origin. Membership claims
  are verified at sign-in. Sessions have a five-minute absolute lease.
- `tenant.compose.yml` runs the same image for each tenant. The migration identity
  prepares the metadata, the app runtime identity serves the managed schema, and
  a separate reader runs analytics queries under PostgreSQL RLS. Tenant display
  names and links back to the chooser use native Superset configuration.
- The browser check covers Classic dashboards and the viewer-only pilot role.
  Customer administration, SQL Lab, V2 edits, guest embedding, reports, and
  Copilot and upload scope have their own release gates in the SaaS plan.
  IdP membership changes take effect at the next sign-in within the session
  lease. Production provisioning and offboarding require a revocation workflow.

The local verification used one Superset image and Alembic head `9fefac24f1cc`
for both tenants. The warehouse reader saw one row per tenant. Chromium showed
101 and 202 in the native dashboards, rejected peer logins for single-tenant
users, and let the dual member switch tenants with one Keycloak sign-in. The
Arabic workspace chooser rendered right to left.

## Extension opportunities

1. Add a workspace home `.supx` with a contributed page and menu entry for
   onboarding links and an approved dashboard catalog. Use the public navigation
   API so it works under a custom application root. Keep tenant membership on
   a protected, same-origin endpoint. [Extension contribution types](https://superset.apache.org/developer-docs/extensions/contribution-types/)
2. Store lightweight workspace shortcuts and personal preferences with the
   extension storage API. Key shared resources by workspace UUID and enforce
   workspace permissions in the extension backend. [Extension storage](https://superset.apache.org/developer-docs/extensions/storage/)
3. Reuse the native Dashboard embed SDK and fork Widget SDK after adding a
   tenant-scoped token issuer. Verify workspace scope across issuing, refreshing,
   data access, and switching before enabling external embeds.

See the [SaaS rollout plan](../../context/saas-tenancy-plan.md) and
[upstream maintenance plan](../../context/upstream-maintenance-plan.md).
