# 06 - BI feature inventory and dashboards-as-code (apache/superset master @ f3f3d10d5c, after 7.0.0rc2)

Labels: VERIFIED-IN-CODE (V), DOCS-CLAIMED (D), UNVERIFIED (U). Paths are repo-relative; `FE` = `superset-frontend`.
Lifecycle comes from the `@lifecycle` comments in `superset/config.py` `DEFAULT_FEATURE_FLAGS` (config.py:724-1092) unless stated.

## 1. Chart catalogue (all registered in `FE/src/visualizations/presets/MainPreset.ts:80-205`, keys from `FE/packages/superset-ui-core/src/chart/types/VizType.ts:19-70`)
Min form_data below = what must be in `params` for the chart to render. Every chart also needs: `viz_type`, `adhoc_filters` (may be `[]`; UI writes a `TEMPORAL_RANGE` "No filter" entry), `row_limit`. The importer overwrites `params.datasource` itself (`superset/commands/utils.py:392-393`) so omit it. Metrics may be a saved-metric name string (`"count"`, V: examples/featured_charts/charts/Pie.yaml) or an ad-hoc object (`{expressionType: SQL, sqlExpression, label}` or `{expressionType: SIMPLE, aggregate, column:{column_name}, label}`).

| viz_type | Renderer | Min form_data (besides common) | Status |
|---|---|---|---|
| echarts_timeseries_bar / _line / _scatter / _smooth / _step, echarts_area, echarts_timeseries | ECharts | `x_axis` (time OR categorical column), `metrics[]`, optional `groupby[]`, `time_grain_sqla` (P1D,P1M,P3M...) when x is temporal, `orientation`, `stack`, `show_legend` | STABLE |
| mixed_timeseries | ECharts | `x_axis`, `metrics[]`, `metrics_b[]`, `seriesType`, `seriesTypeB`, `groupby`/`groupby_b`, `adhoc_filters_b`, `yAxisIndex(B)` (V: featured_charts/charts/Mixed.yaml) | STABLE |
| pie | ECharts | `groupby[]`, `metric` (singular) | STABLE |
| big_number_total | ECharts | `metric` | STABLE |
| big_number (with trendline) | ECharts | `metric`, `x_axis` (temporal), `time_grain_sqla`, `show_trend_line` | STABLE |
| pop_kpi (Big Number period-over-period) | ECharts | metric + time comparison | EXPERIMENTAL: only if `CHART_PLUGINS_EXPERIMENTAL` (config.py:747; MainPreset.ts:96-103) |
| table | AG-less classic | `query_mode: aggregate` -> `groupby[]`+`metrics[]`; `query_mode: raw` -> `all_columns[]`; has `conditional_formatting` (plugin-chart-table controlPanel.tsx:883), `server_pagination` | STABLE |
| ag-grid-table | AG Grid | same as table | EXPERIMENTAL: `AG_GRID_TABLE_ENABLED` is `@lifecycle: development` (config.py:733). Do not use |
| pivot_table_v2 | own plugin | `groupbyRows[]`, `groupbyColumns[]`, `metrics[]`, `aggregateFunction`, `metricsLayout` | STABLE |
| handlebars | own plugin | `query_mode`, `handlebarsTemplate` (+ metrics/groupby or all_columns); doc docs/docs/using-superset/handlebars-chart.mdx | STABLE; HTML sanitised by `HTML_SANITIZATION=True` (config.py:1679) |
| time_table | legacy src/visualizations/TimeTable | `groupby`, `metrics`, time column | legacy renderer |
| heatmap_v2 | ECharts | `x_axis`, `groupby` (y, single col), `metric`, `normalize_across` | STABLE |
| histogram_v2 | ECharts | `column`, `bins`, optional `groupby[]`, `normalize` | STABLE |
| box_plot | ECharts | `columns[]` (distribute across), `groupby[]`, `metrics[]`, `whiskerOptions` | STABLE |
| bubble_v2 | ECharts | `entity`, `x`, `y`, `size` (each a metric), optional `series`, `max_bubble_size` | STABLE (legacy nvd3 `bubble` auto-migrated, UPDATING.md:2320) |
| funnel / gauge_chart | ECharts | `groupby[]`, `metric` | STABLE |
| treemap_v2, sunburst_v2 | ECharts | treemap: `groupby[]`,`metric`; sunburst: `columns[]` (hierarchy),`metric` | STABLE |
| sankey_v2 | ECharts | `source`, `target`, `metric` | STABLE |
| radar | ECharts | `groupby[]`, `metrics[]` (>=3 for shape) | STABLE |
| waterfall | ECharts | `x_axis`, `metric`, optional `groupby`, `time_grain_sqla` | STABLE |
| graph_chart | ECharts | `source`, `target`, `metric` | STABLE |
| tree_chart | ECharts | `id`, `parent`, `name`, `metric`, `root_node_id` | STABLE |
| gantt_chart | ECharts | `start_time`, `end_time`, `series`, `y_axis` | STABLE |
| rose | ECharts | `metrics[]`, `groupby[]`, `x_axis` temporal | STABLE |
| time_pivot | ECharts | `x_axis`, `metric`, `freq` | STABLE |
| bullet | ECharts | `groupby[]`, `metric` + range/target controls (in 6.0.0 enum, not new) | STABLE |
| butterfly, candlestick | ECharts | butterfly: `groupby[]`, `left_metric`, `right_metric`; candlestick: `x_axis`,`open`,`high`,`low`,`close` metrics | NEW since 6.0.0 (enum diff `git show 6.0.0:...VizType.ts`); STABLE by flags (no gate) |
| cal_heatmap, chord, horizon, para, paired_ttest, partition, word_cloud, world_map, country_map | d3 / non-ECharts legacy renderers | cal_heatmap: `metrics`,`domain_granularity`,`subdomain_granularity`; chord: `groupby`,`columns`,`metric`; word_cloud: `series`,`metric`; world_map: `entity`,`country_fieldtype`,`metric`; country_map: `select_country`,`entity`,`metric` | STABLE (legacy pipeline migrated to QueryContext, UPDATING.md:2320) |
| point_cluster_map | own plugin | spatial lat/long cols | NEW since 6.0.0 enum |
| cartodiagram | OpenLayers | `selected_chart`, layer config; default OSM WMS layer (MainPreset.ts:182-196, needs browser internet) | STABLE |
| deck_scatter, deck_arc, deck_grid, deck_hex, deck_heatmap, deck_screengrid, deck_path, deck_polygon, deck_geojson, deck_contour, deck_multi | deck.gl | `spatial` (lonlat/delimited/geohash), `viewport`, `mapbox_style`; examples use OSM raster tiles `https://tile.openstreetmap.org/{z}/{x}/{y}.png` so no key (V: examples/deckgl_demo/charts/*.yaml); `MAPBOX_API_KEY` env read at config.py:1883 | STABLE; JS tooltip/data-mutator controls removed (UPDATING.md:2213) |
| `compare`, `mapbox`, `bubble` | none | enum entries only, not registered | REMOVED/migrated |

Cross-filter capable (`Behavior.InteractiveChart`, V by grep over `plugins/*/src/**/index.ts`): table, pivot_table_v2, pie, all echarts_timeseries_*, echarts_area, mixed_timeseries, bar, funnel, gauge, graph, treemap, sunburst, radar, rose, bubble_v2, box_plot, histogram_v2, bullet, butterfly, gantt, time_pivot, world_map, country_map, all deck_*. NOT cross-filter emitters: big_number*, heatmap_v2, sankey_v2, waterfall, tree, word_cloud, handlebars, cal_heatmap. Drill-by/drill-to-detail (`Behavior.DrillBy/DrillToDetail`): pie, timeseries family, big numbers, box_plot, bubble, butterfly, candlestick, funnel, gantt, gauge, graph, mixed, radar, sunburst, treemap, table, pivot, world/country map, deck_arc.
Chart-customization plugins (dashboard "dynamic group by / time grain / time column / deck.gl layer visibility"): `chart_customization_dynamic_groupby|timegrain|timecolumn|deckgl_layer_visibility` (FE/src/constants.ts:205-210) registered in MainPreset.ts:150-165; no flag gate (STABLE, V).
Native filter types: `filter_select, filter_range, filter_time, filter_timecolumn, filter_timegrain` (FE/src/constants.ts:197-203).

## 2. Feature inventory with flag/config and lifecycle
| Area | Feature | Needs | Status / evidence |
|---|---|---|---|
| Explore | drag-and-drop, ad-hoc metrics/filters/columns | none | STABLE (flag removed, UPDATING.md:3326) |
| Explore | time comparison (`time_compare`, `comparison_type`) | none | STABLE; date-range shifts `DATE_RANGE_TIMESHIFTS_ENABLED` = development (config.py:757) |
| Explore | annotations/annotation layers | none (bundle dir `annotation_layers/` importable, assets.py:80) | STABLE |
| Explore | forecast (Prophet; "Predictive" section, Timeseries/index.ts:66) | `pip install .[prophet]` (pyproject.toml:274-281). NOT in `requirements/base.txt`; present only in `requirements/development.txt:774` (dev image). Default `superset` image installs `.[postgres,mysql,fastmcp]` (Dockerfile:352) so forecast fails there | STABLE feature, optional dependency |
| Explore | currency formatting | metric `currency {symbol,symbolPosition}`, dataset `currency_code_column`, `CURRENCIES` list (config.py:703); docs/docs/using-superset/number-formatting.mdx | STABLE |
| Explore | conditional formatting (table, pivot) | none | STABLE |
| Explore | Matrixify (small multiples) | `MATRIXIFY` | development (config.py:791) |
| SQL Lab | async execution | Celery worker + `RESULTS_BACKEND` (config.py:2303, dev docker uses `FileSystemCache("/app/superset_home/sqllab")`) + db `allow_run_async` (or `SQLLAB_FORCE_RUN_ASYNC`) ; `SQLLAB_ASYNC_TIME_LIMIT_SEC` 6h (config.py:2230) | STABLE |
| SQL Lab | Jinja templates | `ENABLE_TEMPLATE_PROCESSING` (default False; SSTI warning docs/admin_docs/configuration/sql-templating.mdx:17-33). Not enabled by docker dev config | STABLE flag, off by default |
| SQL Lab | saved queries, query history, `SQLLAB_BACKEND_PERSISTENCE` | default True | STABLE (config.py:1032) |
| SQL Lab | cost estimate | `ESTIMATE_QUERY_COST` + db `extra.cost_estimate_enabled` (Postgres/Presto/BigQuery only) | testing |
| SQL Lab | CTAS/CVAS | db `allow_ctas`/`allow_cvas`; `SQLLAB_CTAS_NO_LIMIT` (dev docker sets True) | STABLE |
| SQL Lab | schedule query | `SCHEDULED_QUERIES` dict (config.py:426), empty = hidden | U (UI gating not traced) |
| SQL Lab | "Explore from SQL" / Create chart | db `extra.allows_virtual_table_explore` (ImportV1DatabaseExtraSchema, databases/schemas.py:1250; set true in examples/_shared/database.yaml) | STABLE |
| SQL Lab | RLS inside SQL Lab | `RLS_IN_SQLLAB` | testing |
| Datasets | physical vs virtual (`sql:`), calculated columns (`expression:`), metrics, `cache_timeout`, `template_params`, `fetch_values_predicate` | none | STABLE (ImportV1DatasetSchema datasets/schemas.py:503-570) |
| Datasets | folders | `DATASET_FOLDERS` (dev docker enables it) | development (config.py:753); schema field `folders` exists |
| Dashboard | native filters (select/range/time/timecolumn/timegrain), scoping (`scope.rootPath/excluded`, `tabsInScope`), dependent filters (`cascadeParentIds`), default values (`defaultDataMask`) | none | STABLE |
| Dashboard | cross-filtering | metadata `cross_filters_enabled: true` (+ optional `chart_configuration`, `global_chart_configuration`) | STABLE (flag `DASHBOARD_CROSS_FILTERS` removed, UPDATING.md:3239) |
| Dashboard | drill-by | `DRILL_BY` True | stable runtime_config (config.py:982) |
| Dashboard | drill-to-detail | `DRILL_TO_DETAIL` True | **DEPRECATED** flag (config.py:1059) - still on |
| Dashboard | tabs, markdown, rows/columns, dividers, header | none; `ESCAPE_MARKDOWN_HTML` optional | STABLE |
| Dashboard | auto-refresh | UI interval; `DASHBOARD_AUTO_REFRESH_MODE` "force", `DASHBOARD_AUTO_REFRESH_INTERVALS` (config.py:2078-2080) | STABLE |
| Dashboard | CSS templates | `CSS_TEMPLATES` True; examples loader adds "Flat" template (examples/css_templates.py:30) | STABLE |
| Dashboard | per-dashboard theme | `theme_uuid` in dashboard schema (dashboards/schemas.py:680), `ENABLE_UI_THEME_ADMINISTRATION=True` (config.py:1362), `THEME_DEFAULT/THEME_DARK` | STABLE (theming detail: see 05) |
| Dashboard | embedding | `EMBEDDED_SUPERSET` (False default), `GUEST_TOKEN_JWT_SECRET` MUST be changed (config.py:3432), `superset-embedded-sdk/` dir; `EMBEDDABLE_CHARTS` True | stable runtime_config |
| Dashboard | permalinks | `/api/v1/dashboard/permalink` (commands/dashboard/permalink/) | STABLE |
| Dashboard | tags / certification | `TAGGING_SYSTEM` True = testing (config.py:900); `certified_by`, `certification_details` in chart/dashboard schemas | testing / STABLE |
| Dashboard | viewers (subject-based access) | `ENABLE_VIEWERS` False = testing (config.py:956). BREAKING: owners->editors, DASHBOARD_RBAC removed (UPDATING.md:2232-2245) | testing |
| Versioning | chart/dashboard history | `VERSION_HISTORY` True = testing (config.py:820) | testing |
| Mobile | consumption mode | `MOBILE_CONSUMPTION_MODE` (dev docker enables) | development |
| Export | CSV / XLSX / JSON of chart data | `/api/v1/chart/data` `result_format` csv,json,xlsx,arrow (common/chart_data.py:20-28); `CSV_EXPORT` encoding utf-8-sig (config.py:1714); table full CSV `ALLOW_FULL_CSV_EXPORT` testing | STABLE |
| Export | pivot CSV (Excel-friendly) | in pivot "Download" menu | U |
| Export | dashboard -> Excel workbook | `POST /api/v1/dashboard/<pk>/export_xlsx/` (dashboards/api.py:1888), `EXCEL_EXPORT_SYNC_MAX_ROWS` 100k (config.py:1780); charts WITHOUT saved `query_context` export only if table/big_number/big_number_total/pie, others listed in "Export Summary" (docs/docs/using-superset/exporting-dashboard-data.mdx) | STABLE |
| Export | image / PDF of dashboard | `THUMBNAILS`, `ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS`, `ENABLE_DASHBOARD_DOWNLOAD_WEBDRIVER_SCREENSHOT` (testing); Celery + `THUMBNAIL_CACHE_CONFIG`; endpoints `POST /dashboard/<pk>/cache_dashboard_screenshot/`, `GET /dashboard/<pk>/screenshot/<digest>/` (dashboards/api.py:2363,2798); chart: `GET /chart/<pk>/cache_screenshot/` (charts/api.py:1136) | testing/stable |
| Export | YAML bundle ZIP | `GET /api/v1/dashboard/export/?q=[ids]`, `GET /api/v1/assets/export/` (importexport/api.py:57), CLI `export-dashboards`, `export-datasources` | STABLE |
| Export | "example" bundle (parquet+YAML) | `GET /api/v1/dashboard/<pk>/export_as_example/` (dashboards/api.py:1796; `export_data`, `sample_rows` query params) | NEW; useful to author-in-UI then freeze |
| Alerts & Reports | alerts/reports | `ALERT_REPORTS` (testing, False default; dev docker True + Celery beat `reports.scheduler`). Needs worker+beat, `WEBDRIVER_BASEURL`, Chromium. 7.0.0: Playwright only, `WEBDRIVER_TYPE` unsupported (docs/admin_docs/configuration/alerts-reports.mdx:63). Default `superset` image bundles Chromium (Dockerfile:361-369) | testing |
| Alerts & Reports | targets | `Email`, `Slack`, `SlackV2`, `Webhook` (reports/models.py:67-71); Slack v1 deprecated (UPDATING.md:2818); webhook needs `ALERT_REPORT_WEBHOOK` + HTTPS-only (alerts-reports.mdx:249) | testing |
| Alerts & Reports | formats | `PDF, PNG, CSV, XLSX, TEXT, NONE(alerts)` (reports/models.py:83-90); requires SMTP_* (config.py:2400-2419) for email; `ALERT_REPORTS_NOTIFICATION_DRY_RUN=True` in dev docker (no real sends) | testing |
| Alerts & Reports | dynamic executor / tabs / retry | `ALERT_REPORT_DYNAMIC_EXECUTOR`, `ALERT_REPORT_TABS` = development; `ALERT_REPORTS_RETRY`, `ALERT_REPORT_WEBHOOK` = testing | mixed |

## 3. Caching and async in practical terms
- Defaults are OFF in `config.py`: `CACHE_CONFIG`/`DATA_CACHE_CONFIG` = `NullCache` (config.py:1547-1550). Docker dev `docker/pythonpath_dev/superset_config.py` sets Redis `RedisCache` (300 s) for `CACHE_CONFIG`, `DATA_CACHE_CONFIG`, `THUMBNAIL_CACHE_CONFIG`, Celery on Redis db0/db1, beat entries `reports.scheduler`, `reports.prune_log`. So a Docker-compose demo already caches chart data for 300 s; to make dashboards feel instant set `DATA_CACHE_CONFIG["CACHE_DEFAULT_TIMEOUT"]` (e.g. 3600) and/or `cache_timeout` on dataset/chart/database.
- `FILTER_STATE_CACHE_CONFIG`, `EXPLORE_FORM_DATA_CACHE_CONFIG` default to `SupersetMetastoreCache` (config.py:1562-1590), no extra infra.
- Cache warm-up: Celery task `cache-warmup` with `SUPERSET_CACHE_WARMUP_USER`, strategies documented in docs/admin_docs/configuration/cache.mdx:218-260 (requires worker+beat, `superset.tasks.cache` in imports, present in dev config).
- Global async queries (BREAKING re-platform, UPDATING.md:1370-1440): `FEATURE_FLAGS={"GLOBAL_ASYNC_QUERIES": True}` (auto-enables `GLOBAL_TASK_FRAMEWORK`) + `DISTRIBUTED_COORDINATION_CONFIG` Redis dict (config.py:3790-3830; currently None) + Celery worker. Old keys `GLOBAL_ASYNC_QUERIES_TRANSPORT/JWT_*` are REMOVED. Async per request via `async_mode`; UI default `GLOBAL_ASYNC_QUERIES_DEFAULT=True` (config.py:3380). Embedded guests need `can_read Task`. WebSocket push is optional (`WEBSOCKET_ENABLE` False). Lifecycle: testing. **Demo recommendation: leave OFF** (small data; fewer moving parts). Only SQL Lab async (worker+RESULTS_BACKEND) is worth keeping, already wired in docker dev.
- Celery worker must import `superset.sql_lab`, `superset.tasks.*` (dev config lacks `superset.tasks.slack` and `version_history_retention` vs core CeleryConfig config.py:2107-2120; add if Slack/version history needed - U impact).

## 4. `superset load_examples` on this commit
- Orchestration: `superset/cli/examples.py:load_examples_run` -> `load_css_templates()` -> every auto-discovered `load_<name>` parquet loader -> `load_examples_from_configs` (YAML import via `ImportExamplesCommand`, overwrite=True). Each loader failure is only logged as warning and skipped (cli/examples.py `_load_dataset`) so a partial load can look "successful".
- Data source: LOCAL vendored Parquet inside the package (`superset/examples/<name>/data.parquet` or `data/*.parquet`, `get_examples_folder()` helpers.py:53). No GitHub download any more (UPDATING.md:2996-3014, 6.1.0 section). MANIFEST.in:22 ships the dir. Total ~34 MB parquet: world_health 15.0 MB, long_lat 11.9 MB, fcc_new_coder_survey 2.8 MB, flights 2.1 MB, rest <0.5 MB each (sizes from `ls`; row counts U).
- Creates 9 dashboards (V by `dashboard_title`): deck.gl Demo, FCC New Coder Survey 2018, Featured Charts, Misc Charts, Sales Dashboard, Slack Dashboard, USA Births Names, Video Game Sales, World Bank's Data (slug `world_health`). 21 tables incl. `wb_health_population`, `birth_names`, `cleaned_sales_data`, `international_sales`, `video_game_sales`, `"FCC 2018 Survey"` (space), `users`, `messages`, `threads` (generic names - keep examples DB separate from the metadata DB). Plus CSS template "Flat". `--load-test-data/-t`, `--load-big-data/-b`, `--only-metadata/-m`, `--force/-f`.
- Target DB: `SQLALCHEMY_EXAMPLES_URI` (config.py:3272 sqlite default; docker dev builds a Postgres URI from `EXAMPLES_*` env vars, superset_config.py:53-60, docker/.env:39-44) - Postgres works (docker default). `_shared/database.yaml` has uuid `a2dc77af-e654-49bb-b321-40f6b559a1ee`, db name `examples`.
- Time: UNVERIFIED numerically; docker-init.sh:58 calls it "one of the slowest steps". `SUPERSET_LOAD_EXAMPLES=yes` is default in docker/.env:74; re-runs skipped when slug `world_health` + table `wb_health_population` exist (docker-init.sh:65-95); `SUPERSET_FORCE_LOAD_EXAMPLES=yes` to force.
- Pitfalls: (1) examples DB holds a Postgres schema `public` only; (2) example dashboards have `published: true`; (3) deck.gl charts need browser internet for OSM tiles; (4) charts in examples have `query_context: null`; (5) data_file/parquet is honoured ONLY by the auto-discovery path (`data_loading.py:discover_datasets`), NOT by `import-directory`/`assets/import` - confirmed by grep (only generic_loader + export_example use `data_file`). So custom NxtBI data cannot ride on the examples YAML path unless you add a folder to `superset/examples/` in the image.
- Recommendation: set `SUPERSET_LOAD_EXAMPLES=no` for the NxtBI demo (keep optional profile for the "Featured Charts" gallery which is a good chart-type reference and a template for authored params).

## 5. Dashboards-as-code: import bundle spec on this commit
Layout (ZIP with ONE root folder, root stripped by `remove_root`, commands/importers/v1/utils.py:56,450; or directory for `import-directory`):
```
nxtbi_bundle/
  metadata.yaml                      # version: 1.0.0 ; type: assets | Dashboard ; timestamp
  databases/NxtBI_Demo.yaml
  datasets/NxtBI_Demo/fact_sales.yaml   # any subfolder name; prefix `datasets/` matters
  charts/<anything>.yaml
  dashboards/<anything>.yaml
  (optional) queries/*.yaml (saved queries), annotation_layers/*.yaml
```
Prefix routing is by file-name prefix only (`databases/ datasets/ charts/ dashboards/ queries/ annotation_layers/`, assets.py:84-91). Directory names under them are free.
| Asset | Required fields (marshmallow `required=True`) | Source |
|---|---|---|
| metadata.yaml | `version` == "1.0.0" (`IMPORT_VERSION`); `type` must equal `assets` for REST `/assets/import` (assets.py:352), `Dashboard` for dashboard importer; `import-directory` strips `type` (examples/utils.py:258) | commands/importers/v1/utils.py:48-52 |
| database | `database_name, sqlalchemy_uri, uuid, version` (+ optional `extra{allows_virtual_table_explore,cost_estimate_enabled,...}`, `expose_in_sqllab, allow_ctas, allow_cvas, allow_dml, allow_run_async, allow_csv_upload, cache_timeout, impersonate_user, password`) | databases/schemas.py:1296-1343 |
| dataset | `table_name, uuid, version, database_uuid`; optional `schema, catalog, sql` (virtual), `main_dttm_col, columns[], metrics[], cache_timeout, extra, template_params, folders, normalize_columns, always_filter_main_dttm, filter_select_enabled, fetch_values_predicate`. Column: `column_name` req, `type, is_dttm, groupby, filterable, expression, verbose_name, python_date_format, uuid`. Metric: `metric_name, expression` req, `verbose_name, metric_type, d3format, currency{symbol,symbolPosition}, warning_text, uuid`. Duplicate child uuids rejected | datasets/schemas.py:416-570 |
| chart | `slice_name, viz_type, uuid, version`, exactly ONE of `dataset_uuid` / `datasource_ref`; `params` dict; `query_context` JSON string or null; `cache_timeout, certified_by, description, tags` optional | charts/schemas.py:2066-2092 |
| dashboard | `dashboard_title, uuid, version`; `position` dict, `metadata` dict, `slug, published, css, description, theme_uuid, tags, certified_by` optional | dashboards/schemas.py:656-682 |
All `version` values are the string `1.0.0` (examples use it everywhere).

How things are stored:
- Chart `params` is a YAML mapping (importer `json.dumps` it, chart/importers/v1/utils.py:241). `query_context` is a JSON-encoded string or `null`; if present, importer rewrites `datasource.id/type` and `form_data.datasource` (commands/utils.py:395-414). All shipped examples use `null`; dashboards render (frontend builds the query from form_data). Consequences of `null`: Excel dashboard export skips non table/big_number/pie charts (see 2); Reports for such charts first take a screenshot to regenerate it (commands/report/execute.py:1415-1420). Opening + saving a chart in Explore populates it.
- Dashboard `position` is the position_json dict: `DASHBOARD_VERSION_KEY: v2`, `ROOT_ID{type ROOT,children}`, `GRID_ID{type GRID}`, `HEADER_ID{type HEADER,meta.text}`, `ROW-*`, `COLUMN-*`, `TABS-*/TAB-*`, `MARKDOWN-*`, `DIVIDER-*`, `CHART-*{meta:{chartId:int, uuid, sliceName, width 1-12, height}}`. The importer finds charts ONLY via `meta.uuid` of CHART nodes and remaps `meta.chartId` (dashboard/importers/v1/utils.py:42-71,134-139,commands/importers/v1/assets.py find_chart_uuids). `chartId` must be a unique int per chart inside the bundle (placeholder).
- Dashboard `metadata` = json_metadata: `native_filter_configuration[]` (targets use `datasetUuid`, converted to `datasetId` at import, utils.py:149-153; dataset MUST be in the bundle else KeyError), `cross_filters_enabled`, `chart_configuration{<chartId or chart uuid>: {id, crossFilters:{scope, chartsInScope}}}`, `global_chart_configuration`, `chart_customization_config[]` (dynamic group-by controls; also `datasetUuid`), `color_scheme`, `label_colors`, `refresh_frequency`, `expanded_slices`, `default_filters` (JSON string), `timed_refresh_immune_slices`. chart-id lists (`chartsInScope`) accept ints OR chart uuids (`_remap_chart_ids`, utils.py:~180). `scope.excluded` accepts ints only.
- Idempotency: every object keyed by `uuid`; re-import with overwrite updates in place (import_dashboard/import_chart matrix). `ImportAssetsCommand(overwrite=True)` default; `overwrite=false` makes existing uuids a validation error (assets.py `_prevent_overwrite_existing_assets`). Dataset children matched by name or uuid and synced (columns/metrics not in bundle are REMOVED on overwrite, dataset utils.py:~818). Soft-deleted rows with same uuid are restored (SOFT_DELETE True, config.py:773). Imported assets get the importing user as editor and default viewers.
- Database passwords: (a) clear password inside `sqlalchemy_uri` in YAML - accepted, stored masked/encrypted via `set_sqlalchemy_uri` (database importer utils.py:344-348); (b) `password:` key in YAML (utils.py:245-249); (c) REST/CLI `passwords` JSON map keyed by file path, e.g. `{"databases/NxtBI_Demo.yaml": "<value from env>"}` (commands/importers/v1/utils.py:247). A masked URI (`XXXXXXXXXX`) without a password => validation error (databases/schemas.py:1352-1363). Render the YAML from a template at deploy time from env (`${NXTBI_DB_PASSWORD}`); never commit it. `PREVENT_UNSAFE_DB_CONNECTIONS=True` blocks sqlite (config.py:3282).
- Entry points: CLI `superset import-directory <dir> [-o overwrite] [-f force-data] [-u admin]` (cli/importexport.py:33-80; uses ImportExamplesCommand, loads only `.yaml/.yml`, sets dashboards `published=True`, `ignore_permissions=True`, no `type` needed, KeyError-skips a dashboard whose charts are missing); CLI `superset import-dashboards -p file.zip -u admin` (importexport.py:150-195; metadata `type: Dashboard`, overwrite=True); REST `POST /api/v1/assets/import/` multipart `bundle`(zip) + `passwords` + `overwrite` (default true) + `sparse` (importexport/api.py:99-225; role needs Import permission; also needs session+CSRF token `X-CSRFToken` from `/api/v1/security/csrf_token/`); REST `POST /api/v1/dashboard/import/` fields `formData`, `overwrite=true`, `overwrite_all`, `passwords` (dashboards/api.py:3184-3315). U: exact multipart field name `formData` for dashboard import - verify against swagger at `/swagger/v1`.
- RLS, users, roles, groups, themes, CSS templates, alerts/reports are NOT in the assets bundle (schemas dict assets.py:84-91). RLS = `POST /api/v1/rowlevelsecurity/` body `{name, filter_type: Regular|Base, tables:[dataset ids], subjects:[subject ids], clause, group_key}` (row_level_security/schemas.py:125-166). NOTE `subjects` replaced `roles` (UPDATING.md:2243); subject ids from `GET /api/v1/security/subject/`.

## 6. Worked example (schema-correct; fictitious UUIDs; password supplied outside)
`databases/NxtBI_Demo.yaml`
```yaml
database_name: NxtBI Demo
sqlalchemy_uri: postgresql+psycopg2://nxtbi_ro:${NXTBI_DB_PASSWORD}@db:5432/nxtbi_demo   # render from env before zipping
expose_in_sqllab: true
allow_ctas: false
allow_cvas: false
allow_dml: false
allow_run_async: true
cache_timeout: null
extra:
  allows_virtual_table_explore: true
uuid: 7c1f2a40-5b7e-4d0e-9a3f-1e2d3c4b5a60
version: 1.0.0
```
`datasets/NxtBI_Demo/fact_sales.yaml`
```yaml
table_name: fact_sales
schema: nxtbi
catalog: null
sql: null
main_dttm_col: order_date
cache_timeout: 3600
filter_select_enabled: true
normalize_columns: false
always_filter_main_dttm: false
offset: 0
uuid: 3f6b9d52-8a41-4c7e-b2d9-6e0a1c5f7b81
database_uuid: 7c1f2a40-5b7e-4d0e-9a3f-1e2d3c4b5a60
version: 1.0.0
columns:
- {column_name: order_date,  type: DATE,             is_dttm: true,  groupby: true, filterable: true, verbose_name: Order date}
- {column_name: org_code,    type: VARCHAR(32),      is_dttm: false, groupby: true, filterable: true, verbose_name: Org}
- {column_name: region_en,   type: VARCHAR(64),      is_dttm: false, groupby: true, filterable: true, verbose_name: Region}
- {column_name: region_ar,   type: VARCHAR(64),      is_dttm: false, groupby: true, filterable: true, verbose_name: "المنطقة"}
- {column_name: channel,     type: VARCHAR(32),      is_dttm: false, groupby: true, filterable: true}
- {column_name: category,    type: VARCHAR(64),      is_dttm: false, groupby: true, filterable: true}
- {column_name: revenue,     type: NUMERIC(14,2),    is_dttm: false, groupby: false, filterable: true}
- {column_name: units,       type: INTEGER,          is_dttm: false, groupby: false, filterable: true}
- {column_name: margin_pct,  type: DOUBLE PRECISION, is_dttm: false, groupby: false, filterable: true, expression: "(revenue - cost) / NULLIF(revenue,0)"}
metrics:
- {metric_name: count,         verbose_name: Orders,        expression: "COUNT(*)",       metric_type: count}
- {metric_name: revenue_sum,   verbose_name: Revenue,       expression: "SUM(revenue)",   d3format: ",.0f", currency: {symbol: SAR, symbolPosition: suffix}}
- {metric_name: units_sum,     verbose_name: Units,         expression: "SUM(units)",     d3format: ",d"}
- {metric_name: aov,           verbose_name: Avg order value, expression: "SUM(revenue)/NULLIF(COUNT(*),0)", d3format: ",.2f"}
```
(`margin_pct` as a calculated column requires a `cost` column in the table; drop it if absent. `SAR` only displays if frontend currency accepts it; `CURRENCIES` list config.py:703 does not contain SAR - U whether custom symbol objects need it.)

`charts/sales_by_region.yaml` (echarts_timeseries_bar, categorical x-axis)
```yaml
slice_name: Revenue by region
viz_type: echarts_timeseries_bar
dataset_uuid: 3f6b9d52-8a41-4c7e-b2d9-6e0a1c5f7b81
uuid: b4e8c1a2-6d3f-4f7a-8c5e-2a9d0f1b3c47
version: 1.0.0
description: Revenue per region split by channel
cache_timeout: null
certified_by: null
certification_details: null
query_context: null
params:
  viz_type: echarts_timeseries_bar
  x_axis: region_en
  metrics: [revenue_sum]
  groupby: [channel]
  adhoc_filters:
  - {clause: WHERE, expressionType: SIMPLE, operator: TEMPORAL_RANGE, subject: order_date, comparator: No filter}
  row_limit: 10000
  orientation: vertical
  stack: Stack
  show_legend: true
  legendType: scroll
  legendOrientation: top
  rich_tooltip: true
  sort_series_type: sum
  color_scheme: supersetColors
  y_axis_format: SMART_NUMBER
  x_axis_sort_series: name
  x_axis_sort_series_ascending: true
  extra_form_data: {}
```
`dashboards/sales_overview.yaml`
```yaml
dashboard_title: NxtBI Sales Overview
slug: nxtbi-sales-overview
description: null
css: ''
published: true
uuid: d6a0e3c4-8f51-4b9c-ae70-4c1f2b3d5e69
version: 1.0.0
metadata:
  color_scheme: supersetColors
  cross_filters_enabled: true
  refresh_frequency: 0
  expanded_slices: {}
  timed_refresh_immune_slices: []
  default_filters: '{}'
  global_chart_configuration:
    scope: {rootPath: [ROOT_ID], excluded: []}
    chartsInScope: [b4e8c1a2-6d3f-4f7a-8c5e-2a9d0f1b3c47]   # chart uuids accepted, remapped at import
  native_filter_configuration:
  - id: NATIVE_FILTER-region01
    type: NATIVE_FILTER
    name: Region
    filterType: filter_select
    description: ''
    cascadeParentIds: []
    targets:
    - column: {name: region_en}
      datasetUuid: 3f6b9d52-8a41-4c7e-b2d9-6e0a1c5f7b81
    controlValues: {multiSelect: true, enableEmptyFilter: false, defaultToFirstItem: false, inverseSelection: false, searchAllOptions: false}
    defaultDataMask: {extraFormData: {}, filterState: {}, ownState: {}}
    scope: {rootPath: [ROOT_ID], excluded: []}
    chartsInScope: [b4e8c1a2-6d3f-4f7a-8c5e-2a9d0f1b3c47]
position:
  DASHBOARD_VERSION_KEY: v2
  ROOT_ID: {type: ROOT, id: ROOT_ID, children: [GRID_ID]}
  GRID_ID: {type: GRID, id: GRID_ID, parents: [ROOT_ID], children: [ROW-kpi01]}
  HEADER_ID: {type: HEADER, id: HEADER_ID, meta: {text: NxtBI Sales Overview}}
  ROW-kpi01:
    type: ROW
    id: ROW-kpi01
    parents: [ROOT_ID, GRID_ID]
    children: [CHART-rev01]
    meta: {background: BACKGROUND_TRANSPARENT}
  CHART-rev01:
    type: CHART
    id: CHART-rev01
    parents: [ROOT_ID, GRID_ID, ROW-kpi01]
    children: []
    meta: {chartId: 1, uuid: b4e8c1a2-6d3f-4f7a-8c5e-2a9d0f1b3c47, sliceName: Revenue by region, width: 12, height: 60}
```
Zip it as `nxtbi_bundle/...` + `metadata.yaml` (`version: 1.0.0`, `type: assets`, `timestamp: '2026-11-17T00:00:00+00:00'`). Import: `curl -b cookies -H "X-CSRFToken: $T" -F bundle=@nxtbi_bundle.zip -F overwrite=true -F passwords='{"databases/NxtBI_Demo.yaml":"..."}' http://localhost:8088/api/v1/assets/import/` or `docker exec superset_app superset import-directory /app/nxtbi_bundle -o -u admin`. (This example was checked field-by-field against the schemas above, not executed: U at runtime.)

## 7. Recommendation: how to provision the NxtBI demo
1. Data: seed Postgres with a dedicated DB/schema (`nxtbi_demo.nxtbi`) via a SQL file mounted into `docker/docker-entrypoint-initdb.d/` (pattern: examples-init.sh creates `examples` DB/user, GRANT on schema public). Use `generate_series` + deterministic `setseed`/hash-based values so rebuilds are identical; include `org_code` (RLS key), `region_en`/`region_ar` (Arabic strings, UTF-8; Arabic UI chrome needs `BUILD_TRANSLATIONS=true` build arg, Dockerfile:32,131, default false; locale `ar` exists in LANGUAGES config.py:614). Parquet/`load_examples` path is the wrong tool for custom data (section 4 pitfall).
2. Content: YAML bundle (section 5-6) generated by a small Python script (Jinja/f-strings + `uuid.uuid5(NAMESPACE, "<asset-key>")` so UUIDs are stable and reproducible), zipped, then `POST /api/v1/assets/import/` (or `import-directory`) as an idempotent init step after `superset init`; RLS + demo users/groups via a second REST/CLI step (`superset fab create-user`, `POST /api/v1/rowlevelsecurity/`).
3. Why bundle over REST-create: REST needs numeric ids in sequence (dataset id -> chart `datasource_id`/params.datasource -> dashboard `position_json` chartId + `dashboards` M2M + native-filter `datasetId`), non-idempotent POSTs (duplicates unless you search by name), and ordering/partial-failure cleanup. The bundle resolves all of that from UUIDs inside one transaction (`@transaction` on `ImportAssetsCommand.run`, assets.py:`run`), rolls back on error, reports file-keyed validation errors (422), and gives true re-run idempotency. Remaining bundle risks: a hand-written `position` tree (parents/children consistency, width sum 12 per row), `query_context: null` limitations, `datasetUuid` KeyError when a dataset is missing, and import schema drift between releases (the schemas are strict - pin to this commit).
4. Fast authoring loop: build one chart/dashboard in the UI, export `GET /api/v1/dashboard/export/?q=!(ID)` (or `export_as_example`), diff against hand-generated YAML, then templatise. Treat the Featured Charts example (`superset/examples/featured_charts/charts/*.yaml`) as the param catalogue for each viz_type.
5. Chart choices for attractive output: big_number_total + big_number (trend) KPIs, echarts_timeseries_bar/line/area, pie (donut via `innerRadius`), treemap_v2, heatmap_v2, funnel, sankey_v2, pivot_table_v2/table with conditional formatting, mixed_timeseries; skip pop_kpi, ag-grid-table, matrixify (non-stable flags) and deck.gl (needs external tiles). Cross-filter: enable `cross_filters_enabled`; confirm emitters (pie, bar, treemap, table). Drill-by works on pie/bar/treemap by default (`DRILL_BY` True).
6. Turn on for demo (docker `superset_config_docker.py`): `FEATURE_FLAGS` add `ENABLE_TEMPLATE_PROCESSING` (only if Jinja RLS/SQL demo wanted), `TAGGING_SYSTEM` (default on), `THUMBNAILS`+`ENABLE_DASHBOARD_SCREENSHOT_ENDPOINTS` (+Celery) for dashboard cards; keep `ALERT_REPORTS` + dry run; bump `DATA_CACHE_CONFIG` timeout; set `GUEST_TOKEN_JWT_SECRET` only if embedding. Keep async queries off.
7. Future (out of scope, document only): Cube Core / Wren / Schema-Sense / custom NxtBI semantic layer map to `SEMANTIC_LAYERS` (development) and chart `datasource_ref` (charts/schemas.py:2078) - bundles already model semantic views as typed references.
