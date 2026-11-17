# Arabic and right-to-left (RTL) support in the NxtBI Superset fork

Branch `feature/nxtbi-arabic-rtl` (base: Superset master `f3f3d10d5c`). This replaces the earlier
"translated text only, RTL gaps documented" status: the application now runs right-to-left in Arabic.
Research and the surface audit that drove the work are in [rtl/](rtl/).

## 1. How direction works

Direction is a property of the locale and is fixed for a page load (changing language is a full reload).

| Layer | What happens | Where |
|---|---|---|
| Server | The locale's direction comes from Babel CLDR data; `<html lang dir>` is rendered by the server and `common.direction` is in the bootstrap payload. `RTL_LAYOUT_ENABLED = False` keeps every locale left-to-right. | `superset/translations/utils.py`, `superset/views/base.py`, `superset/embedded/view.py`, `superset/templates/superset/spa.html`, `superset/config.py` |
| Theme provider | `SupersetThemeProvider` resolves direction (prop, else parent, else document) and provides one Emotion cache per direction. The RTL cache runs `stylis-plugin-rtl`, so physical CSS in `css` / `styled` is mirrored automatically. Ant Design gets `ConfigProvider direction`. | `packages/superset-core/src/theme/Theme.tsx`, `direction.ts` |
| Isolation | `LtrIsolate` / `DirectionProvider` switch a subtree back to left-to-right with the `dir` attribute and a nested provider (never CSS `direction`, which the mirroring step would flip). `noFlip` stops one rule from mirroring. | `packages/superset-core/src/theme/LtrIsolate.tsx` |
| Popups | The shared Tooltip, Popover, Dropdown, Popconfirm, DatePicker and Drawer wrappers mirror an explicit placement. Callers pass the left-to-right value. | `packages/superset-ui-core/src/components/*` |
| Charts | `ChartMetadata.direction`: plots stay left-to-right (axis semantics preserved); tables, pivot tables, Big Number, handlebars and the time-series table inherit the interface direction with numbers isolated left-to-right. Decided in one place, `SuperChartCore`. | `packages/superset-ui-core/src/chart` |
| Code | SQL, JSON, stack traces, identifiers, format strings and URL slugs stay left-to-right. User-authored text (titles, descriptions, markdown) takes its direction from its own content. | editors, `CodeSyntaxHighlighter`, inputs |
| Ant Design strings | Ant Design's own locale pack and the dayjs locale load for `ar`, `fa`, `he`, `ur`. | `src/hooks/useLocale.ts`, `src/theme/AntdLocaleProvider.tsx` |

Left-to-right output is unchanged by design: RTL-only rules are emitted only in the RTL cache, `dir`
attributes on chart containers are added only on RTL pages. The exceptions are deliberate and
direction-neutral (`<bdi>` in chart tooltips, `dir="auto"` on user-authored titles, `dir="ltr"` on code).

## 2. Arabic catalogue

`superset/translations/ar/LC_MESSAGES/messages.po`, 5,951 entries.

| | Before | After |
|---|---|---|
| Translated, not fuzzy | 3,223 | 5,950 |
| Fuzzy (machine or fuzzy-matched) | 2,718 | 1 |
| Untranslated | 9 | 0 |

Two passes: 345 corrections from the catalogue audit, then a full review of every entry in ten chunks
(1,644 corrections applied, 1,618 fuzzy entries confirmed as correct). The review was done by language
models with placeholder, whitespace and plural-form validation in code, not by a native-speaker
proofreader; treat the catalogue as good and consistent, not as certified copy. Technical terms (SQL,
CSS, JSON, engine names, format strings, code identifiers) stay in Latin script. Details:
[rtl/04-arabic-catalogue.md](rtl/04-arabic-catalogue.md), [rtl/05-arabic-changes.md](rtl/05-arabic-changes.md).

## 3. Verification

Scripts and how to run them: [../tests/README.md](../tests/README.md). Final run on the production image
built from the branch (no dev overlay):

| Check | Result |
|---|---|
| `rtl_audit.py`, 53 screens, Arabic + English, light, desktop | 106 / 106 clean |
| Same, dark theme, Arabic | 53 / 53 clean |
| Same, dark theme, English | 53 / 53 clean |
| Same, 390px phone viewport, Arabic + English | 42 clean, 22 with warnings, 42 not applicable at that width; every warning also occurs in English |
| `rtl_e2e.py`, 12 functional checks x 2 languages | 20 passed, 2 failed, 1 skipped |
| `rtl_e2e.py --after-restart` (session, locale and a saved dashboard survive a restart) | 3 / 3 |
| `smoke_test.py` (existing demo checks) | 48 / 48 |
| `browser_check.py` (existing demo checks) | 15 / 15 |
| Jest sweep over every touched area | 11,645 passed; 2 suites fail the same way on master (`MetadataBar`, `ProgressBar`) |
| Backend unit tests (translations, document direction, error page) | 122 passed |
| TypeScript | clean except 5 errors in an upstream test file this branch does not touch |

The two E2E failures are one check in both languages: at 390px the dashboard header overflows
horizontally. It happens in English on master too (the vertical filter bar keeps 260px, leaving 130px
for the header). Upstream's answer is `MOBILE_CONSUMPTION_MODE`; it is not enabled here.

A visual baseline for every combination is committed under `nxtbi/tests/rtl-visual/baseline`
(`rtl_audit.py --compare` diffs against it).

## 4. Known limitations

| Item | Detail |
|---|---|
| Phone layout | Dashboard and Explore headers overflow at 390px in both languages (upstream). |
| Static error pages | The 404 page gets the session's `lang` and `dir`, but its three strings are English; the 500 page handlers are unchanged. |
| Untranslatable strings | A few upstream strings are not wrapped for translation (for example the Explore results row-limit options "1k rows", "Untitled Query N" tab names). |
| Chart fonts | The theme font has no Arabic glyphs; canvas text in ECharts falls back to a system Arabic font. |
| Embedded host override | Controls drawn inside a left-to-right chart island (ECharts extra controls, Gantt, deck.gl legend/tooltip) read the page direction from the document, so a host that forces a direction different from `<html dir>` gets those four pieces wrong. Resizable modals opened from inside such an island have the same caveat. |
| Legends | Translated legend buttons are wider, so ECharts legends paginate earlier in Arabic. |
| "Save as" | Saving a copy of a dashboard also writes metadata to the source dashboard (upstream, both languages). |
| Undo/redo icons | Kept un-mirrored in dashboard edit mode. |
| Not exercised | deck.gl maps, Gantt, cartodiagram and the remaining less common plugins have unit tests for direction but no browser check; alerts/reports screenshots were not compared in Arabic. |

## 5. Upstream work reused

| Upstream | Use |
|---|---|
| PR #34629 (closed RTL attempt) | Approach reviewed; its global CSS overrides were not adopted. The stylis plugin idea is kept, behind one cache per direction. |
| PR #29586, #41705 (Arabic) | Catalogue baseline and language registration. |
| PR #42323 (RTL-safe filter fix) | Pattern for direction-safe overflow handling in the filter bar. |

See [rtl/01-upstream-prs.md](rtl/01-upstream-prs.md).

## 6. Development loop

`nxtbi/docker-compose.dev.yml` adds a Linux webpack runner (about 25 seconds per rebuild) and mounts the
built assets, the changed backend files and the Arabic language pack into the web container:

```bash
docker compose -f nxtbi/docker-compose.yml -f nxtbi/docker-compose.dev.yml run --rm fe-build dev
docker compose -f nxtbi/docker-compose.yml -f nxtbi/docker-compose.dev.yml run --rm fe-build translations
docker compose -f nxtbi/docker-compose.yml -f nxtbi/docker-compose.dev.yml up -d superset
```

Other modes: `prod`, `type`, `test <jest args>`.
