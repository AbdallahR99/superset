# Decisions and fixes

## Decisions

| Decision | Reason |
|---|---|
| All NxtBI demo files live in `nxtbi/` | Upstream merges stay conflict-free for the demo |
| Reuse the existing Keycloak; only add a client, a scope and demo data | It is shared with NxtDash and has no data volume |
| RTL by mirroring CSS in a per-direction Emotion cache, not global CSS overrides | The closed upstream attempt (#34629) used overrides and broke components; this keeps LTR output untouched |
| Plots stay LTR, table-like charts inherit | Axis semantics must not flip; text tables must |
| Widgets PR merged with `--no-ff` on top of the RTL branch | Keeps upstream history and lets the builder inherit RTL |
| `DASHBOARD_V2` flag, default off, 404 when off | The framework is new; the classic dashboard is untouched |
| Revision kept inside `json_metadata`, written by compare-and-swap on the stored value | No change to the dashboards table; works on every database |
| Every non-V2 writer of dashboard metadata keeps the stored document; restore and import bump the revision | Prevents silent overwrite and revision reuse |
| Guest inline definitions need a `dataset` token resource; the `datasets` claim only narrows | Review found the claim was being used as a grant |
| Server rejects unsafe ECharts / AG Grid settings; the client sanitizes again; a Jest test keeps both lists equal | Defence in depth against stored XSS |
| Dataset readers may author SQL expressions in widgets; guests never | Same entitlement as an ad-hoc metric in Explore |
| Mint-time RLS guard `GUEST_TOKEN_WIDGET_RLS_GUARD = True` | A token for an RLS-protected dataset needs a covering rule; an RLS-restricted minter cannot grant it |
| Builder forms validate with an interpreting JSON-schema validator | The `new Function` used by ajv is blocked by the production CSP; the CSP is not relaxed |
| AI and agent parts of the PR removed | Out of scope by instruction |

## Defects fixed (widgets)

- Save/load races and stale overwrites: revision, 409/428, single save in flight, lost-answer
  reconcile, idempotent create by client uuid, a replayed create never overwrites another session.
- Cyclic or malformed document trees: full server validation, iterative walkers, limits (500 nodes,
  depth 16, 1 MB), reserved node ids refused and repaired.
- Shared mutable state: context, event bus, extension host and node ids are per provider.
- Routes: V2 routes ahead of the classic dashboard route; the gate runs before CSRF.
- Disclosure: document read rule (access to every bound dataset); export and the classic GET strip the
  document; the classic create and PUT cannot store one.
- Guest tokens: a widget is bound to its dataset at mint; the minter must be able to read what it grants.
- Builder: CSP crash, canvas scroll ownership, "last saved" time zone.
- Merge fallout: migration re-parented to a single head, lockfile regenerated, guest-token
  entitlement check restored.

Details: `nxtbi/docs/WIDGETS.md` section 2 and `nxtbi/docs/widgets/03-backend-security.md` section 5.

## Things learned the hard way

- `npm run type` alone reports thousands of TS6305 errors; run `npx tsc --build` (project references).
- A production webpack rebuild changes entry hashes; the web container reads the manifest at start,
  so restart it after a rebuild.
- `docker build` in agent sessions on this machine needs a `DOCKER_CONFIG` without the wincred helper.
- In the backend test container install `freezegun` with `--no-deps` and pin
  `python-dateutil==2.9.0.post0`.
- The Arabic date format in dayjs contains direction marks; wrap times in a plain `<bdi>`, not `dir="ltr"`.
- The upstream "Save as" on a dashboard also writes metadata to the source dashboard.
- `run_upstream_playwright.sh` fails if `MSYS_NO_PATHCONV=1` is exported; unset it for that script.
