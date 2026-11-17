# 05 - Arabic catalogue changes (what was applied to `ar/LC_MESSAGES/messages.po`)

Companion of `04-arabic-catalogue.md` (the audit). This file records what was actually changed in the fork, what was refused, what is still missing, and how to redo it after an upstream merge. Scope: wording only; no layout. Digits stay Latin everywhere.

## 1. Result

Counts from `babel.messages.pofile.read_po` (header excluded; polib gives the same numbers):

| | Before | After |
|---|---|---|
| Entries | 5,950 | 5,950 |
| Translated, not fuzzy | 3,223 | 3,430 |
| Fuzzy | 2,718 | 2,512 |
| Untranslated | 9 | 8 |

Entries rewritten by hand-reviewed corrections: **345** (206 were fuzzy, 138 were confirmed but wrong or poor, 1 was empty). Of these 290 come from the section 10 list of `04-arabic-catalogue.md` and 55 are new (section 3). Their `#, fuzzy` flag and the `# Machine-translated via backfill_po.py ...` comment were removed; other flags (`python-format`) were kept.

A further **104** entries (still fuzzy, not reviewed) only had retired terms replaced mechanically (section 4). They stay fuzzy.

Nothing else in the file changed: comments, order, header, wrapping of the other 5,500 entries are byte-identical (`git diff` hunks: 652, all inside the touched entries). The file still parses, and compiles with Babel `write_mo` (with and without fuzzy). `msgfmt` and `polib` are not in the image; the repo checker `scripts/translations/check_translation_regression.py` needs `msgfmt`, so it could not run here. Its numbers equal the Babel counts above, and every change is `fuzzy -> confirmed`, `confirmed -> confirmed` or `empty -> confirmed`, never `confirmed -> fuzzy`, so it cannot report a regression.

Placeholders, HTML tags, newlines and leading/trailing spaces were validated for every correction before it was written (`%s`, `%d`, `%(name)s`, `{name}`, tags: multiset equal to the msgid; plural forms: no placeholder that the msgid_plural does not have, forms 3-5 carry all of them). **0 corrections were rejected, 0 msgids were missing from the catalogue.** After writing, an independent pass over the 345 entries found 0 placeholder problems, 0 still fuzzy and every plural with 6 non-empty forms. The one real bug of the audit is fixed: `Applied filters (%s)` had `%d`.

### Corrections by area (345)

| Area | Count | Examples |
|---|---|---|
| Navigation, auth, users and roles | 45 | `Home`, `Dashboards`, `Sign in`, `Users`, `List Roles`, `Is active?`, `Last login` |
| Common buttons and verbs | 60 | `Save`, `Cancel`, `Run`, `Apply`, `Back`, `Retry`, `Select all`, `Done`, refresh and loading texts |
| Filters and filter bar | 23 | `Filters`, `Apply filters`, `No applied filters`, `Cross-filters`, `Applied filters (%s)` |
| Dashboard | 10 | `Edit dashboard`, `Refresh dashboard`, `Show Dashboard` |
| Chart, Explore controls, other | 98 | `Chart`, `Legend`, `Time grain`, `Group by`, `Show only my charts`, table and metric labels |
| Schema, database, SQL Lab | 26 | `Schema`, `Select database`, `Show SQL`, `Select a schema` |
| Alerts, reports, schedules | 14 | `Report`, `Schedule`, `Send as PDF` |
| Errors, toasts, permissions | 43 | `Failed to ...`, `There was an error ...`, `You don't have permission ...` |
| Plural entries (6 forms each) | 26 | `%s option(s)`, `%s row(s)`, `Deleted %(num)d ...` (12), relative times |

(Areas were assigned by keyword rules and are approximate; the machine-readable list in the appendix is authoritative.)

## 2. Glossary actually applied

One term per concept. Taken from section 4 of the audit; the NxtBI-specific decisions are marked.

| English | Arabic | Notes |
|---|---|---|
| Dashboard(s) | لوحة المعلومات / لوحات المعلومات | retired: لوحة التحكم, لوحة القيادة, لوحه القياده |
| Chart(s) | مخطط / مخططات | retired: رسم بياني, الرسوم البيانية, جدول (as chart) |
| Dataset(s) | مجموعة بيانات / مجموعات بيانات | |
| Filter(s) | عامل تصفية / عوامل التصفية; verb تصفية | |
| Metric / Dimension | مقياس / بُعد | |
| Schema | سكيما | frees مخطط for charts (NxtBI decision, native-speaker review advised) |
| Query / SQL Lab | استعلام / مختبر SQL | |
| Time grain / Time range | الدقة الزمنية / النطاق الزمني | |
| Label / Legend | تسمية / وسيلة الإيضاح | |
| Edit / Save / Delete | تحرير / حفظ / حذف | |
| Run / Apply / Clear | تشغيل / تطبيق / مسح | |
| Permission | صلاحية | |
| Theme | سمة | previous renderings were inconsistent |
| Select (verb in labels) | حدد ... / تحديد | |

## 3. Additions to the audit's list (55)

Found by reading the Arabic screenshots in `nxtbi/out/rtl-audit/ar-light-desktop/` (welcome, dashboard list, chart list, dashboard view and edit mode, filter select, explore, SQL Lab, database modal, users and alerts lists), then looking each visible English, fuzzy-wrong or awkward string up in the catalogue:

- Plurals that were shown in English in the screenshots because only `msgstr[0]` existed: `Drop a column here or click`, `Drop a column/metric here or click` (explore drop zones; the dashboard filter selects show `%s options`, fixed by the audit's `%s option` entry), `Added to 1 dashboard`, `This was triggered by:`.
- Users list columns: `Is active?`, `Last login`, `Login count`, `Changed on`, `Created on`.
- List and explore chrome: `Creator`, `Duplicate`, `Done`, `Saved`, `Columns`, `Bulk select`, `Light`, `About`, `Chart Type`, `Viz type`, `View all charts`, `Filter your charts`, `Show only my charts`.
- Empty states: `There is currently no information to display.` (showed "the type of visualization to display"), `No %s yet`.
- Select placeholders and toasts that were wrong (`Select a database` = "Select a dataset", `Select a schema/theme/tab/semantic layer ...` = "Select the schema", `Failed to copy API key to clipboard`, `Failed to create API key`, theme and cross-filter failure toasts).
- `Applied filters (%s)` (placeholder bug) and `Invalid temporal filter value for column %(column)s` (the only real gap among the untranslated).

## 4. Mechanical normalisation of retired terms (104 entries, still fuzzy)

For entries not otherwise corrected: if the msgid contains `dashboard`, `لوحة التحكم / لوحات التحكم / لوحة القيادة / لوحات القيادة / لوحه القياده` became the glossary form; if it contains `chart`, `الرسوم البيانية -> المخططات`, `الرسم البياني -> المخطط`, `رسوم بيانية -> مخططات`, `رسم بياني -> مخطط`. Placeholders are not touched. Remaining drift that was not changed (needs a reviewer): `فلتر / فلاتر / مرشح` for filter (about 70 entries), `الأسطورة` for legend, `متري`.

## 5. Strings not wrapped in `t()` (not in `messages.pot`, so not translatable)

For the lead; no frontend file was touched.

| Where | Literal | Seen in |
|---|---|---|
| `superset-frontend/src/components/ListView/ListView.tsx:642-645` | template literal `` `${from}-${to} of ${count}` `` | every list footer: shows "of 12 1-12" in RTL. Needs `t('%s-%s of %s', from, to, count)` |
| `superset-frontend/src/SqlLab/utils/newQueryTabName.ts:24` | `'Untitled Query '` + number | SQL Lab tab title "Untitled Query 1" (a translated `Untitled Query` exists) |
| antd `Tabs` add button label "Add tab" | antd locale string, not Superset's | needs `ar` in `src/hooks/useLocale.ts` (`antd/locale/ar_EG`), see 04 section 7 |
| Relative dates such as "Today at 12:50" in the alerts list | dayjs calendar strings | needs `import 'dayjs/locale/ar'` in `useLocale.ts` (04 section 7) |
| `src/features/alerts/AlertReportModal.tsx:1389` | `'All Tabs'` | 04 section 5 |
| `src/explore/components/SaveModal.tsx:305` | `'Out of tab'` | 04 section 5 |
| `src/features/datasets/AddDataset/DatasetPanel/DatasetPanel.tsx:184,190` | `'Column Name'`, `'Datatype'` | 04 section 5 |
| `src/features/databases/UploadDataModel/index.tsx:278,285,293` | `'Pipe'`, `'Fail'`, `'Append'` | 04 section 5 |
| `src/explore/components/controls/AnnotationLayerControl/AnnotationTypes.ts:70` | `'Superset annotation'` | 04 section 5 |
| `src/explore/components/controls/LayerConfigsControl/LayerConfigsPopoverContent.tsx:176` | `'Default Style'` | 04 section 5 |

English that is user data and correctly stays English: dashboard and chart titles, dataset column names such as "Fiscal year" and "Sector", filter names, role names (`Admin`, `Gamma`) and the `Yes` of the users-list boolean cells (the `Yes` entry is now translated; if those cells still show English they come from the Flask-AppBuilder catalogue, which ships no `ar`. Not verified).

## 6. Rejected corrections

None. The validator rejects a correction when placeholders differ, when plural forms are not exactly six or contain a placeholder the msgid_plural lacks, when newline or edge spaces differ, and for Arabic-Indic digits; no entry triggered it. Pre-existing, untouched oddity: the two plural entries `%(suggestion)s instead of ...` mix placeholder names between singular and plural; that is how upstream defines them.

## 7. Backend tests added

| File | Covers |
|---|---|
| `tests/unit_tests/translations/text_direction_test.py` | `get_text_direction`: `ar`, `ar_SA`, `ar-EG`, `fa`, `he`, `ur` -> rtl; `en`, `fr`, `zh_TW`, `pt_BR`, `None`, `''`, `not-a-locale` -> ltr; Babel `Locale` objects; `RTL_LAYOUT_ENABLED = False` |
| `tests/unit_tests/views/test_document_direction.py` | `get_document_locale_template_context` (hyphenated `html_lang`, `html_dir` from `common.direction` or derived, defaults, disabled flag) and `direction` in the common bootstrap payload |
| `tests/unit_tests/translations/ar_catalogue_test.py` | catalogue loads, `nplurals=6`, placeholders intact in every entry, reviewed plurals have six forms, Latin digits, the most visible strings pinned, `Applied filters (%s)` |

Run: `pytest tests/unit_tests/translations tests/unit_tests/views/test_document_direction.py` (66 passed in a throwaway container from `nxtbi/superset-fork:local` with the repo mounted read-only, `pip install --target /tmp/p pytest pytest-mock polib`).

## 8. Regenerating the language pack

- Backend `.mo`: built in the image by `Dockerfile` stage `python-translation-compiler` (`pybabel compile --use-fuzzy`), enabled by `BUILD_TRANSLATIONS=true` (`nxtbi/docker-compose.yml`). The `.po` is deleted from the final image.
- Frontend pack: `cd superset-frontend && npm run build-translation` (`po2json` to `ar/LC_MESSAGES/messages.json`, served content-hashed by `/language_pack/ar/<hash>/script.js`). Both outputs are git-ignored and are rebuilt by an image build; browsers pick up the new hash automatically.
- Quick local check without a build: `python -c "from babel.messages.pofile import read_po; read_po(open('superset/translations/ar/LC_MESSAGES/messages.po','rb'), locale='ar')"`.
- Do not run `babel_update.sh` for a wording change: it reflows the file. Run it only when source strings change, then re-apply the appendix.

## 9. After an upstream merge (re-applying mechanically)

Upstream bots rewrite the `ar` catalogue weekly (`backfill-translations.yml`, `babel_update.sh`). To restore this work:

1. Merge or rebase; if `messages.po` conflicts, take upstream's version of the file.
2. For each entry of Appendix A, find the entry by `(msgid, msgid_plural)`, set `msgstr` (or `msgstr[0..5]`), delete `fuzzy` from its flags and delete the `# Machine-translated ...` comment (and its `# ` continuation lines). Keep order and wrapping of everything else; check that `git diff --stat` touches only those entries.
3. Run the normalisation of section 4 on the remaining entries (optional; the rules are four substring replacements gated by `dashboard` / `chart` in the msgid).
4. Validate (section 1 rules), run the three test files of section 7 (the catalogue test fails if a correction is lost or a placeholder breaks).
5. If upstream changed a msgid of the appendix, the entry shows up as missing: re-translate it by the glossary.

The working script is not kept in the repo; it is about 150 lines of stdlib Python (parse the file into blank-line separated blocks, rewrite only the `msgstr` lines and comments of matched blocks, wrap with babel's 76-78 column style). A `polib` variant (`polib.pofile(path, wrapwidth=78)`, `entry.msgstr = ...`, `entry.flags.remove('fuzzy')`) is the route `backfill_po.py` uses, but it was not tested here and may re-wrap the whole file.

## Appendix A. Applied corrections (machine-readable, UTF-8 JSON)

Same format as section 10 of `04-arabic-catalogue.md`: `msgstr_plural` index 0..5 = zero, one, two, few (3-10), many (11-99), other.

```json
[
{"msgid":"Home","msgstr":"الرئيسية"},
{"msgid":"Dashboards","msgstr":"لوحات المعلومات"},
{"msgid":"Dashboard","msgstr":"لوحة المعلومات"},
{"msgid":"Chart","msgstr":"مخطط"},
{"msgid":"SQL Lab","msgstr":"مختبر SQL"},
{"msgid":"Users","msgstr":"المستخدمون"},
{"msgid":"List Users","msgstr":"قائمة المستخدمين"},
{"msgid":"List Roles","msgstr":"قائمة الأدوار"},
{"msgid":"User Registrations","msgstr":"تسجيلات المستخدمين"},
{"msgid":"Themes","msgstr":"السمات"},
{"msgid":"Theme","msgstr":"السمة"},
{"msgid":"Groups","msgstr":"المجموعات"},
{"msgid":"Group","msgstr":"المجموعة"},
{"msgid":"Permissions","msgstr":"الصلاحيات"},
{"msgid":"Extensions","msgstr":"الامتدادات"},
{"msgid":"Languages","msgstr":"اللغات"},
{"msgid":"System","msgstr":"النظام"},
{"msgid":"Manage","msgstr":"إدارة"},
{"msgid":"Mine","msgstr":"الخاصة بي"},
{"msgid":"Edit user","msgstr":"تحرير المستخدم"},
{"msgid":"Email","msgstr":"البريد الإلكتروني"},
{"msgid":"First name","msgstr":"الاسم الأول"},
{"msgid":"First Name","msgstr":"الاسم الأول"},
{"msgid":"Last name","msgstr":"اسم العائلة"},
{"msgid":"Last Name","msgstr":"اسم العائلة"},
{"msgid":"Sign in","msgstr":"تسجيل الدخول"},
{"msgid":"Sign in with","msgstr":"تسجيل الدخول باستخدام"},
{"msgid":"Username:","msgstr":"اسم المستخدم:"},
{"msgid":"Password:","msgstr":"كلمة المرور:"},
{"msgid":"Password","msgstr":"كلمة المرور"},
{"msgid":"Please enter your username","msgstr":"يرجى إدخال اسم المستخدم"},
{"msgid":"Please enter your password","msgstr":"يرجى إدخال كلمة المرور"},
{"msgid":"Please confirm your password","msgstr":"يرجى تأكيد كلمة المرور"},
{"msgid":"Register","msgstr":"تسجيل حساب"},
{"msgid":"Password is required","msgstr":"كلمة المرور مطلوبة"},
{"msgid":"Username is required","msgstr":"اسم المستخدم مطلوب"},
{"msgid":"Email is required","msgstr":"البريد الإلكتروني مطلوب"},
{"msgid":"Passwords do not match!","msgstr":"كلمتا المرور غير متطابقتين!"},
{"msgid":"Enter your login and password below:","msgstr":"أدخل اسم المستخدم وكلمة المرور أدناه:"},
{"msgid":"Save","msgstr":"حفظ"},
{"msgid":"Cancel","msgstr":"إلغاء"},
{"msgid":"Close","msgstr":"إغلاق"},
{"msgid":"Apply","msgstr":"تطبيق"},
{"msgid":"Add","msgstr":"إضافة"},
{"msgid":"Search","msgstr":"بحث"},
{"msgid":"Yes","msgstr":"نعم"},
{"msgid":"No","msgstr":"لا"},
{"msgid":"OK","msgstr":"موافق"},
{"msgid":"Run","msgstr":"تشغيل"},
{"msgid":"Run selection","msgstr":"تشغيل التحديد"},
{"msgid":"Import","msgstr":"استيراد"},
{"msgid":"Share","msgstr":"مشاركة"},
{"msgid":"Create","msgstr":"إنشاء"},
{"msgid":"Clear","msgstr":"مسح"},
{"msgid":"Back","msgstr":"رجوع"},
{"msgid":"Retry","msgstr":"إعادة المحاولة"},
{"msgid":"Confirm","msgstr":"تأكيد"},
{"msgid":"Select","msgstr":"تحديد"},
{"msgid":"Select All","msgstr":"تحديد الكل"},
{"msgid":"Select all","msgstr":"تحديد الكل"},
{"msgid":"Resize","msgstr":"تغيير الحجم"},
{"msgid":"Expand","msgstr":"توسيع"},
{"msgid":"New","msgstr":"جديد"},
{"msgid":"Copied!","msgstr":"تم النسخ!"},
{"msgid":"Copy column name","msgstr":"نسخ اسم العمود"},
{"msgid":"Copy code to clipboard","msgstr":"نسخ الشيفرة إلى الحافظة"},
{"msgid":"You don't have permission to copy to clipboard","msgstr":"ليس لديك صلاحية النسخ إلى الحافظة"},
{"msgid":"Refresh settings","msgstr":"إعدادات التحديث"},
{"msgid":"Refresh table schema","msgstr":"تحديث بنية الجدول"},
{"msgid":"Refresh delayed","msgstr":"تأخر التحديث"},
{"msgid":"Refresh interval set for this session","msgstr":"تم ضبط فاصل التحديث لهذه الجلسة"},
{"msgid":"Refresh dashboard","msgstr":"تحديث لوحة المعلومات"},
{"msgid":"Force refresh","msgstr":"فرض التحديث"},
{"msgid":"Reset Columns","msgstr":"إعادة تعيين الأعمدة"},
{"msgid":"Reset columns","msgstr":"إعادة تعيين الأعمدة"},
{"msgid":"Reset to default folders?","msgstr":"إعادة التعيين إلى المجلدات الافتراضية؟"},
{"msgid":"Fetching data...","msgstr":"جارٍ جلب البيانات..."},
{"msgid":"Fetching","msgstr":"جارٍ الجلب"},
{"msgid":"Loading","msgstr":"جارٍ التحميل"},
{"msgid":"Loading filter values","msgstr":"جارٍ تحميل قيم عامل التصفية"},
{"msgid":"Loading timezones...","msgstr":"جارٍ تحميل المناطق الزمنية..."},
{"msgid":"Clear Sort","msgstr":"إلغاء الفرز"},
{"msgid":"Clear form","msgstr":"مسح النموذج"},
{"msgid":"Search by","msgstr":"بحث حسب"},
{"msgid":"Page","msgstr":"الصفحة"},
{"msgid":"Page Size:","msgstr":"حجم الصفحة:"},
{"msgid":"Page navigation","msgstr":"التنقل بين الصفحات"},
{"msgid":"Summary","msgstr":"الملخص"},
{"msgid":"Download to client","msgstr":"تنزيل إلى الجهاز"},
{"msgid":"Upload Excel to database","msgstr":"رفع ملف Excel إلى قاعدة البيانات"},
{"msgid":"Upload CSV to database","msgstr":"رفع ملف CSV إلى قاعدة البيانات"},
{"msgid":"Filters","msgstr":"عوامل التصفية"},
{"msgid":"Apply filters","msgstr":"تطبيق عوامل التصفية"},
{"msgid":"Filters and controls","msgstr":"عوامل التصفية وعناصر التحكم"},
{"msgid":"Add filter","msgstr":"إضافة عامل تصفية"},
{"msgid":"Clear all filters","msgstr":"مسح كل عوامل التصفية"},
{"msgid":"No filter","msgstr":"بدون عامل تصفية"},
{"msgid":"No filters","msgstr":"لا توجد عوامل تصفية"},
{"msgid":"No applied filters","msgstr":"لا توجد عوامل تصفية مطبقة"},
{"msgid":"No items","msgstr":"لا توجد عناصر"},
{"msgid":"Filter Type","msgstr":"نوع عامل التصفية"},
{"msgid":"Filter type","msgstr":"نوع عامل التصفية"},
{"msgid":"Filter value is required","msgstr":"قيمة عامل التصفية مطلوبة"},
{"msgid":"Filter charts","msgstr":"تصفية المخططات"},
{"msgid":"Filter options","msgstr":"خيارات التصفية"},
{"msgid":"Cross-filters","msgstr":"عوامل التصفية المتقاطعة"},
{"msgid":"Filters out of scope (%d)","msgstr":"عوامل التصفية خارج النطاق (%d)"},
{"msgid":"Customizations out of scope (%d)","msgstr":"التخصيصات خارج النطاق (%d)"},
{"msgid":"Filter value (case sensitive)","msgstr":"قيمة عامل التصفية (حساسة لحالة الأحرف)"},
{"msgid":"Sort filter values","msgstr":"فرز قيم عامل التصفية"},
{"msgid":"Pre-filter available values","msgstr":"تصفية مسبقة للقيم المتاحة"},
{"msgid":"Edit dashboard","msgstr":"تحرير لوحة المعلومات"},
{"msgid":"Edit Dashboard","msgstr":"تحرير لوحة المعلومات"},
{"msgid":"Show Dashboard","msgstr":"عرض لوحة المعلومات"},
{"msgid":"You do not have permission to edit this dashboard","msgstr":"ليس لديك صلاحية تحرير لوحة المعلومات هذه"},
{"msgid":"You do not have permissions to edit this dashboard.","msgstr":"ليس لديك صلاحية تحرير لوحة المعلومات هذه."},
{"msgid":"You don't have access to this dashboard.","msgstr":"ليس لديك صلاحية الوصول إلى لوحة المعلومات هذه."},
{"msgid":"Sorry, there was an error saving this dashboard: %s","msgstr":"عذرًا، حدث خطأ أثناء حفظ لوحة المعلومات: %s"},
{"msgid":"Dashboard %(dashboard_id)s not found","msgstr":"لم يتم العثور على لوحة المعلومات %(dashboard_id)s"},
{"msgid":"Chart Options","msgstr":"خيارات المخطط"},
{"msgid":"Chart options","msgstr":"خيارات المخطط"},
{"msgid":"Chart Title","msgstr":"عنوان المخطط"},
{"msgid":"Chart ID","msgstr":"معرّف المخطط"},
{"msgid":"Chart Orientation","msgstr":"اتجاه المخطط"},
{"msgid":"Select chart","msgstr":"اختيار مخطط"},
{"msgid":"All charts","msgstr":"جميع المخططات"},
{"msgid":"Chart not found","msgstr":"لم يتم العثور على المخطط"},
{"msgid":"Chart %(id)s not found","msgstr":"لم يتم العثور على المخطط %(id)s"},
{"msgid":"The id of the active chart","msgstr":"معرّف المخطط النشط"},
{"msgid":"Whether to display a legend for the chart","msgstr":"ما إذا كان سيتم عرض وسيلة الإيضاح للمخطط"},
{"msgid":"Legend","msgstr":"وسيلة الإيضاح"},
{"msgid":"Show legend","msgstr":"عرض وسيلة الإيضاح"},
{"msgid":"Labels","msgstr":"التسميات"},
{"msgid":"Show Labels","msgstr":"عرض التسميات"},
{"msgid":"Label","msgstr":"التسمية"},
{"msgid":"Whether to display the labels.","msgstr":"ما إذا كان سيتم عرض التسميات."},
{"msgid":"Metric","msgstr":"المقياس"},
{"msgid":"metric","msgstr":"مقياس"},
{"msgid":"Table","msgstr":"جدول"},
{"msgid":"Table V2","msgstr":"جدول V2"},
{"msgid":"Group by","msgstr":"تجميع حسب"},
{"msgid":"Group By","msgstr":"تجميع حسب"},
{"msgid":"Time","msgstr":"الوقت"},
{"msgid":"Time grain","msgstr":"الدقة الزمنية"},
{"msgid":"Time shift","msgstr":"الإزاحة الزمنية"},
{"msgid":"Time Shift","msgstr":"الإزاحة الزمنية"},
{"msgid":"Limit","msgstr":"الحد"},
{"msgid":"Count","msgstr":"العدد"},
{"msgid":"Average","msgstr":"المتوسط"},
{"msgid":"mean","msgstr":"المتوسط"},
{"msgid":"std","msgstr":"الانحراف المعياري"},
{"msgid":"min","msgstr":"الحد الأدنى"},
{"msgid":"Min","msgstr":"الحد الأدنى"},
{"msgid":"cumsum","msgstr":"المجموع التراكمي"},
{"msgid":"Main","msgstr":"الرئيسي"},
{"msgid":"Featured","msgstr":"مميز"},
{"msgid":"Created","msgstr":"تاريخ الإنشاء"},
{"msgid":"Category","msgstr":"الفئة"},
{"msgid":"Categorical","msgstr":"فئوي"},
{"msgid":"Categorical palette","msgstr":"لوحة ألوان فئوية"},
{"msgid":"Custom color palettes","msgstr":"لوحات ألوان مخصصة"},
{"msgid":"Subcategories","msgstr":"الفئات الفرعية"},
{"msgid":"Custom","msgstr":"مخصص"},
{"msgid":"General","msgstr":"عام"},
{"msgid":"General information","msgstr":"معلومات عامة"},
{"msgid":"Inside","msgstr":"داخل"},
{"msgid":"Extent","msgstr":"المدى"},
{"msgid":"to","msgstr":"إلى"},
{"msgid":"Top","msgstr":"أعلى"},
{"msgid":"Bottom","msgstr":"أسفل"},
{"msgid":"Right","msgstr":"اليمين"},
{"msgid":"Business","msgstr":"الأعمال"},
{"msgid":"deckGL","msgstr":"deck.gl"},
{"msgid":"ECharts","msgstr":"ECharts"},
{"msgid":"Actions","msgstr":"الإجراءات"},
{"msgid":"Bar","msgstr":"شريط"},
{"msgid":"Marker","msgstr":"علامة"},
{"msgid":"Report","msgstr":"تقرير"},
{"msgid":"report","msgstr":"تقرير"},
{"msgid":"Schedule","msgstr":"الجدولة"},
{"msgid":"Schedule type","msgstr":"نوع الجدولة"},
{"msgid":"Schedule query","msgstr":"جدولة الاستعلام"},
{"msgid":"Current day","msgstr":"اليوم الحالي"},
{"msgid":"Current month","msgstr":"الشهر الحالي"},
{"msgid":"Current week","msgstr":"الأسبوع الحالي"},
{"msgid":"previous calendar quarter","msgstr":"الربع التقويمي السابق"},
{"msgid":"Series settings","msgstr":"إعدادات السلسلة"},
{"msgid":"Height of each row in pixels","msgstr":"ارتفاع كل صف بالبكسل"},
{"msgid":"Row height","msgstr":"ارتفاع الصف"},
{"msgid":"Charts per row","msgstr":"عدد المخططات في كل صف"},
{"msgid":"Fit columns dynamically","msgstr":"ملاءمة الأعمدة ديناميكيًا"},
{"msgid":"Display all","msgstr":"عرض الكل"},
{"msgid":"Show cell bars for all columns","msgstr":"عرض أشرطة الخلايا لجميع الأعمدة"},
{"msgid":"Align +/- for all columns","msgstr":"محاذاة +/- لجميع الأعمدة"},
{"msgid":"Basic conditional formatting","msgstr":"تنسيق شرطي أساسي"},
{"msgid":"Custom conditional formatting","msgstr":"تنسيق شرطي مخصص"},
{"msgid":"Visual formatting","msgstr":"تنسيق مرئي"},
{"msgid":"entire row","msgstr":"الصف بأكمله"},
{"msgid":"Percentage metric calculation","msgstr":"حساب مقياس النسبة المئوية"},
{"msgid":"All records","msgstr":"كل السجلات"},
{"msgid":"CSV Export","msgstr":"تصدير CSV"},
{"msgid":"color type","msgstr":"نوع اللون"},
{"msgid":"Decrease label","msgstr":"تسمية الانخفاض"},
{"msgid":"Increase label","msgstr":"تسمية الزيادة"},
{"msgid":"Increase color","msgstr":"لون الزيادة"},
{"msgid":"Decrease color","msgstr":"لون الانخفاض"},
{"msgid":"Decrease","msgstr":"انخفاض"},
{"msgid":"Schema","msgstr":"سكيما"},
{"msgid":"Select schema","msgstr":"اختيار السكيما"},
{"msgid":"Select database","msgstr":"اختيار قاعدة البيانات"},
{"msgid":"Select Database and Schema","msgstr":"اختيار قاعدة البيانات والسكيما"},
{"msgid":"Schema cache timeout","msgstr":"مهلة التخزين المؤقت للسكيما"},
{"msgid":"Schemas allowed for File upload","msgstr":"السكيمات المسموح بها لرفع الملفات"},
{"msgid":"Schema not found.","msgstr":"لم يتم العثور على السكيما."},
{"msgid":"There was an error loading the schemas","msgstr":"حدث خطأ أثناء تحميل السكيمات"},
{"msgid":"Format","msgstr":"تنسيق"},
{"msgid":"Format SQL","msgstr":"تنسيق SQL"},
{"msgid":"Format SQL query","msgstr":"تنسيق استعلام SQL"},
{"msgid":"Format JSON configuration","msgstr":"تنسيق إعدادات JSON"},
{"msgid":"formatted","msgstr":"منسق"},
{"msgid":"Show SQL","msgstr":"عرض SQL"},
{"msgid":"Show Log","msgstr":"عرض السجل"},
{"msgid":"Show Bubbles","msgstr":"عرض الفقاعات"},
{"msgid":"Table or View \"%(table)s\" does not exist.","msgstr":"الجدول أو العرض \"%(table)s\" غير موجود."},
{"msgid":"There was an error creating the group. Please, try again.","msgstr":"حدث خطأ أثناء إنشاء المجموعة. يرجى المحاولة مرة أخرى."},
{"msgid":"There was an error creating the role. Please, try again.","msgstr":"حدث خطأ أثناء إنشاء الدور. يرجى المحاولة مرة أخرى."},
{"msgid":"There was an error creating the user. Please, try again.","msgstr":"حدث خطأ أثناء إنشاء المستخدم. يرجى المحاولة مرة أخرى."},
{"msgid":"There was an error duplicating the role. Please, try again.","msgstr":"حدث خطأ أثناء تكرار الدور. يرجى المحاولة مرة أخرى."},
{"msgid":"There was an error loading groups.","msgstr":"حدث خطأ أثناء تحميل المجموعات."},
{"msgid":"There was an error loading permissions.","msgstr":"حدث خطأ أثناء تحميل الصلاحيات."},
{"msgid":"There was an error loading the catalogs","msgstr":"حدث خطأ أثناء تحميل الكتالوجات"},
{"msgid":"There was an error fetching the filtered charts and dashboards:","msgstr":"حدث خطأ أثناء جلب المخططات ولوحات المعلومات المصفّاة:"},
{"msgid":"An error occurred while accessing the copy link.","msgstr":"حدث خطأ أثناء الوصول إلى رابط النسخ."},
{"msgid":"An error occurred while creating the copy link.","msgstr":"حدث خطأ أثناء إنشاء رابط النسخ."},
{"msgid":"You do not have permission to perform this operation","msgstr":"ليس لديك صلاحية تنفيذ هذه العملية"},
{"msgid":"You don't have permission to export data","msgstr":"ليس لديك صلاحية تصدير البيانات"},
{"msgid":"You don't have permission to export images","msgstr":"ليس لديك صلاحية تصدير الصور"},
{"msgid":"You do not have permission to edit this chart","msgstr":"ليس لديك صلاحية تحرير هذا المخطط"},
{"msgid":"You do not have sufficient permissions to edit the chart","msgstr":"ليس لديك صلاحيات كافية لتحرير المخطط"},
{"msgid":"You don't have access to this chart.","msgstr":"ليس لديك صلاحية الوصول إلى هذا المخطط."},
{"msgid":"You don't have access to this dataset.","msgstr":"ليس لديك صلاحية الوصول إلى مجموعة البيانات هذه."},
{"msgid":"You don't have access to this semantic view.","msgstr":"ليس لديك صلاحية الوصول إلى هذا العرض الدلالي."},
{"msgid":"You don't have permission to access this resource.","msgstr":"ليس لديك صلاحية الوصول إلى هذا المورد."},
{"msgid":"Sorry, something went wrong. Try again later.","msgstr":"عذرًا، حدث خطأ ما. حاول مرة أخرى لاحقًا."},
{"msgid":"Sorry, something went wrong. Please try again.","msgstr":"عذرًا، حدث خطأ ما. يرجى المحاولة مرة أخرى."},
{"msgid":"Sorry, something went wrong. Embedding could not be deactivated.","msgstr":"عذرًا، حدث خطأ ما. تعذّر إلغاء تفعيل التضمين."},
{"msgid":"Forbidden","msgstr":"محظور"},
{"msgid":"Alert is active","msgstr":"التنبيه نشط"},
{"msgid":"Alert contents","msgstr":"محتويات التنبيه"},
{"msgid":"Send as PDF","msgstr":"إرسال بصيغة PDF"},
{"msgid":"Report Schedule execution failed when generating a pdf.","msgstr":"فشل تنفيذ جدول التقرير عند إنشاء ملف pdf."},
{"msgid":"recipients","msgstr":"المستلمون"},
{"msgid":"email subject","msgstr":"موضوع البريد الإلكتروني"},
{"msgid":"crontab","msgstr":"crontab"},
{"msgid":"No groups yet","msgstr":"لا توجد مجموعات بعد"},
{"msgid":"No roles yet","msgstr":"لا توجد أدوار بعد"},
{"msgid":"No user registrations yet","msgstr":"لا توجد تسجيلات مستخدمين بعد"},
{"msgid":"No users yet","msgstr":"لا يوجد مستخدمون بعد"},
{"msgid":"Auto-detect","msgstr":"اكتشاف تلقائي"},
{"msgid":"Automatically sync columns","msgstr":"مزامنة الأعمدة تلقائيًا"},
{"msgid":"Autosize All Columns","msgstr":"ضبط حجم جميع الأعمدة تلقائيًا"},
{"msgid":"Autosize all columns","msgstr":"ضبط حجم جميع الأعمدة تلقائيًا"},
{"msgid":"Autosize Column","msgstr":"ضبط حجم العمود تلقائيًا"},
{"msgid":"Autosize This Column","msgstr":"ضبط حجم هذا العمود تلقائيًا"},
{"msgid":"auto","msgstr":"تلقائي"},
{"msgid":"Clear default dark theme","msgstr":"مسح السمة الداكنة الافتراضية"},
{"msgid":"Clear local theme","msgstr":"مسح السمة المحلية"},
{"msgid":"Reset and reselect values","msgstr":"إعادة التعيين وإعادة تحديد القيم"},
{"msgid":"%s row","msgid_plural":"%s rows","msgstr_plural":["%s صف","%s صف","%s صفان","%s صفوف","%s صفًا","%s صف"]},
{"msgid":"%s column","msgid_plural":"%s columns","msgstr_plural":["%s عمود","%s عمود","%s عمودان","%s أعمدة","%s عمودًا","%s عمود"]},
{"msgid":"%s item","msgid_plural":"%s items","msgstr_plural":["%s عنصر","%s عنصر","%s عنصران","%s عناصر","%s عنصرًا","%s عنصر"]},
{"msgid":"%s option","msgid_plural":"%s options","msgstr_plural":["%s خيار","%s خيار","%s خياران","%s خيارات","%s خيارًا","%s خيار"]},
{"msgid":"%s metric","msgid_plural":"%s metrics","msgstr_plural":["%s مقياس","%s مقياس","%s مقياسان","%s مقاييس","%s مقياسًا","%s مقياس"]},
{"msgid":"%s out of %s column","msgid_plural":"%s out of %s columns","msgstr_plural":["%s من %s عمود","%s من %s عمود","%s من %s عمودين","%s من %s أعمدة","%s من %s عمودًا","%s من %s عمود"]},
{"msgid":"%s out of %s metric","msgid_plural":"%s out of %s metrics","msgstr_plural":["%s من %s مقياس","%s من %s مقياس","%s من %s مقياسين","%s من %s مقاييس","%s من %s مقياسًا","%s من %s مقياس"]},
{"msgid":"%s record...","msgid_plural":"%s records...","msgstr_plural":["%s سجل...","%s سجل...","%s سجلان...","%s سجلات...","%s سجلًا...","%s سجل..."]},
{"msgid":"%s second","msgid_plural":"%s seconds","msgstr_plural":["%s ثانية","%s ثانية","%s ثانيتان","%s ثوانٍ","%s ثانية","%s ثانية"]},
{"msgid":"%s s ago","msgid_plural":"%s s ago","msgstr_plural":["منذ %s ث","منذ %s ث","منذ %s ث","منذ %s ث","منذ %s ث","منذ %s ث"]},
{"msgid":"%s min ago","msgid_plural":"%s min ago","msgstr_plural":["منذ %s د","منذ %s د","منذ %s د","منذ %s د","منذ %s د","منذ %s د"]},
{"msgid":"%s hr ago","msgid_plural":"%s hr ago","msgstr_plural":["منذ %s س","منذ %s س","منذ %s س","منذ %s س","منذ %s س","منذ %s س"]},
{"msgid":"%s day ago","msgid_plural":"%s days ago","msgstr_plural":["منذ %s يوم","منذ %s يوم","منذ %s يومين","منذ %s أيام","منذ %s يومًا","منذ %s يوم"]},
{"msgid":"Deleted %(num)d chart","msgid_plural":"Deleted %(num)d charts","msgstr_plural":["تم حذف %(num)d مخطط","تم حذف %(num)d مخطط","تم حذف %(num)d مخططين","تم حذف %(num)d مخططات","تم حذف %(num)d مخططًا","تم حذف %(num)d مخطط"]},
{"msgid":"Deleted %(num)d dashboard","msgid_plural":"Deleted %(num)d dashboards","msgstr_plural":["تم حذف %(num)d لوحة معلومات","تم حذف %(num)d لوحة معلومات","تم حذف %(num)d لوحتي معلومات","تم حذف %(num)d لوحات معلومات","تم حذف %(num)d لوحة معلومات","تم حذف %(num)d لوحة معلومات"]},
{"msgid":"Deleted %(num)d dataset","msgid_plural":"Deleted %(num)d datasets","msgstr_plural":["تم حذف %(num)d مجموعة بيانات","تم حذف %(num)d مجموعة بيانات","تم حذف %(num)d مجموعتي بيانات","تم حذف %(num)d مجموعات بيانات","تم حذف %(num)d مجموعة بيانات","تم حذف %(num)d مجموعة بيانات"]},
{"msgid":"Deleted %(num)d annotation","msgid_plural":"Deleted %(num)d annotations","msgstr_plural":["تم حذف %(num)d تعليق توضيحي","تم حذف %(num)d تعليق توضيحي","تم حذف %(num)d تعليقين توضيحيين","تم حذف %(num)d تعليقات توضيحية","تم حذف %(num)d تعليقًا توضيحيًا","تم حذف %(num)d تعليق توضيحي"]},
{"msgid":"Deleted %(num)d annotation layer","msgid_plural":"Deleted %(num)d annotation layers","msgstr_plural":["تم حذف %(num)d طبقة تعليقات توضيحية","تم حذف %(num)d طبقة تعليقات توضيحية","تم حذف %(num)d طبقتي تعليقات توضيحية","تم حذف %(num)d طبقات تعليقات توضيحية","تم حذف %(num)d طبقة تعليقات توضيحية","تم حذف %(num)d طبقة تعليقات توضيحية"]},
{"msgid":"Deleted %(num)d css template","msgid_plural":"Deleted %(num)d css templates","msgstr_plural":["تم حذف %(num)d قالب CSS","تم حذف %(num)d قالب CSS","تم حذف %(num)d قالبي CSS","تم حذف %(num)d قوالب CSS","تم حذف %(num)d قالب CSS","تم حذف %(num)d قالب CSS"]},
{"msgid":"Deleted %(num)d report schedule","msgid_plural":"Deleted %(num)d report schedules","msgstr_plural":["تم حذف %(num)d جدولة تقرير","تم حذف %(num)d جدولة تقرير","تم حذف %(num)d جدولتي تقرير","تم حذف %(num)d جدولات تقارير","تم حذف %(num)d جدولة تقرير","تم حذف %(num)d جدولة تقرير"]},
{"msgid":"Deleted %(num)d saved query","msgid_plural":"Deleted %(num)d saved queries","msgstr_plural":["تم حذف %(num)d استعلام محفوظ","تم حذف %(num)d استعلام محفوظ","تم حذف %(num)d استعلامين محفوظين","تم حذف %(num)d استعلامات محفوظة","تم حذف %(num)d استعلامًا محفوظًا","تم حذف %(num)d استعلام محفوظ"]},
{"msgid":"Deleted %(num)d theme","msgid_plural":"Deleted %(num)d themes","msgstr_plural":["تم حذف %(num)d سمة","تم حذف %(num)d سمة","تم حذف %(num)d سمتين","تم حذف %(num)d سمات","تم حذف %(num)d سمة","تم حذف %(num)d سمة"]},
{"msgid":"Applied filters (%s)","msgstr":"عوامل التصفية المطبقة (%s)"},
{"msgid":"Invalid temporal filter value for column %(column)s","msgstr":"قيمة عامل تصفية زمني غير صالحة للعمود %(column)s"},
{"msgid":"Creator","msgstr":"المنشئ"},
{"msgid":"Duplicate","msgstr":"تكرار"},
{"msgid":"Done","msgstr":"تم"},
{"msgid":"Saved","msgstr":"محفوظ"},
{"msgid":"Columns","msgstr":"الأعمدة"},
{"msgid":"Bulk select","msgstr":"تحديد جماعي"},
{"msgid":"Add to dashboard","msgstr":"إضافة إلى لوحة المعلومات"},
{"msgid":"Save & go to dashboard","msgstr":"حفظ والانتقال إلى لوحة المعلومات"},
{"msgid":"Light","msgstr":"فاتح"},
{"msgid":"About","msgstr":"حول"},
{"msgid":"Is active?","msgstr":"نشط؟"},
{"msgid":"Last login","msgstr":"آخر تسجيل دخول"},
{"msgid":"Login count","msgstr":"عدد مرات تسجيل الدخول"},
{"msgid":"Changed on","msgstr":"تاريخ التعديل"},
{"msgid":"Created on","msgstr":"تاريخ الإنشاء"},
{"msgid":"Chart Type","msgstr":"نوع المخطط"},
{"msgid":"Viz type","msgstr":"نوع التصور"},
{"msgid":"Datasource is required","msgstr":"مصدر البيانات مطلوب"},
{"msgid":"Datasource is required for validation","msgstr":"مصدر البيانات مطلوب للتحقق"},
{"msgid":"Datasources","msgstr":"مصادر البيانات"},
{"msgid":"There is currently no information to display.","msgstr":"لا توجد معلومات لعرضها حاليًا."},
{"msgid":"No %s yet","msgstr":"لا توجد %s بعد"},
{"msgid":"Select a schema","msgstr":"حدد السكيما"},
{"msgid":"Select a semantic layer","msgstr":"حدد طبقة دلالية"},
{"msgid":"Select a semantic layer type","msgstr":"حدد نوع الطبقة الدلالية"},
{"msgid":"Select a theme","msgstr":"حدد سمة"},
{"msgid":"Select a tab","msgstr":"حدد علامة تبويب"},
{"msgid":"Select a database","msgstr":"حدد قاعدة بيانات"},
{"msgid":"Select a sheet name from the uploaded file","msgstr":"حدد اسم الورقة من الملف المرفوع"},
{"msgid":"Select a CSS template","msgstr":"حدد قالب CSS"},
{"msgid":"Select a linear color scheme","msgstr":"حدد نظام ألوان خطي"},
{"msgid":"Select a predefined CSS template to apply to your dashboard","msgstr":"حدد قالب CSS معرّفًا مسبقًا لتطبيقه على لوحة المعلومات"},
{"msgid":"Filter your charts","msgstr":"تصفية المخططات"},
{"msgid":"Show only my charts","msgstr":"عرض المخططات الخاصة بي فقط"},
{"msgid":"View all charts","msgstr":"عرض جميع المخططات"},
{"msgid":"Whether to populate autocomplete filters options","msgstr":"ما إذا كان سيتم ملء خيارات عوامل التصفية للإكمال التلقائي"},
{"msgid":"Failed to copy API key to clipboard","msgstr":"فشل نسخ مفتاح API إلى الحافظة"},
{"msgid":"Failed to copy stack trace to clipboard","msgstr":"فشل نسخ تتبع المكدس إلى الحافظة"},
{"msgid":"Failed to create API key","msgstr":"فشل إنشاء مفتاح API"},
{"msgid":"Failed to fetch API keys","msgstr":"فشل جلب مفاتيح API"},
{"msgid":"Failed to remove system default theme: %s","msgstr":"فشل إزالة السمة الافتراضية للنظام: %s"},
{"msgid":"Failed to set system default theme: %s","msgstr":"فشل تعيين السمة الافتراضية للنظام: %s"},
{"msgid":"Failed to remove system dark theme: %s","msgstr":"فشل إزالة السمة الداكنة للنظام: %s"},
{"msgid":"Failed to set system dark theme: %s","msgstr":"فشل تعيين السمة الداكنة للنظام: %s"},
{"msgid":"Failed to apply theme: Invalid JSON","msgstr":"فشل تطبيق السمة: JSON غير صالح"},
{"msgid":"Failed to set local theme: Invalid JSON configuration","msgstr":"فشل تعيين السمة المحلية: إعدادات JSON غير صالحة"},
{"msgid":"Failed to save chart customization","msgstr":"فشل حفظ تخصيص المخطط"},
{"msgid":"Failed to save cross-filters setting","msgstr":"فشل حفظ إعداد عوامل التصفية المتقاطعة"},
{"msgid":"Failed to save cross-filter scoping","msgstr":"فشل حفظ نطاق عوامل التصفية المتقاطعة"},
{"msgid":"Drop a column here or click","msgid_plural":"Drop columns here or click","msgstr_plural":["قم بإسقاط الأعمدة هنا أو انقر","قم بإسقاط عمود هنا أو انقر","قم بإسقاط الأعمدة هنا أو انقر","قم بإسقاط الأعمدة هنا أو انقر","قم بإسقاط الأعمدة هنا أو انقر","قم بإسقاط الأعمدة هنا أو انقر"]},
{"msgid":"Drop a column/metric here or click","msgid_plural":"Drop columns/metrics here or click","msgstr_plural":["قم بإسقاط الأعمدة/المقاييس هنا أو انقر","قم بإسقاط عمود/مقياس هنا أو انقر","قم بإسقاط الأعمدة/المقاييس هنا أو انقر","قم بإسقاط الأعمدة/المقاييس هنا أو انقر","قم بإسقاط الأعمدة/المقاييس هنا أو انقر","قم بإسقاط الأعمدة/المقاييس هنا أو انقر"]},
{"msgid":"Added to 1 dashboard","msgid_plural":"Added to %s dashboards","msgstr_plural":["لم تتم الإضافة إلى أي لوحة معلومات","تمت الإضافة إلى لوحة معلومات واحدة","تمت الإضافة إلى لوحتي معلومات","تمت الإضافة إلى %s لوحات معلومات","تمت الإضافة إلى %s لوحة معلومات","تمت الإضافة إلى %s لوحة معلومات"]},
{"msgid":"This was triggered by:","msgid_plural":"This may be triggered by:","msgstr_plural":["قد يتم تشغيل هذا من خلال:","تم تشغيل هذا من خلال:","قد يتم تشغيل هذا من خلال:","قد يتم تشغيل هذا من خلال:","قد يتم تشغيل هذا من خلال:","قد يتم تشغيل هذا من خلال:"]}
]
```
