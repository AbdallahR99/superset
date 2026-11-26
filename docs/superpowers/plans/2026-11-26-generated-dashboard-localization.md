# Generated dashboard localization implementation plan

**Goal**

A Copilot author can choose the dashboard format and source language, preview and edit captions in English and Arabic, and save one dashboard. Readers use the Superset language menu to switch localized captions and layout direction on the same dashboard.

**Design**

Keep a single proposal with typed, optional `dashboardType`, `contentLocale` and `titleTranslations`. Store alternate captions beside their canonical source text so a later source edit falls back to the current authored value. Data references, values, SQL, and filter operands remain canonical in every language. Follow the application locale in the saved dashboard. The preview sets `lang` and `dir` on its own content. [W3C language and direction](https://www.w3.org/International/questions/qa-html-dir.en.html)

- [x] Extend Copilot agent draft and gateway contracts with bounded English and Arabic captions. Localize the deterministic upload and snapshot captions. Ask the model to supply both captions for a custom draft. Verify the same query references and filters across variants.
- [x] Compile Classic (V1) proposals with native chart and dashboard commands in one transaction. Use the saved dashboard UUID for idempotency, preserve actor permissions and validate format-bound approvals. Render V1 captions through the existing dashboard and chart title surfaces.
- [x] Store V2 captions on the grid root by stable node ID. Resolve captions for readers and retain original authoring fields for edits. Use the normal Superset direction provider and rendering infrastructure.
- [x] Add Copilot format and source language controls and a caption preview/editor. Validate exact classic and V2 paths for approved dashboards and transcripts. Keep draft edits intact during language switching.
- [x] Run agent and gateway tests, frontend tests, extension type checking and a disposable Chromium lifecycle from CSV through opening both saved formats under both languages. Use the same dataset and verify values and direction for both locales.

**Limits**

The first locales are English and Arabic. Dates, names and dimension values that originate in the dataset retain their source representation. The dashboard author can review generated captions and fill in untranslated names. Existing dashboards keep their normal rendering and saves. No schema migration is needed.
