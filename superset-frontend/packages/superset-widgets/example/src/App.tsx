/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
import { useState } from 'react';
import {
  Chart,
  FilterSelect,
  Markdown,
  MetricTile,
  SupersetProvider,
  Table,
  Widget,
} from '@apache-superset/widgets';
// `?raw` loads this file's text for the source panel, not the module itself.
// eslint-disable-next-line import/no-self-import
import appSource from './App.tsx?raw';
import { authFor, config } from './config';
import MinimalEmbed from './MinimalEmbed';
import minimalEmbedSource from './minimalEmbedSource';
import { ErrorLog, useErrorLog } from './ErrorLog';
import { EventLog } from './EventLog';
import { Gallery } from './Gallery';
import { HostFilterBar, hostFilter } from './HostFilterBar';
import { Isolation } from './Isolation';
import {
  Frame,
  StructureProvider,
  StructureTree,
  useStructureVisible,
} from './structure';

const withoutLicense = (source: string) =>
  source.replace(/^\/\*\*[\s\S]*?\*\/\s*/, '');

const binding = (metrics: string[], dimensions: string[], rowLimit = 1000) => ({
  datasetId: config.datasetId,
  metrics,
  dimensions,
  rowLimit,
});

const COPY = {
  ltr: {
    title: 'Acme Operations',
    tagline: 'Superset widgets rendered in this app’s own React tree.',
    note: 'Text in a widget follows the provider’s **direction**. Charts keep their axes left to right in every locale.',
  },
  rtl: {
    title: 'عمليات أكمي',
    tagline: 'عناصر Superset معروضة داخل شجرة React الخاصة بهذا التطبيق.',
    note: 'النص داخل العنصر يتبع **اتجاه** المزوّد. المخططات تحتفظ بمحاورها من اليسار إلى اليمين في كل اللغات.',
  },
};

function Page() {
  const [dark, setDark] = useState(false);
  const [rtl, setRtl] = useState(false);
  const [showStructure, setShowStructure] = useStructureVisible();
  // The host owns this state; the provider only reads it (`filters` below).
  const [selected, setSelected] = useState<string[]>([]);
  const [errors, onError] = useErrorLog();

  const direction = rtl ? 'rtl' : 'ltr';
  const themeMode = dark ? 'dark' : 'default';
  const copy = COPY[direction];
  const appClass = ['app', dark && 'app-dark', showStructure && 'app-structure']
    .filter(Boolean)
    .join(' ');

  return (
    <div className={appClass} dir={direction} lang={rtl ? 'ar' : 'en'}>
      <header className="app-header">
        <div>
          <h1>{copy.title}</h1>
          <p>{copy.tagline}</p>
          {config.authMode === 'session' && (
            <p className="hint">
              Uses your Superset login, no backend. Not signed in?{' '}
              <a
                href={`${config.supersetUrl}/login/`}
                target="_blank"
                rel="noreferrer"
              >
                Log in to Superset
              </a>
              , then reload.
            </p>
          )}
        </div>
        <div className="toggles">
          <label className="toggle">
            <input
              type="checkbox"
              checked={showStructure}
              onChange={event => setShowStructure(event.target.checked)}
            />
            Show structure
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={rtl}
              onChange={event => setRtl(event.target.checked)}
            />
            العربية (RTL)
          </label>
          <label className="toggle">
            <input
              type="checkbox"
              checked={dark}
              onChange={event => setDark(event.target.checked)}
            />
            Dark
          </label>
        </div>
      </header>

      {config.authMode === 'session' && (
        <section className="minimal-embed">
          <h2>Embed one widget</h2>
          <p className="hint">
            The whole integration: a provider and a widget. This is the file
            below, rendered live next to its source.
          </p>
          <div className="minimal-embed-body">
            <pre className="code-block" dir="ltr">
              <code>{withoutLicense(minimalEmbedSource)}</code>
            </pre>
            <div className="card">
              {/* Its own provider, told the direction the toggle chose. */}
              <MinimalEmbed direction={direction} />
            </div>
          </div>
        </section>
      )}

      <SupersetProvider
        supersetDomain={config.supersetUrl}
        // Guest mode: a token from this app's own backend, for audience "a".
        {...authFor('a')}
        // The host's filter state, declaratively: widgets on the dataset
        // follow it, and `null` lifts it.
        filters={{
          region: hostFilter(config.datasetId, config.filterColumn, selected),
        }}
        // Every failure a widget shows is also reported here; none is thrown.
        onError={onError}
        // `locale` alone would do: only its direction is used.
        locale={rtl ? config.rtlLocale : undefined}
        direction={direction}
        themeMode={themeMode}
      >
        <Frame
          label="<SupersetProvider>"
          detail={`${config.supersetUrl} · ${
            config.authMode === 'guest'
              ? 'guest token from /api/guest-token'
              : 'your Superset login'
          } · ${direction}`}
          kind="superset"
          className="provider"
        >
          <Frame
            label="<HostFilterBar>"
            detail="state in the host, passed as <SupersetProvider filters>"
            kind="host"
          >
            <HostFilterBar
              label={config.filterColumn}
              values={config.filterValues}
              selected={selected}
              onChange={setSelected}
            />
          </Frame>
          <div className="app-body">
            <main>
              <Frame label="Inline widgets" kind="host" as="section">
                <h2>Inline widgets</h2>
                <p className="hint">
                  Defined here, validated and executed by Superset. They
                  cross-filter each other, and the host filter above narrows
                  them.
                </p>
                <div className="grid">
                  <Frame
                    label="<FilterSelect>"
                    code
                    detail={`datasetId=${config.datasetId} column=${config.category}`}
                    kind="superset"
                    className="card small"
                  >
                    <FilterSelect
                      datasetId={config.datasetId}
                      column={config.category}
                    />
                  </Frame>
                  <Frame
                    label="<MetricTile>"
                    code
                    detail={config.metric}
                    kind="superset"
                    className="card small"
                  >
                    <MetricTile
                      dataBinding={binding([config.metric], [])}
                      label={`Total ${config.metric}`}
                    />
                  </Frame>
                  <Frame
                    label="<Chart chartType=bar>"
                    code
                    detail={`${config.metric} by ${config.filterColumn}, top 10, crossFilter`}
                    kind="superset"
                    className="card"
                  >
                    <Chart
                      instanceId="by-dimension"
                      dataBinding={binding(
                        [config.metric],
                        [config.filterColumn],
                        10,
                      )}
                      chartType="bar"
                      crossFilter
                      chrome={{
                        titleText: `${config.metric} by ${config.filterColumn} (top 10)`,
                      }}
                      echartsOptions={{
                        tooltip: { trigger: 'axis' },
                        xAxis: {
                          type: 'category',
                          data: {
                            $bind: {
                              source: 'dimension',
                              alias: config.filterColumn,
                            },
                          },
                        },
                        yAxis: { type: 'value' },
                      }}
                    />
                  </Frame>
                  <Frame
                    label="<Chart> (pie)"
                    code
                    detail={`${config.metric} by ${config.category}, crossFilter`}
                    kind="superset"
                    className="card"
                  >
                    <Chart
                      instanceId="by-category"
                      dataBinding={binding([config.metric], [config.category])}
                      crossFilter
                      chrome={{
                        titleText: `${config.metric} by ${config.category}`,
                      }}
                      echartsOptions={{
                        tooltip: { trigger: 'item' },
                        series: [
                          {
                            type: 'pie',
                            radius: '60%',
                            data: {
                              $bind: {
                                source: 'records',
                                fields: {
                                  name: config.category,
                                  value: config.metric,
                                },
                              },
                            },
                          },
                        ],
                      }}
                    />
                  </Frame>
                  <Frame
                    label="<Table>"
                    code
                    detail={`${config.label} · mirrored when the direction is rtl`}
                    kind="superset"
                    className="card"
                  >
                    <Table
                      dataBinding={binding(
                        [config.metric],
                        [config.label, config.category],
                        50,
                      )}
                      columnDefs={[
                        { field: config.label, flex: 1 },
                        { field: config.category, width: 120 },
                        { field: config.metric, type: 'numericColumn' },
                      ]}
                    />
                  </Frame>
                  <Frame
                    label="<Markdown>"
                    code
                    detail="text follows the provider's direction"
                    kind="superset"
                    className="card small"
                  >
                    <Markdown content={copy.note} />
                  </Frame>
                </div>
              </Frame>

              {config.extensionWidgetType && (
                <Frame label="Extension widget" kind="host" as="section">
                  <h2>From an extension</h2>
                  <p className="hint">
                    Nothing about this widget is bundled here. The type names
                    the extension that draws it, so the provider fetched it from
                    Superset and loaded its code into this page.
                  </p>
                  <div className="grid">
                    <Frame
                      label={`<Widget type="${config.extensionWidgetType}">`}
                      code
                      detail={`${config.metric} by ${config.category}`}
                      kind="superset"
                      className="card"
                    >
                      <Widget
                        type={config.extensionWidgetType}
                        instanceId="from-extension"
                        props={{
                          dataBinding: binding(
                            [config.metric],
                            [config.category],
                          ),
                          colorDimension: config.category,
                        }}
                      />
                    </Frame>
                  </div>
                </Frame>
              )}

              <Frame label="Saved widgets" kind="host" as="section">
                <h2>Saved widgets</h2>
                <p className="hint">
                  Stored in Superset and rendered by id. The page holds no
                  definition: the query is whatever Superset has saved.
                </p>
                {config.savedWidgetIds.length > 0 ? (
                  <div className="grid">
                    {config.savedWidgetIds.map(id => (
                      <Frame
                        key={id}
                        label="<Widget id>"
                        code
                        detail={id}
                        kind="superset"
                        className="card"
                      >
                        <Widget id={id} />
                      </Frame>
                    ))}
                  </div>
                ) : (
                  <p className="hint">
                    None configured. Set <code>EMBED_WIDGET_IDS</code> in{' '}
                    <code>.env</code> to saved widget uuids (
                    <code>GET /api/v1/widget/</code>).
                  </p>
                )}
              </Frame>
            </main>
            <aside>
              <Frame
                label="<EventLog>"
                detail="useWidgetEvent('valueChanged')"
                kind="host"
              >
                <EventLog />
              </Frame>
              <Frame
                label="<ErrorLog>"
                detail="<SupersetProvider onError>"
                kind="host"
              >
                <ErrorLog entries={errors} />
              </Frame>
              {showStructure && (
                <>
                  <section className="card structure-panel">
                    <h2>React tree</h2>
                    <StructureTree />
                  </section>
                  <details className="card structure-panel source" dir="ltr">
                    <summary>App.tsx</summary>
                    <pre>{appSource}</pre>
                  </details>
                </>
              )}
            </aside>
          </div>
        </Frame>
      </SupersetProvider>

      <Isolation
        themeMode={themeMode}
        direction={direction}
        onError={onError}
      />

      <Gallery themeMode={themeMode} direction={direction} />
    </div>
  );
}

export default function App() {
  return (
    <StructureProvider>
      <Page />
    </StructureProvider>
  );
}
