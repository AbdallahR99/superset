# Known limitations

The release validation covers PostgreSQL 17, Keycloak 26.4, and Chromium.
The isolated release checks and the live main demo smoke checks found no
release-blocking regression in the stabilization scope. The main demo keeps
Dashboard V2 disabled.
See `nxtbi/docs/I18N-RTL.md` section 4 and `nxtbi/docs/WIDGETS.md` section 4
for the broader product limitations.

## Not run or not verified

- **Medium.** The aggregate pre-commit run still reports 23 baseline mypy
  diagnostics and lint on the existing Python demo harnesses. The frontend custom-rule hook
  could not find Node through Windows pre-commit and passed when run directly
  from Git Bash. Locked Linux TypeScript passed.
- **Low.** PostgreSQL is the verified concurrency target. MySQL was outside the run.
- **Low.** The RTL harness skipped English image export. Arabic JPG export passed.
- **Low.** Full upstream test sweeps remain partial. See the scoped comparisons
  in [testing.md](testing.md#final-stabilization-release-verification).
- The Arabic catalogue was reviewed by language models with placeholder checks, not by a native proofreader.
- Less common chart plugins (deck.gl, Gantt, cartodiagram) have direction unit tests but no browser check.
- **Low.** The BigQuery compilation test requires the optional dialect driver.
  SQLite extension fixtures require a writable working directory. Both cases
  passed in the candidate's isolated test environment.

## Product gaps

| Area | Gap |
|---|---|
| Phone layout (medium) | Explore metadata controls extend beyond their header at 390px in both languages. Classic dashboard phone layout passed in Arabic and English. |
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
