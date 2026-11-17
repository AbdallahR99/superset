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
  MetricTile,
  SupersetProvider,
  type ThemeModeName,
  type WidgetErrorInfo,
} from '@apache-superset/widgets';
import {
  authFor,
  config,
  firstShape,
  type Audience,
  type DatasetShape,
} from './config';
import { HostFilterBar, hostFilter } from './HostFilterBar';
import { Frame } from './structure';

/**
 * One provider with everything of its own: the token it is given (in guest
 * mode, one per audience), the filter its host control holds, the widgets
 * under it. The chart deliberately has the same `instanceId` in both
 * providers: an id names a widget within its provider, not on the page.
 */
function IndependentProvider({
  audience,
  shape,
  themeMode,
  direction,
  onError,
}: {
  audience: Audience;
  shape: DatasetShape;
  themeMode: ThemeModeName;
  direction: 'ltr' | 'rtl';
  onError: (error: Error, info: WidgetErrorInfo) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);
  const name = audience.toUpperCase();
  const binding = (dimensions: string[]) => ({
    datasetId: shape.datasetId,
    metrics: [shape.metric],
    dimensions,
    rowLimit: 8,
  });

  return (
    <SupersetProvider
      supersetDomain={config.supersetUrl}
      {...authFor(audience)}
      filters={{
        own: hostFilter(shape.datasetId, shape.dimension, selected),
      }}
      onError={onError}
      direction={direction}
      themeMode={themeMode}
    >
      <Frame
        label={`<SupersetProvider> ${name}`}
        detail={`${shape.table} #${shape.datasetId}${
          config.authMode === 'guest' ? ` · guestTokenKey="${audience}"` : ''
        }`}
        kind="superset"
        className="card isolation-provider"
      >
        <h3>Provider {name}</h3>
        <HostFilterBar
          label={shape.dimension}
          values={shape.values}
          selected={selected}
          onChange={setSelected}
        />
        <div className="isolation-widgets">
          <div className="isolation-tile">
            <MetricTile
              dataBinding={binding([])}
              label={`${shape.metric} · ${shape.table}`}
            />
          </div>
          <div className="isolation-chart">
            <Chart
              instanceId="by-dimension"
              chartType="bar"
              crossFilter
              dataBinding={binding([shape.dimension])}
              echartsOptions={{
                tooltip: { trigger: 'axis' },
                xAxis: {
                  type: 'category',
                  data: {
                    $bind: { source: 'dimension', alias: shape.dimension },
                  },
                },
                yAxis: { type: 'value' },
              }}
              chrome={{ titleText: `${shape.metric} by ${shape.dimension}` }}
            />
          </div>
        </div>
      </Frame>
    </SupersetProvider>
  );
}

/**
 * Two providers on one page that share nothing: filter one, click a bar in
 * one, and the other does not move. In guest mode each also asks the broker
 * for its own token.
 */
export function Isolation({
  themeMode,
  direction,
  onError,
}: {
  themeMode: ThemeModeName;
  direction: 'ltr' | 'rtl';
  onError: (error: Error, info: WidgetErrorInfo) => void;
}) {
  return (
    <section className="isolation">
      <h2>Two independent providers</h2>
      <p className="hint">
        Each has its own event bus, data client, credentials and host filter.
        Filter or cross-filter on one side: the other side does not refetch.
        Give two providers the same <code>bus</code> only when you want them to
        act as one (see the gallery below).
      </p>
      <div className="isolation-row">
        <IndependentProvider
          audience="a"
          shape={firstShape()}
          themeMode={themeMode}
          direction={direction}
          onError={onError}
        />
        <IndependentProvider
          audience="b"
          shape={config.second}
          themeMode={themeMode}
          direction={direction}
          onError={onError}
        />
      </div>
    </section>
  );
}
