# Known limitations

None of these block running the application. Full lists: `nxtbi/docs/I18N-RTL.md` section 4 and
`nxtbi/docs/WIDGETS.md` section 4.

## Not run or not verified

- `mypy` and `pre-commit` were not run on either piece of work (ruff, oxlint, oxfmt and tsc were).
  The upstream guide asks for pre-commit before pushing; GitHub CI on the fork will show what it finds.
- Truly concurrent V2 saves on PostgreSQL, and anything on MySQL, were not run. Concurrency is covered
  by unit tests on SQLite and sequential requests on PostgreSQL.
- Extension widgets were tested against a simulated Module Federation container, not a real bundle.
- Keycloak login on the widgets stack (port 8089) is verified at configuration level only; it needs a
  redirect URI added to the client, which was deliberately not changed.
- The Arabic catalogue was reviewed by language models with placeholder checks, not by a native proofreader.
- Less common chart plugins (deck.gl, Gantt, cartodiagram) have direction unit tests but no browser check.
- Backend unit run: 1 failure for a missing BigQuery driver and 13 setup errors in
  `tests/unit_tests/extensions/test_sqlalchemy.py` (untouched upstream file; the SQLite file cannot be
  created in the read-only test container).

## Product gaps

| Area | Gap |
|---|---|
| Phone layout | Dashboard and Explore headers overflow at 390px in both languages (upstream) |
| Semantic layer dialogs | Use the JSON form library with ajv; expected to fail under the production CSP (upstream, not reproduced) |
| Static error pages | Direction follows the session, strings are English |
| Chart fonts | Theme font has no Arabic glyphs; canvas text falls back to a system font |
| Builder | Palette block names untranslated in Arabic; container parent/child pairing not enforced by the server; one observed first-click cross-filter miss after clearing a filter |
| Extension widgets | A call to the core that names no node, from a timer or event handler, cannot be attributed when two providers show the widget (it throws); in the builder such a call runs unfiltered |
| Stored definitions | Widgets or documents saved before the stricter rules load but must be cleaned before the next save |
| Guest tokens | Widget tokens minted before dataset binding must be re-minted; the minter must be admin or unrestricted by RLS on what it grants |
| Rate limit | Default 50 requests per second per address is too low for a page with many embedded widgets |
| Trash restore, welcome template | Write dashboard metadata without the compare-and-swap; neither can race an open editor |
| "Save as" | Also writes metadata to the source dashboard (upstream) |
