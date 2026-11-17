# 04 - Arabic catalogue audit (translation completeness and correctness)

Scope: `superset/translations/ar/LC_MESSAGES/messages.po` on the fork (HEAD `976e975e99`, 2026-11-17), wording only, not layout. All numbers below come from a read-only parser run (stdlib, scripts kept outside the repo); nothing in the repo was modified.

## 0. Headline

1. The catalogue is **far worse than its 54% "non-fuzzy" figure suggests**. Even the 3,223 *confirmed* (non-fuzzy) entries contain serious errors on the most visible strings: `Chart` = "جدول" (table), `Mine` = "منجم" (gold mine), `Dashboard` = "لوحه القياده", `Save` = "وفر" (economize), `Right` = "صحيح" (correct), `std` = "الأمراض المنقولة جنسيا" (STDs), `mean` = "خسيس" (stingy), `min` = "دقيقة" (minute), `Table` = "الطاولة" (furniture), `General` = "جنرال لواء" (army general), `Custom` = "تقليد" (tradition), `Home`/`Yes`/`No` left in English.
2. **Fuzzy entries are shipped to users on both build paths** (section 2). Served pack = 5,941 non-empty strings = 3,223 confirmed + 2,718 fuzzy. Fuzzy legacy entries are frequently wrong or opposite: `Sign in` -> "ليس في" (login page title), `Current month` -> "الشهر الماضي" (last month), `Select database` -> "حذف قاعدة البيانات" (Delete database), `Select all` -> "إلغاء تحديد الكل" (deselect all), `Passwords do not match!` -> "لوحات المعلومات غير موجودة", `Send as PDF` -> "أرسل بصيغة PNG", `You don't have permission to export data` -> "...لقراءة العلامات" (read tags), `%s row` n=0 -> "0 خطأ" (error).
3. The brief's premise is stale: the fork already contains upstream **#29586** (`4e346180e0`, 2024-08-26 human Arabic), **#41705** (`4e2160079a`, AI backfill) **and #46034** (`2649e3bbf4`, "AI-backfill 29 catalogs with Sonnet 5.5 + weekly backfill workflow"), plus #44611 (`cba2574241`, cleared 1,188 fuzzy with broken placeholders) and #45973 (`494a507b18`). 1,689 entries carry `# Machine-translated via backfill_po.py (claude-sonnet-5-5) [refs: ...]` + `#, fuzzy`; 1,029 fuzzy entries are older (pre-AI) msgmerge leftovers and are the worst quality.
4. Recommended policy: apply the JSON in section 10 (290 entries, human-corrected, strip `fuzzy` + MT comment), then **stop shipping fuzzy** (drop `--use-fuzzy` and make the frontend packer skip fuzzy), so unreviewed strings fall back to English instead of to wrong Arabic.

## 1. Measurements (script over `messages.po`, header excluded)

| Metric | Value |
|---|---|
| Total entries (msgid != "") | 5,950 (0 `msgctxt`, 0 obsolete `#~`) |
| Non-empty msgstr | 5,941 (equals the 5,941 seen in the served pack; verified, section 2) |
| Confirmed (non-fuzzy, non-empty) | 3,223 (54.2%) |
| Fuzzy | 2,718 (45.7%); all non-empty; 1,689 AI (`Machine-translated`), 1,029 legacy |
| Untranslated (empty msgstr) | 9: `10000`, `WFS`, `WMS`, `XYZ`, `sql`, `schema1,schema2`, `superset.example.com`, `your-project-1234-a1`, `Invalid temporal filter value for column %(column)s` (only the last is a real gap) |
| Do-not-translate markers (`#. do-not-translate`) | 25 (`superset/translations/do-not-translate.txt`, 59 lines incl. licence) |
| Confirmed entries whose msgstr == msgid | 24 (e.g. `Home`, `Yes`, `No`); 31 confirmed with no Arabic letters (mostly legit: `css`, `var`, `y`) |
| Placeholder mismatches (`%s %d %(n)s {n}`) | **1 real bug**: `Applied filters (%s)` (po line 3322, fuzzy) -> "المرشحات المطبقة (%d)": `%s` became `%d`, a Python/JS formatting error at runtime. A naive count gives 26, but 25 are plural forms legitimately omitting `%d` |
| HTML tag mismatches | 0 |
| Plural entries | 70, **all fuzzy**; header `nplurals=6; plural=(n==0)?0:(n==1)?1:(n==2)?2:(n%100>=3&&n%100<=10)?3:(n%100>=11&&n%100<=99)?4:5` (po lines 32-33) = CLDR Arabic, matches. 43 have all 6 forms; **27 have only `msgstr[0]`** and Jed falls back to English for n>=1 |
| Duplicated concepts | dashboard has 8 renderings (لوحة المعلومات 87, لوحة التحكم 69, لوحة معلومات 24, لوحة القيادة 10, ...); filter has 8 (التصفية 118, عامل التصفية 43, فلاتر 41, مرشح 31, ...); chart: مخطط 391, الرسم البياني 54, الرسوم البيانية 20 |

Demonstrated at runtime (po2json.js -> Jed, run read-only): n=0..100 for `%s row` gives `0 خطأ`, then `1 row`, `2 rows`, ... (English), while the fully filled `%s chart` gives correct Arabic dual/few/many forms. So partial plurals are both wrong at n=0 and English elsewhere.

## 2. How fuzzy is treated (confirmed from code)

| Path | File:line | Behaviour |
|---|---|---|
| Backend .mo in image | `Dockerfile:206-209` (stage `python-translation-compiler`): `pybabel compile --use-fuzzy -d /app/translations_mo \|\| true` when `BUILD_TRANSLATIONS=true`; `\|\| true` swallows compile errors | **Fuzzy included** |
| Backend alt path | `scripts/translations/generate_mo_files.sh` -> `flask fab babel-compile` (no fuzzy flag) | fuzzy **excluded** (dev only, not used by Docker) |
| Frontend pack | `superset-frontend/scripts/po2json.sh` (`npm run build-translation`, `package.json:46`) -> `po2json-cli.js` -> `po2json.js:poToJed()` using `gettext-parser@10.0.0` `po.parse` | No fuzzy filter anywhere: `po2json.js:82-91` copies every `entry.msgstr`; grep of `node_modules/gettext-parser/lib` for "fuzzy" = 0 hits. Only empty strings fall back to msgid (Jed). **Fuzzy included** |
| Serving | `superset/translations/utils.py:get_language_pack*` reads `ar/LC_MESSAGES/messages.json`; `.gitignore:118-120` ignores `messages.json`/`.mo` (generated) | pack content-hashed; image deletes `.po` (`Dockerfile:134`) |
| Where is it built | `nxtbi/docker-compose.yml:33` sets `BUILD_TRANSLATIONS: "true"`; upstream default is `"false"` (`Dockerfile:32`) | NxtBI image has the pack |

Reproduced: `poToJed(messages.po)` -> 5,950 keys, 5,941 non-empty; `translate('Sign in')` -> "ليس في"; `translate('Current month')` -> "الشهر الماضي". Upstream's own rationale (`scripts/translations/backfill_po.py` docstring, `.github/workflows/backfill-translations.yml:7-12`): AI output is marked fuzzy "for human review", yet the build ships it as if final.

## 3. Quality sample (about 900 entries read, 290 corrected)

Method: ranked every `t()/tn()/tct()` literal in `superset-frontend/{src,packages,plugins}` by number of source files using it (5,134 distinct, 4,901 in the catalogue), read the top ~640 (<=70 chars) plus targeted lookups for nav, buttons, list chrome, dashboard, explore, SQL Lab, alerts, errors, login, time range (about 260 more). Status key: C = confirmed, F = fuzzy.

| msgid | current msgstr | status | fix |
|---|---|---|---|
| Home | Home | missing (C) | الرئيسية |
| Dashboards / Dashboard | لوحات / لوحه القياده | wrong (C) | لوحات المعلومات / لوحة المعلومات |
| Chart | جدول | wrong (C) | مخطط |
| Save | وفر | wrong (C) | حفظ |
| Cancel / Close | إلغاء الأمر / غلق | poor (C) | إلغاء / إغلاق |
| Apply / Add / Search | طبق / جمع / ابحث | poor (C) | تطبيق / إضافة / بحث |
| Yes / No / OK | Yes / No / ok | missing (C) | نعم / لا / موافق |
| Run / Create / Clear / Back | اركض / خلق / واضح / ظهر | wrong (C) | تشغيل / إنشاء / مسح / رجوع |
| Share / Import | شارك / الاستيراد | poor (C) | مشاركة / استيراد |
| Retry | خالق | wrong (F) | إعادة المحاولة |
| Sign in | ليس في | wrong (F) | تسجيل الدخول |
| Email / First name / Last name | التفاصيل / اسم المخطط / اسم مجموعة البيانات | wrong (F) | البريد الإلكتروني / الاسم الأول / اسم العائلة |
| Users / List Users / Themes / Groups | سلسلة / رقم منقسم / زمن / مجموعة حسب | wrong (F) | المستخدمون / قائمة المستخدمين / السمات / المجموعات |
| Mine | منجم | wrong (C) | الخاصة بي |
| Filters and controls | عناصر تحكم إضافية | wrong (F) | عوامل التصفية وعناصر التحكم |
| Apply filters / Clear all | تطبيق الفلاتر / مسح الكل | ok term drift (C) | تطبيق عوامل التصفية / (unchanged) |
| Edit dashboard | تحرير لوحة التحكم | term drift (C) | تحرير لوحة المعلومات |
| Select all | إلغاء تحديد الكل | opposite meaning (F) | تحديد الكل |
| Current month / Current week | الشهر الماضي / تشغيل الاستعلام الحالي | wrong (F) | الشهر الحالي / الأسبوع الحالي |
| Time grain / Time shift | تايم جرين / تايم شيفت | untranslated transliteration (C) | الدقة الزمنية / الإزاحة الزمنية |
| Schema | مخطط (collides with chart) | ambiguous (C) | سكيما |
| Select database | حذف قاعدة البيانات | opposite (F) | اختيار قاعدة البيانات |
| Table | الطاولة | wrong (C) | جدول |
| Right / Top / Bottom | صحيح / قمة / قاع | wrong (C) | اليمين / أعلى / أسفل |
| mean / std / min | خسيس / الأمراض المنقولة جنسيا / دقيقة | wrong (C) | المتوسط / الانحراف المعياري / الحد الأدنى |
| Report | أبلغ عن | wrong (C) | تقرير |
| Send as PDF | أرسل بصيغة PNG | wrong (F) | إرسال بصيغة PDF |
| Schedule query | استعلام الجدول | wrong (C) | جدولة الاستعلام |
| Run selection | اختيار التشغيل | wrong (C) | تشغيل التحديد |
| SQL Lab | مختبر إس كيو إل | brand transliterated (C) | مختبر SQL |
| Show SQL / Show Log | سجل العرض / سجل العرض | wrong (C) | عرض SQL / عرض السجل |
| Passwords do not match! | لوحات المعلومات غير موجودة | wrong (F) | كلمتا المرور غير متطابقتين! |
| You don't have permission to export data | ليس لديك إذن لقراءة العلامات | wrong (F) | ليس لديك صلاحية تصدير البيانات |
| Table or View "%(table)s" does not exist. | لا يوجد جدول أو طريقة عرض %(table)s "». | broken quotes (C) | الجدول أو العرض "%(table)s" غير موجود. |
| Applied filters (%s) | ... (%d) | **placeholder bug** (F) | fix `%d` -> `%s` (not in JSON: msgid absent from JSON list, patch by hand) |
| Loading... / No data / Are you sure you want to delete | جارٍ التحميل... / ما من بيانات / ... | ok | (kept) |
| Refresh interval, Query history, Saved queries, Dashboard properties, Alerts & Reports, Row Level Security | ok | ok | (kept) |

Login page: **comes from the Superset catalogue** (SPA page `superset-frontend/src/pages/Login/index.tsx:167,179,209,218,221,267` uses `t()`), not FAB templates. Menu labels (`superset/initialization/__init__.py:535-557`, `_("SQL")`, `_("SQL Lab")`) and `commonMenuData.ts:27-36` are also wrapped; 'SQL' is translated as "SQL" (fine).
Flask-AppBuilder 5.3.0 (`requirements/base.txt:123`) ships **no `ar`** translations (tag v5.3.0 `flask_appbuilder/translations/`: de el es fa fr it ja_JP ko nl pl pt pt_BR ru sl tr zh zh_HK). Any string rendered only from FAB's own catalogue (permission/role names in security views, FAB error pages) stays English; Superset's catalogue copies only some of them (e.g. `List Users`, `List Roles`, `User Registrations`, all currently fuzzy/wrong).

## 4. Glossary (one term per concept; applied in the JSON)

| English | Arabic | Notes |
|---|---|---|
| Dashboard(s) | لوحة معلومات / لوحات معلومات (def. لوحة المعلومات) | majority form; retire لوحة التحكم, لوحة القيادة, لوحة البيانات |
| Chart(s) | مخطط / مخططات | retire رسم بياني / الرسوم البيانية / جدول |
| Dataset(s) | مجموعة بيانات / مجموعات بيانات (def. مجموعة البيانات) | |
| Filter(s) | عامل تصفية / عوامل التصفية; verb: تصفية | retire فلتر, فلاتر, مرشح |
| Native filter / cross-filter | عامل تصفية أصلي / تصفية متقاطعة | |
| Metric / Dimension | مقياس (مقاييس) / بُعد (أبعاد) | retire متري |
| Column / Row / Table | عمود / صف / جدول | |
| Schema | سكيما | frees مخطط for charts; alternative "المخطط (Schema)" is ambiguous |
| Query / SQL Lab | استعلام / مختبر SQL | keep Latin "SQL" |
| Time grain / Time range | الدقة الزمنية / النطاق الزمني | |
| Label / Legend / Tooltip | تسمية / وسيلة الإيضاح / تلميح | retire ملصق, أسطورة |
| Edit / Save / Delete | تحرير / حفظ / حذف | تحرير is the existing majority |
| Alert / Report / Schedule | تنبيه / تقرير / جدولة | |
| Permission | صلاحية | retire إذن in new strings |
| Tag / Owner / Role | وسم / مالك / دور | |
| Digits | Latin 0-9 always | no Arabic-Indic digits in msgstr |

## 5. Strings not wrapped / not in `messages.pot` (examples, not exhaustive)

| Source | Literal | In pot? |
|---|---|---|
| `src/features/alerts/AlertReportModal.tsx:1389` | `title: 'All Tabs'` | no |
| `src/explore/components/SaveModal.tsx:305` | `title: 'Out of tab'` | no |
| `src/features/datasets/AddDataset/DatasetPanel/DatasetPanel.tsx:184,190` | `'Column Name'`, `'Datatype'` | no |
| `src/features/databases/UploadDataModel/index.tsx:278,285,293` | `'Pipe'`, `'Fail'`, `'Append'` (`'Replace'` is in pot via another site) | no |
| `src/explore/components/controls/AnnotationLayerControl/AnnotationTypes.ts:70` | `'Superset annotation'` | no |
| `src/explore/components/controls/LayerConfigsControl/LayerConfigsPopoverContent.tsx:176` | `'Default Style'` | no |
| `src/features/home/Menu.tsx:355` | `alt='Apache Superset'` fallback (brand, intentionally untranslated; NxtBI sets `brandLogoAlt`) | n/a |
The main navigation, login, buttons and list chrome are well wrapped in this fork; gaps are in modal option lists and table column titles. Discover more with `grep -rnE "(title|label|name): '[A-Z]"` in `src/features src/explore`, wrap in `t()`, then `babel_update.sh`.

## 6. Upstream state and tooling

| Item | Fact |
|---|---|
| ar history | 61 commits; stub #28129 `cddcff2c63`; #29586 `4e346180e0`; AI backfill #41705 `4e2160079a`; #44611 `cba2574241` (clear fuzzy with broken placeholders); #45973 `494a507b18`; #46034 `2649e3bbf4`; latest touch `e60f79ffe2` |
| Header | `Language: ar`, Plural-Forms nplurals=6 (ok), `PO-Revision-Date: 2024-07-14`, `Generated-By: Babel 2.17.0` |
| Extract/update | `scripts/translations/babel_update.sh`: `pybabel extract ... --add-comments=i18n:`; `msgcat --sort-output --no-wrap --no-location`; `apply_do_not_translate.py`; `pybabel update --ignore-obsolete --no-fuzzy-matching`; strips trailing blank line; clears python-format on 3 `%` labels |
| Backfill | `scripts/translations/backfill_po.py` (polib, `cat.save()` at :805, `polib.pofile` :884); only fills empty msgstr, marks `#, fuzzy`; `.github/workflows/backfill-translations.yml:19-21` cron `0 6 * * 2` (weekly, Tuesday). In the fork keep this disabled or it re-adds unreviewed fuzzy |
| CI | `superset-translations.yml`: `frontend-check-translations` runs `npm run build-translation`; `babel-extract` runs `check_pot_drift.py` + `check_translation_regression.py` (fails only on confirmed -> fuzzy transitions; `untranslated -> fuzzy` is allowed; fuzzy -> confirmed is never a regression) |
| Wrapping | no wrap check in CI; file already mixes babel (76) and polib (78) wrapping |

**Minimal safe edit procedure**
1. Do NOT run `babel_update.sh` for a wording change (it reflows and re-stamps; only needed when source strings change).
2. Apply section-10 JSON with `polib.pofile(path, wrapwidth=78)` (same writer as `backfill_po.py`): match by `(msgid, msgid_plural)`, set `msgstr` / `msgstr_plural` (keys 0..5), remove `fuzzy` from `entry.flags`, delete the `# Machine-translated ...` line from `entry.comment`. Keep entry order; do not call `.sort()`. Check `git diff --stat` touches only edited entries (a wrap change would show as a whole-file diff; if so use `wrapwidth=0` consistently or edit line-wise).
3. Validate: placeholder multiset equality (the build script in this audit passed 0 errors), `msgfmt -c --check-format -o /dev/null ar/LC_MESSAGES/messages.po` (gettext), `cd superset-frontend && npm run build-translation`, `python scripts/translations/check_translation_regression.py --count` before/after.
4. Keep `%s` in every plural form (msgfmt-safe) and re-use identical HTML tags.
5. Fix the one real placeholder bug by hand: `Applied filters (%s)`.

## 7. Locale wiring gaps (fork facts)

| Area | Fact | Action |
|---|---|---|
| `useLocale.ts` antd map | `superset-frontend/src/hooks/useLocale.ts:41-57` `LOCALE_MAPPING` has en fr es it zh zh_TW ja de pt pt_BR ru ko cs sk sl nl; **no ar** (antd 6.6.8 ships `antd/locale/ar_EG`). Missing key -> `setDatePickerLocale(undefined)` (English antd strings: DatePicker, Pagination "Page", Empty, Table sort) | add `ar: () => import('antd/locale/ar_EG')` |
| dayjs | imports at `useLocale.ts:25-39` list no `ar`; `toDayjsLocale` (`:66-68`) would map `ar`->`ar` but it is never imported. dayjs 1.11.23 has `locale/ar` (weekStart Saturday=6, Latin digits in my render, "منذ 3 أيام") and `ar-sa` (weekStart Sunday=0, Latin digits) | add `import 'dayjs/locale/ar'` (or `ar-sa` if Sunday week start preferred; decide per customer) |
| html `lang` | `src/views/App.tsx:64-70` sets `lang` only; no `dir` | belongs to layout doc |
| ECharts | `plugins/plugin-chart-echarts/src/components/echartsLocale.ts:49` `AR` already mapped to `echarts/i18n/langAR-obj.js` (echarts 6.1.0) | none; verify tooltip/legend strings in browser (UNVERIFIED) |
| D3 number | `superset/config.py:626-643` `D3_FORMAT = {}`; defaults decimal ".", thousands ",", currency ["$",""]; `D3_FORMAT` is global (passed at `superset/views/base.py:676`), not per locale | keep Latin digits and "." / ","; set currency per customer; Arabic-Indic digits are NOT recommended (d3 `numerals` unused) |
| D3 time | `config.py:672-701` `D3_TIME_FORMAT = {}`; frontend default `packages/superset-ui-core/src/time-format/D3FormatConfig.ts:22-40` is English (months, days, AM/PM). Chart time-axis ticks that use d3-time-format stay English in an Arabic UI | set `D3_TIME_FORMAT` with Arabic `months`, `shortMonths`, `days`, `shortDays`, `periods: ["ص","م"]` only if the deployment is Arabic-only; for mixed users add a per-locale selection in `views/base.py:676-677` (UNVERIFIED that a callable is accepted) |
| ag-grid | `ag-grid-community` 36.3.0; grep for `localeText` / locale in `src` and `packages` (non-test) found no usage, so grids use English built-in text | UNVERIFIED which grids exist in the product; if used, load `AG_GRID_LOCALE_AR` from the ag-grid locale package (not installed: `node_modules/@ag-grid-community` absent) |
| Relative time | dayjs `fromNow` uses the active dayjs locale; list views ("Modified %s") use `dayjs.locale(...)` only after `useLocale` runs | covered once `ar` imported |
| Backend Babel | `BABEL_DEFAULT_FOLDER = "superset/translations"` (`config.py:588`), `LANGUAGES["ar"]` (`:614`) present | Babel number/date formatting digit choice in emails/reports: UNVERIFIED |
| Language packs | pack served only if `BUILD_TRANSLATIONS=true` at build | keep set in NxtBI compose (already) |

## 8. Fonts

Default theme: `superset/config.py:1296` `"fontFamily": "Inter, Helvetica, Arial, sans-serif"`, code font IBM Plex Mono (`:1297`), `fontUrls: []` (`:1295`). Inter is bundled via `@fontsource/inter` imports (`packages/superset-core/src/theme/GlobalStyles.tsx:22-25`); its CSS subsets are cyrillic/greek/vietnamese/latin only (unicode-range lines in `node_modules/@fontsource/inter/400.css`), **no Arabic glyphs**. Arabic therefore renders with the OS fallback of Helvetica/Arial/sans-serif (Arial on Windows/macOS has Arabic; minimal Linux containers may show tofu). NxtBI's own config already sets `'IBM Plex Sans Arabic', 'Noto Sans Arabic', Inter, ...` (`nxtbi/config/superset_config.py:335`). Minimal fork-side recommendation, no new dependency: change the default stack to `Inter, 'Segoe UI', Tahoma, 'Noto Sans Arabic', 'Noto Naskh Arabic', Helvetica, Arial, sans-serif` (system fonts only), and in the Docker image install `fonts-noto-core` or `fonts-noto-naskh` so headless screenshots/PDF (reports) also have Arabic glyphs (UNVERIFIED which fonts the current image contains).

## 9. Recommendations (ordered)

1. Apply the JSON below (procedure in section 6); expect about 251 `wrong`, 25 `missing`, 14 `fuzzy` (confirm only) entries. Native-speaker review of the JSON is still advised, particularly the glossary choices (سكيما, عامل تصفية).
2. Fix `Applied filters (%s)` placeholder by hand.
3. Add a CI/unit guard: placeholder multiset equality per msgstr (incl. plural forms) and "no fuzzy with extreme length ratio"; fail the fork's catalogue job.
4. Stop shipping fuzzy: remove `--use-fuzzy` at `Dockerfile:208`, and in `po2json.js:82-91` skip entries whose `entry.comments.flag` contains `fuzzy` (preserve the empty fallback). Do it only after step 1 and a second review pass, otherwise the UI drops from 5,941 to about 3,300 Arabic strings (the unreviewed 2,400 would show English). Alternative: keep fuzzy but run backfill review sprints.
5. Complete the 27 partial plural entries (6 forms each); until then keep them out of the pack.
6. Add `ar` to `useLocale.ts` (antd `ar_EG`, dayjs `ar`).
7. Wrap the unwrapped literals in section 5 and re-run `babel_update.sh`.
8. Disable `backfill-translations.yml` in the fork (or leave it opening PRs but never auto-merge).
9. Enforce the glossary: a lint listing retired terms (لوحة التحكم, فلتر, الرسم البياني, ملصق, متري) across `ar` msgstr.
10. Font stack per section 8.

## 10. Machine-applicable corrections (UTF-8 JSON, `was` = status of the current entry; plural arrays are index 0..5 = zero, one, two, few(3-10), many(11-99), other)

```json
[
{"msgid":"Home","msgstr":"الرئيسية","was":"missing"},{"msgid":"Dashboards","msgstr":"لوحات المعلومات","was":"wrong"},{"msgid":"Dashboard","msgstr":"لوحة المعلومات","was":"wrong"},{"msgid":"Chart","msgstr":"مخطط","was":"wrong"},{"msgid":"SQL Lab","msgstr":"مختبر SQL","was":"wrong"},
{"msgid":"Users","msgstr":"المستخدمون","was":"wrong"},{"msgid":"List Users","msgstr":"قائمة المستخدمين","was":"wrong"},{"msgid":"List Roles","msgstr":"قائمة الأدوار","was":"fuzzy"},{"msgid":"User Registrations","msgstr":"تسجيلات المستخدمين","was":"wrong"},{"msgid":"Themes","msgstr":"السمات","was":"wrong"},
{"msgid":"Theme","msgstr":"السمة","was":"wrong"},{"msgid":"Groups","msgstr":"المجموعات","was":"wrong"},{"msgid":"Group","msgstr":"المجموعة","was":"wrong"},{"msgid":"Permissions","msgstr":"الصلاحيات","was":"wrong"},{"msgid":"Extensions","msgstr":"الامتدادات","was":"wrong"},
{"msgid":"Languages","msgstr":"اللغات","was":"wrong"},{"msgid":"System","msgstr":"النظام","was":"wrong"},{"msgid":"Manage","msgstr":"إدارة","was":"wrong"},{"msgid":"Mine","msgstr":"الخاصة بي","was":"wrong"},{"msgid":"Edit user","msgstr":"تحرير المستخدم","was":"wrong"},
{"msgid":"Email","msgstr":"البريد الإلكتروني","was":"wrong"},{"msgid":"First name","msgstr":"الاسم الأول","was":"wrong"},{"msgid":"First Name","msgstr":"الاسم الأول","was":"wrong"},{"msgid":"Last name","msgstr":"اسم العائلة","was":"wrong"},{"msgid":"Last Name","msgstr":"اسم العائلة","was":"wrong"},
{"msgid":"Sign in","msgstr":"تسجيل الدخول","was":"wrong"},{"msgid":"Sign in with","msgstr":"تسجيل الدخول باستخدام","was":"fuzzy"},{"msgid":"Username:","msgstr":"اسم المستخدم:","was":"fuzzy"},{"msgid":"Password:","msgstr":"كلمة المرور:","was":"fuzzy"},{"msgid":"Password","msgstr":"كلمة المرور","was":"wrong"},
{"msgid":"Please enter your username","msgstr":"يرجى إدخال اسم المستخدم","was":"wrong"},{"msgid":"Please enter your password","msgstr":"يرجى إدخال كلمة المرور","was":"wrong"},{"msgid":"Please confirm your password","msgstr":"يرجى تأكيد كلمة المرور","was":"wrong"},{"msgid":"Register","msgstr":"تسجيل حساب","was":"wrong"},{"msgid":"Password is required","msgstr":"كلمة المرور مطلوبة","was":"wrong"},
{"msgid":"Username is required","msgstr":"اسم المستخدم مطلوب","was":"wrong"},{"msgid":"Email is required","msgstr":"البريد الإلكتروني مطلوب","was":"wrong"},{"msgid":"Passwords do not match!","msgstr":"كلمتا المرور غير متطابقتين!","was":"wrong"},{"msgid":"Enter your login and password below:","msgstr":"أدخل اسم المستخدم وكلمة المرور أدناه:","was":"fuzzy"},{"msgid":"Save","msgstr":"حفظ","was":"wrong"},
{"msgid":"Cancel","msgstr":"إلغاء","was":"wrong"},{"msgid":"Close","msgstr":"إغلاق","was":"wrong"},{"msgid":"Apply","msgstr":"تطبيق","was":"wrong"},{"msgid":"Add","msgstr":"إضافة","was":"wrong"},{"msgid":"Search","msgstr":"بحث","was":"wrong"},
{"msgid":"Yes","msgstr":"نعم","was":"missing"},{"msgid":"No","msgstr":"لا","was":"missing"},{"msgid":"OK","msgstr":"موافق","was":"wrong"},{"msgid":"Run","msgstr":"تشغيل","was":"wrong"},{"msgid":"Run selection","msgstr":"تشغيل التحديد","was":"wrong"},
{"msgid":"Import","msgstr":"استيراد","was":"wrong"},{"msgid":"Share","msgstr":"مشاركة","was":"wrong"},{"msgid":"Create","msgstr":"إنشاء","was":"wrong"},{"msgid":"Clear","msgstr":"مسح","was":"wrong"},{"msgid":"Back","msgstr":"رجوع","was":"wrong"},
{"msgid":"Retry","msgstr":"إعادة المحاولة","was":"wrong"},{"msgid":"Confirm","msgstr":"تأكيد","was":"wrong"},{"msgid":"Select","msgstr":"تحديد","was":"wrong"},{"msgid":"Select All","msgstr":"تحديد الكل","was":"wrong"},{"msgid":"Select all","msgstr":"تحديد الكل","was":"wrong"},
{"msgid":"Resize","msgstr":"تغيير الحجم","was":"wrong"},{"msgid":"Expand","msgstr":"توسيع","was":"wrong"},{"msgid":"New","msgstr":"جديد","was":"wrong"},{"msgid":"Copied!","msgstr":"تم النسخ!","was":"wrong"},{"msgid":"Copy column name","msgstr":"نسخ اسم العمود","was":"wrong"},
{"msgid":"Copy code to clipboard","msgstr":"نسخ الشيفرة إلى الحافظة","was":"wrong"},{"msgid":"You don't have permission to copy to clipboard","msgstr":"ليس لديك صلاحية النسخ إلى الحافظة","was":"wrong"},{"msgid":"Refresh settings","msgstr":"إعدادات التحديث","was":"wrong"},{"msgid":"Refresh table schema","msgstr":"تحديث بنية الجدول","was":"wrong"},{"msgid":"Refresh delayed","msgstr":"تأخر التحديث","was":"wrong"},
{"msgid":"Refresh interval set for this session","msgstr":"تم ضبط فاصل التحديث لهذه الجلسة","was":"wrong"},{"msgid":"Refresh dashboard","msgstr":"تحديث لوحة المعلومات","was":"wrong"},{"msgid":"Force refresh","msgstr":"فرض التحديث","was":"wrong"},{"msgid":"Reset Columns","msgstr":"إعادة تعيين الأعمدة","was":"wrong"},{"msgid":"Reset columns","msgstr":"إعادة تعيين الأعمدة","was":"wrong"},
{"msgid":"Reset to default folders?","msgstr":"إعادة التعيين إلى المجلدات الافتراضية؟","was":"wrong"},{"msgid":"Fetching data...","msgstr":"جارٍ جلب البيانات...","was":"wrong"},{"msgid":"Fetching","msgstr":"جارٍ الجلب","was":"wrong"},{"msgid":"Loading","msgstr":"جارٍ التحميل","was":"fuzzy"},{"msgid":"Loading filter values","msgstr":"جارٍ تحميل قيم عامل التصفية","was":"wrong"},
{"msgid":"Loading timezones...","msgstr":"جارٍ تحميل المناطق الزمنية...","was":"wrong"},{"msgid":"Clear Sort","msgstr":"إلغاء الفرز","was":"wrong"},{"msgid":"Clear form","msgstr":"مسح النموذج","was":"wrong"},{"msgid":"Search by","msgstr":"بحث حسب","was":"wrong"},{"msgid":"Page","msgstr":"الصفحة","was":"wrong"},
{"msgid":"Page Size:","msgstr":"حجم الصفحة:","was":"wrong"},{"msgid":"Page navigation","msgstr":"التنقل بين الصفحات","was":"wrong"},{"msgid":"Summary","msgstr":"الملخص","was":"wrong"},{"msgid":"Download to client","msgstr":"تنزيل إلى الجهاز","was":"wrong"},{"msgid":"Upload Excel to database","msgstr":"رفع ملف Excel إلى قاعدة البيانات","was":"fuzzy"},
{"msgid":"Upload CSV to database","msgstr":"رفع ملف CSV إلى قاعدة البيانات","was":"wrong"},{"msgid":"Filters","msgstr":"عوامل التصفية","was":"wrong"},{"msgid":"Apply filters","msgstr":"تطبيق عوامل التصفية","was":"wrong"},{"msgid":"Filters and controls","msgstr":"عوامل التصفية وعناصر التحكم","was":"wrong"},{"msgid":"Add filter","msgstr":"إضافة عامل تصفية","was":"wrong"},
{"msgid":"Clear all filters","msgstr":"مسح كل عوامل التصفية","was":"wrong"},{"msgid":"No filter","msgstr":"بدون عامل تصفية","was":"wrong"},{"msgid":"No filters","msgstr":"لا توجد عوامل تصفية","was":"wrong"},{"msgid":"No applied filters","msgstr":"لا توجد عوامل تصفية مطبقة","was":"wrong"},{"msgid":"No items","msgstr":"لا توجد عناصر","was":"wrong"},
{"msgid":"Filter Type","msgstr":"نوع عامل التصفية","was":"wrong"},{"msgid":"Filter type","msgstr":"نوع عامل التصفية","was":"wrong"},{"msgid":"Filter value is required","msgstr":"قيمة عامل التصفية مطلوبة","was":"wrong"},{"msgid":"Filter charts","msgstr":"تصفية المخططات","was":"wrong"},{"msgid":"Filter options","msgstr":"خيارات التصفية","was":"wrong"},
{"msgid":"Cross-filters","msgstr":"عوامل التصفية المتقاطعة","was":"wrong"},{"msgid":"Filters out of scope (%d)","msgstr":"عوامل التصفية خارج النطاق (%d)","was":"wrong"},{"msgid":"Customizations out of scope (%d)","msgstr":"التخصيصات خارج النطاق (%d)","was":"wrong"},{"msgid":"Filter value (case sensitive)","msgstr":"قيمة عامل التصفية (حساسة لحالة الأحرف)","was":"wrong"},{"msgid":"Sort filter values","msgstr":"فرز قيم عامل التصفية","was":"wrong"},
{"msgid":"Pre-filter available values","msgstr":"تصفية مسبقة للقيم المتاحة","was":"wrong"},{"msgid":"Edit dashboard","msgstr":"تحرير لوحة المعلومات","was":"wrong"},{"msgid":"Edit Dashboard","msgstr":"تحرير لوحة المعلومات","was":"wrong"},{"msgid":"Show Dashboard","msgstr":"عرض لوحة المعلومات","was":"wrong"},{"msgid":"You do not have permission to edit this dashboard","msgstr":"ليس لديك صلاحية تحرير لوحة المعلومات هذه","was":"wrong"},
{"msgid":"You do not have permissions to edit this dashboard.","msgstr":"ليس لديك صلاحية تحرير لوحة المعلومات هذه.","was":"wrong"},{"msgid":"You don't have access to this dashboard.","msgstr":"ليس لديك صلاحية الوصول إلى لوحة المعلومات هذه.","was":"wrong"},{"msgid":"Sorry, there was an error saving this dashboard: %s","msgstr":"عذرًا، حدث خطأ أثناء حفظ لوحة المعلومات: %s","was":"wrong"},{"msgid":"Dashboard %(dashboard_id)s not found","msgstr":"لم يتم العثور على لوحة المعلومات %(dashboard_id)s","was":"fuzzy"},{"msgid":"Chart Options","msgstr":"خيارات المخطط","was":"wrong"},
{"msgid":"Chart options","msgstr":"خيارات المخطط","was":"wrong"},{"msgid":"Chart Title","msgstr":"عنوان المخطط","was":"wrong"},{"msgid":"Chart ID","msgstr":"معرّف المخطط","was":"wrong"},{"msgid":"Chart Orientation","msgstr":"اتجاه المخطط","was":"wrong"},{"msgid":"Select chart","msgstr":"اختيار مخطط","was":"wrong"},
{"msgid":"All charts","msgstr":"جميع المخططات","was":"wrong"},{"msgid":"Chart not found","msgstr":"لم يتم العثور على المخطط","was":"wrong"},{"msgid":"Chart %(id)s not found","msgstr":"لم يتم العثور على المخطط %(id)s","was":"wrong"},{"msgid":"The id of the active chart","msgstr":"معرّف المخطط النشط","was":"wrong"},{"msgid":"Whether to display a legend for the chart","msgstr":"ما إذا كان سيتم عرض وسيلة الإيضاح للمخطط","was":"wrong"},
{"msgid":"Legend","msgstr":"وسيلة الإيضاح","was":"wrong"},{"msgid":"Show legend","msgstr":"عرض وسيلة الإيضاح","was":"wrong"},{"msgid":"Labels","msgstr":"التسميات","was":"wrong"},{"msgid":"Show Labels","msgstr":"عرض التسميات","was":"wrong"},{"msgid":"Label","msgstr":"التسمية","was":"wrong"},
{"msgid":"Whether to display the labels.","msgstr":"ما إذا كان سيتم عرض التسميات.","was":"wrong"},{"msgid":"Metric","msgstr":"المقياس","was":"wrong"},{"msgid":"metric","msgstr":"مقياس","was":"wrong"},{"msgid":"Table","msgstr":"جدول","was":"wrong"},{"msgid":"Table V2","msgstr":"جدول V2","was":"fuzzy"},
{"msgid":"Group by","msgstr":"تجميع حسب","was":"wrong"},{"msgid":"Group By","msgstr":"تجميع حسب","was":"wrong"},{"msgid":"Time","msgstr":"الوقت","was":"wrong"},{"msgid":"Time grain","msgstr":"الدقة الزمنية","was":"wrong"},{"msgid":"Time shift","msgstr":"الإزاحة الزمنية","was":"wrong"},
{"msgid":"Time Shift","msgstr":"الإزاحة الزمنية","was":"wrong"},{"msgid":"Limit","msgstr":"الحد","was":"fuzzy"},{"msgid":"Count","msgstr":"العدد","was":"wrong"},{"msgid":"Average","msgstr":"المتوسط","was":"wrong"},{"msgid":"mean","msgstr":"المتوسط","was":"wrong"},
{"msgid":"std","msgstr":"الانحراف المعياري","was":"wrong"},{"msgid":"min","msgstr":"الحد الأدنى","was":"wrong"},{"msgid":"Min","msgstr":"الحد الأدنى","was":"wrong"},{"msgid":"cumsum","msgstr":"المجموع التراكمي","was":"wrong"},{"msgid":"Main","msgstr":"الرئيسي","was":"wrong"},
{"msgid":"Featured","msgstr":"مميز","was":"wrong"},{"msgid":"Created","msgstr":"تاريخ الإنشاء","was":"wrong"},{"msgid":"Category","msgstr":"الفئة","was":"wrong"},{"msgid":"Categorical","msgstr":"فئوي","was":"wrong"},{"msgid":"Categorical palette","msgstr":"لوحة ألوان فئوية","was":"wrong"},
{"msgid":"Custom color palettes","msgstr":"لوحات ألوان مخصصة","was":"wrong"},{"msgid":"Subcategories","msgstr":"الفئات الفرعية","was":"wrong"},{"msgid":"Custom","msgstr":"مخصص","was":"wrong"},{"msgid":"General","msgstr":"عام","was":"wrong"},{"msgid":"General information","msgstr":"معلومات عامة","was":"wrong"},
{"msgid":"Inside","msgstr":"داخل","was":"wrong"},{"msgid":"Extent","msgstr":"المدى","was":"wrong"},{"msgid":"to","msgstr":"إلى","was":"wrong"},{"msgid":"Top","msgstr":"أعلى","was":"wrong"},{"msgid":"Bottom","msgstr":"أسفل","was":"wrong"},
{"msgid":"Right","msgstr":"اليمين","was":"wrong"},{"msgid":"Business","msgstr":"الأعمال","was":"wrong"},{"msgid":"deckGL","msgstr":"deck.gl","was":"wrong"},{"msgid":"ECharts","msgstr":"ECharts","was":"wrong"},{"msgid":"Actions","msgstr":"الإجراءات","was":"wrong"},
{"msgid":"Bar","msgstr":"شريط","was":"wrong"},{"msgid":"Marker","msgstr":"علامة","was":"wrong"},{"msgid":"Report","msgstr":"تقرير","was":"wrong"},{"msgid":"report","msgstr":"تقرير","was":"wrong"},{"msgid":"Schedule","msgstr":"الجدولة","was":"wrong"},
{"msgid":"Schedule type","msgstr":"نوع الجدولة","was":"wrong"},{"msgid":"Schedule query","msgstr":"جدولة الاستعلام","was":"wrong"},{"msgid":"Current day","msgstr":"اليوم الحالي","was":"wrong"},{"msgid":"Current month","msgstr":"الشهر الحالي","was":"wrong"},{"msgid":"Current week","msgstr":"الأسبوع الحالي","was":"wrong"},
{"msgid":"previous calendar quarter","msgstr":"الربع التقويمي السابق","was":"wrong"},{"msgid":"Series settings","msgstr":"إعدادات السلسلة","was":"wrong"},{"msgid":"Height of each row in pixels","msgstr":"ارتفاع كل صف بالبكسل","was":"wrong"},{"msgid":"Row height","msgstr":"ارتفاع الصف","was":"wrong"},{"msgid":"Charts per row","msgstr":"عدد المخططات في كل صف","was":"wrong"},
{"msgid":"Fit columns dynamically","msgstr":"ملاءمة الأعمدة ديناميكيًا","was":"wrong"},{"msgid":"Display all","msgstr":"عرض الكل","was":"wrong"},{"msgid":"Show cell bars for all columns","msgstr":"عرض أشرطة الخلايا لجميع الأعمدة","was":"wrong"},{"msgid":"Align +/- for all columns","msgstr":"محاذاة +/- لجميع الأعمدة","was":"wrong"},{"msgid":"Basic conditional formatting","msgstr":"تنسيق شرطي أساسي","was":"wrong"},
{"msgid":"Custom conditional formatting","msgstr":"تنسيق شرطي مخصص","was":"wrong"},{"msgid":"Visual formatting","msgstr":"تنسيق مرئي","was":"wrong"},{"msgid":"entire row","msgstr":"الصف بأكمله","was":"wrong"},{"msgid":"Percentage metric calculation","msgstr":"حساب مقياس النسبة المئوية","was":"wrong"},{"msgid":"All records","msgstr":"كل السجلات","was":"wrong"},
{"msgid":"CSV Export","msgstr":"تصدير CSV","was":"wrong"},{"msgid":"color type","msgstr":"نوع اللون","was":"wrong"},{"msgid":"Decrease label","msgstr":"تسمية الانخفاض","was":"wrong"},{"msgid":"Increase label","msgstr":"تسمية الزيادة","was":"wrong"},{"msgid":"Increase color","msgstr":"لون الزيادة","was":"wrong"},
{"msgid":"Decrease color","msgstr":"لون الانخفاض","was":"wrong"},{"msgid":"Decrease","msgstr":"انخفاض","was":"wrong"},{"msgid":"Schema","msgstr":"سكيما","was":"wrong"},{"msgid":"Select schema","msgstr":"اختيار السكيما","was":"wrong"},{"msgid":"Select database","msgstr":"اختيار قاعدة البيانات","was":"wrong"},
{"msgid":"Select Database and Schema","msgstr":"اختيار قاعدة البيانات والسكيما","was":"wrong"},{"msgid":"Schema cache timeout","msgstr":"مهلة التخزين المؤقت للسكيما","was":"wrong"},{"msgid":"Schemas allowed for File upload","msgstr":"السكيمات المسموح بها لرفع الملفات","was":"wrong"},{"msgid":"Schema not found.","msgstr":"لم يتم العثور على السكيما.","was":"fuzzy"},{"msgid":"There was an error loading the schemas","msgstr":"حدث خطأ أثناء تحميل السكيمات","was":"wrong"},
{"msgid":"Format","msgstr":"تنسيق","was":"wrong"},{"msgid":"Format SQL","msgstr":"تنسيق SQL","was":"wrong"},{"msgid":"Format SQL query","msgstr":"تنسيق استعلام SQL","was":"wrong"},{"msgid":"Format JSON configuration","msgstr":"تنسيق إعدادات JSON","was":"wrong"},{"msgid":"formatted","msgstr":"منسق","was":"wrong"},
{"msgid":"Show SQL","msgstr":"عرض SQL","was":"wrong"},{"msgid":"Show Log","msgstr":"عرض السجل","was":"wrong"},{"msgid":"Show Bubbles","msgstr":"عرض الفقاعات","was":"wrong"},{"msgid":"Table or View \"%(table)s\" does not exist.","msgstr":"الجدول أو العرض \"%(table)s\" غير موجود.","was":"wrong"},{"msgid":"There was an error creating the group. Please, try again.","msgstr":"حدث خطأ أثناء إنشاء المجموعة. يرجى المحاولة مرة أخرى.","was":"wrong"},
{"msgid":"There was an error creating the role. Please, try again.","msgstr":"حدث خطأ أثناء إنشاء الدور. يرجى المحاولة مرة أخرى.","was":"wrong"},{"msgid":"There was an error creating the user. Please, try again.","msgstr":"حدث خطأ أثناء إنشاء المستخدم. يرجى المحاولة مرة أخرى.","was":"wrong"},{"msgid":"There was an error duplicating the role. Please, try again.","msgstr":"حدث خطأ أثناء تكرار الدور. يرجى المحاولة مرة أخرى.","was":"wrong"},{"msgid":"There was an error loading groups.","msgstr":"حدث خطأ أثناء تحميل المجموعات.","was":"wrong"},{"msgid":"There was an error loading permissions.","msgstr":"حدث خطأ أثناء تحميل الصلاحيات.","was":"wrong"},
{"msgid":"There was an error loading the catalogs","msgstr":"حدث خطأ أثناء تحميل الكتالوجات","was":"wrong"},{"msgid":"There was an error fetching the filtered charts and dashboards:","msgstr":"حدث خطأ أثناء جلب المخططات ولوحات المعلومات المصفّاة:","was":"wrong"},{"msgid":"An error occurred while accessing the copy link.","msgstr":"حدث خطأ أثناء الوصول إلى رابط النسخ.","was":"wrong"},{"msgid":"An error occurred while creating the copy link.","msgstr":"حدث خطأ أثناء إنشاء رابط النسخ.","was":"wrong"},{"msgid":"You do not have permission to perform this operation","msgstr":"ليس لديك صلاحية تنفيذ هذه العملية","was":"wrong"},
{"msgid":"You don't have permission to export data","msgstr":"ليس لديك صلاحية تصدير البيانات","was":"wrong"},{"msgid":"You don't have permission to export images","msgstr":"ليس لديك صلاحية تصدير الصور","was":"wrong"},{"msgid":"You do not have permission to edit this chart","msgstr":"ليس لديك صلاحية تحرير هذا المخطط","was":"wrong"},{"msgid":"You do not have sufficient permissions to edit the chart","msgstr":"ليس لديك صلاحيات كافية لتحرير المخطط","was":"wrong"},{"msgid":"You don't have access to this chart.","msgstr":"ليس لديك صلاحية الوصول إلى هذا المخطط.","was":"wrong"},
{"msgid":"You don't have access to this dataset.","msgstr":"ليس لديك صلاحية الوصول إلى مجموعة البيانات هذه.","was":"wrong"},{"msgid":"You don't have access to this semantic view.","msgstr":"ليس لديك صلاحية الوصول إلى هذا العرض الدلالي.","was":"wrong"},{"msgid":"You don't have permission to access this resource.","msgstr":"ليس لديك صلاحية الوصول إلى هذا المورد.","was":"fuzzy"},{"msgid":"Sorry, something went wrong. Try again later.","msgstr":"عذرًا، حدث خطأ ما. حاول مرة أخرى لاحقًا.","was":"wrong"},{"msgid":"Sorry, something went wrong. Please try again.","msgstr":"عذرًا، حدث خطأ ما. يرجى المحاولة مرة أخرى.","was":"wrong"},
{"msgid":"Sorry, something went wrong. Embedding could not be deactivated.","msgstr":"عذرًا، حدث خطأ ما. تعذّر إلغاء تفعيل التضمين.","was":"wrong"},{"msgid":"Forbidden","msgstr":"محظور","was":"fuzzy"},{"msgid":"Alert is active","msgstr":"التنبيه نشط","was":"wrong"},{"msgid":"Alert contents","msgstr":"محتويات التنبيه","was":"wrong"},{"msgid":"Send as PDF","msgstr":"إرسال بصيغة PDF","was":"wrong"},
{"msgid":"Report Schedule execution failed when generating a pdf.","msgstr":"فشل تنفيذ جدول التقرير عند إنشاء ملف pdf.","was":"wrong"},{"msgid":"recipients","msgstr":"المستلمون","was":"wrong"},{"msgid":"email subject","msgstr":"موضوع البريد الإلكتروني","was":"wrong"},{"msgid":"crontab","msgstr":"crontab","was":"wrong"},{"msgid":"No groups yet","msgstr":"لا توجد مجموعات بعد","was":"wrong"},
{"msgid":"No roles yet","msgstr":"لا توجد أدوار بعد","was":"wrong"},{"msgid":"No user registrations yet","msgstr":"لا توجد تسجيلات مستخدمين بعد","was":"wrong"},{"msgid":"No users yet","msgstr":"لا يوجد مستخدمون بعد","was":"wrong"},{"msgid":"Auto-detect","msgstr":"اكتشاف تلقائي","was":"wrong"},{"msgid":"Automatically sync columns","msgstr":"مزامنة الأعمدة تلقائيًا","was":"wrong"},
{"msgid":"Autosize All Columns","msgstr":"ضبط حجم جميع الأعمدة تلقائيًا","was":"wrong"},{"msgid":"Autosize all columns","msgstr":"ضبط حجم جميع الأعمدة تلقائيًا","was":"wrong"},{"msgid":"Autosize Column","msgstr":"ضبط حجم العمود تلقائيًا","was":"wrong"},{"msgid":"Autosize This Column","msgstr":"ضبط حجم هذا العمود تلقائيًا","was":"wrong"},{"msgid":"auto","msgstr":"تلقائي","was":"wrong"},
{"msgid":"Clear default dark theme","msgstr":"مسح السمة الداكنة الافتراضية","was":"wrong"},{"msgid":"Clear local theme","msgstr":"مسح السمة المحلية","was":"wrong"},{"msgid":"Reset and reselect values","msgstr":"إعادة التعيين وإعادة تحديد القيم","was":"fuzzy"},{"msgid":"%s row","msgid_plural":"%s rows","msgstr_plural":["%s صف","%s صف","%s صفان","%s صفوف","%s صفًا","%s صف"],"was":"missing"},{"msgid":"%s column","msgid_plural":"%s columns","msgstr_plural":["%s عمود","%s عمود","%s عمودان","%s أعمدة","%s عمودًا","%s عمود"],"was":"missing"},
{"msgid":"%s item","msgid_plural":"%s items","msgstr_plural":["%s عنصر","%s عنصر","%s عنصران","%s عناصر","%s عنصرًا","%s عنصر"],"was":"missing"},{"msgid":"%s option","msgid_plural":"%s options","msgstr_plural":["%s خيار","%s خيار","%s خياران","%s خيارات","%s خيارًا","%s خيار"],"was":"missing"},{"msgid":"%s metric","msgid_plural":"%s metrics","msgstr_plural":["%s مقياس","%s مقياس","%s مقياسان","%s مقاييس","%s مقياسًا","%s مقياس"],"was":"missing"},{"msgid":"%s out of %s column","msgid_plural":"%s out of %s columns","msgstr_plural":["%s من %s عمود","%s من %s عمود","%s من %s عمودين","%s من %s أعمدة","%s من %s عمودًا","%s من %s عمود"],"was":"missing"},{"msgid":"%s out of %s metric","msgid_plural":"%s out of %s metrics","msgstr_plural":["%s من %s مقياس","%s من %s مقياس","%s من %s مقياسين","%s من %s مقاييس","%s من %s مقياسًا","%s من %s مقياس"],"was":"missing"},
{"msgid":"%s record...","msgid_plural":"%s records...","msgstr_plural":["%s سجل...","%s سجل...","%s سجلان...","%s سجلات...","%s سجلًا...","%s سجل..."],"was":"missing"},{"msgid":"%s second","msgid_plural":"%s seconds","msgstr_plural":["%s ثانية","%s ثانية","%s ثانيتان","%s ثوانٍ","%s ثانية","%s ثانية"],"was":"missing"},{"msgid":"%s s ago","msgid_plural":"%s s ago","msgstr_plural":["منذ %s ث","منذ %s ث","منذ %s ث","منذ %s ث","منذ %s ث","منذ %s ث"],"was":"missing"},{"msgid":"%s min ago","msgid_plural":"%s min ago","msgstr_plural":["منذ %s د","منذ %s د","منذ %s د","منذ %s د","منذ %s د","منذ %s د"],"was":"missing"},{"msgid":"%s hr ago","msgid_plural":"%s hr ago","msgstr_plural":["منذ %s س","منذ %s س","منذ %s س","منذ %s س","منذ %s س","منذ %s س"],"was":"missing"},
{"msgid":"%s day ago","msgid_plural":"%s days ago","msgstr_plural":["منذ %s يوم","منذ %s يوم","منذ %s يومين","منذ %s أيام","منذ %s يومًا","منذ %s يوم"],"was":"missing"},{"msgid":"Deleted %(num)d chart","msgid_plural":"Deleted %(num)d charts","msgstr_plural":["تم حذف %(num)d مخطط","تم حذف %(num)d مخطط","تم حذف %(num)d مخططين","تم حذف %(num)d مخططات","تم حذف %(num)d مخططًا","تم حذف %(num)d مخطط"],"was":"missing"},{"msgid":"Deleted %(num)d dashboard","msgid_plural":"Deleted %(num)d dashboards","msgstr_plural":["تم حذف %(num)d لوحة معلومات","تم حذف %(num)d لوحة معلومات","تم حذف %(num)d لوحتي معلومات","تم حذف %(num)d لوحات معلومات","تم حذف %(num)d لوحة معلومات","تم حذف %(num)d لوحة معلومات"],"was":"missing"},{"msgid":"Deleted %(num)d dataset","msgid_plural":"Deleted %(num)d datasets","msgstr_plural":["تم حذف %(num)d مجموعة بيانات","تم حذف %(num)d مجموعة بيانات","تم حذف %(num)d مجموعتي بيانات","تم حذف %(num)d مجموعات بيانات","تم حذف %(num)d مجموعة بيانات","تم حذف %(num)d مجموعة بيانات"],"was":"missing"},{"msgid":"Deleted %(num)d annotation","msgid_plural":"Deleted %(num)d annotations","msgstr_plural":["تم حذف %(num)d تعليق توضيحي","تم حذف %(num)d تعليق توضيحي","تم حذف %(num)d تعليقين توضيحيين","تم حذف %(num)d تعليقات توضيحية","تم حذف %(num)d تعليقًا توضيحيًا","تم حذف %(num)d تعليق توضيحي"],"was":"missing"},
{"msgid":"Deleted %(num)d annotation layer","msgid_plural":"Deleted %(num)d annotation layers","msgstr_plural":["تم حذف %(num)d طبقة تعليقات توضيحية","تم حذف %(num)d طبقة تعليقات توضيحية","تم حذف %(num)d طبقتي تعليقات توضيحية","تم حذف %(num)d طبقات تعليقات توضيحية","تم حذف %(num)d طبقة تعليقات توضيحية","تم حذف %(num)d طبقة تعليقات توضيحية"],"was":"missing"},{"msgid":"Deleted %(num)d css template","msgid_plural":"Deleted %(num)d css templates","msgstr_plural":["تم حذف %(num)d قالب CSS","تم حذف %(num)d قالب CSS","تم حذف %(num)d قالبي CSS","تم حذف %(num)d قوالب CSS","تم حذف %(num)d قالب CSS","تم حذف %(num)d قالب CSS"],"was":"missing"},{"msgid":"Deleted %(num)d report schedule","msgid_plural":"Deleted %(num)d report schedules","msgstr_plural":["تم حذف %(num)d جدولة تقرير","تم حذف %(num)d جدولة تقرير","تم حذف %(num)d جدولتي تقرير","تم حذف %(num)d جدولات تقارير","تم حذف %(num)d جدولة تقرير","تم حذف %(num)d جدولة تقرير"],"was":"missing"},{"msgid":"Deleted %(num)d saved query","msgid_plural":"Deleted %(num)d saved queries","msgstr_plural":["تم حذف %(num)d استعلام محفوظ","تم حذف %(num)d استعلام محفوظ","تم حذف %(num)d استعلامين محفوظين","تم حذف %(num)d استعلامات محفوظة","تم حذف %(num)d استعلامًا محفوظًا","تم حذف %(num)d استعلام محفوظ"],"was":"missing"},{"msgid":"Deleted %(num)d theme","msgid_plural":"Deleted %(num)d themes","msgstr_plural":["تم حذف %(num)d سمة","تم حذف %(num)d سمة","تم حذف %(num)d سمتين","تم حذف %(num)d سمات","تم حذف %(num)d سمة","تم حذف %(num)d سمة"],"was":"missing"}
]
```
