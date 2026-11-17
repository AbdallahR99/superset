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

// Vite injects env only where the source literally reads `import.meta.env`,
// so this must not be destructured (oxlint's prefer-destructuring would).
const viteEnv = import.meta.env;

const list = (value: string | undefined): string[] =>
  (value ?? '')
    .split(',')
    .map(item => item.trim())
    .filter(Boolean);

const text = (value: string | undefined, fallback: string): string =>
  value !== undefined && value.trim() !== '' ? value.trim() : fallback;

/** A whole number from the environment, or `fallback` when it is not one. */
const integer = (value: string | undefined, fallback: number): number => {
  const parsed = Number(value);
  return value !== undefined && value.trim() !== '' && Number.isInteger(parsed)
    ? parsed
    : fallback;
};

/** What one provider's demo queries: a dataset, a metric, a dimension. */
export interface DatasetShape {
  /** Looked up by name in session mode; ids differ between deployments. */
  table: string;
  datasetId: number;
  metric: string;
  /** The column the charts group by and the host filter narrows. */
  dimension: string;
  /** Values of `dimension` offered by the host's filter control. */
  values: string[];
}

/** Who a guest token is minted for; the broker knows exactly these two. */
export type Audience = 'a' | 'b';

const datasetId = integer(viteEnv.FILTER_DATASET_ID, 17);
const table = text(viteEnv.FILTER_DATASET_TABLE, 'birth_names');
const filterColumn = text(viteEnv.FILTER_COLUMN, 'state');
const metric = text(viteEnv.EMBED_METRIC, 'sum__num');

export const config = {
  supersetUrl: text(viteEnv.SUPERSET_URL, 'http://localhost:8088').replace(
    /\/+$/,
    '',
  ),
  // `session` uses the viewer's Superset login cookie; `guest` uses the token broker.
  authMode: (viteEnv.EMBED_AUTH === 'guest' ? 'guest' : 'session') as
    | 'guest'
    | 'session',
  savedWidgetIds: list(viteEnv.EMBED_WIDGET_IDS),
  /**
   * A uuid no saved widget has, for the gallery's `renderError` demo. Left
   * empty, the demo is not rendered and the page makes no request that is
   * bound to fail.
   */
  missingWidgetId: text(viteEnv.EMBED_MISSING_WIDGET_ID, ''),
  /**
   * A widget type contributed by a Superset extension, e.g.
   * `extensions.<publisher>.<name>.<type>`. Set it and the page renders one:
   * the provider fetches that extension from Superset and loads its code at
   * runtime. Left empty, no extension is referenced at all.
   */
  extensionWidgetType: text(viteEnv.EMBED_EXTENSION_WIDGET, ''),
  /** The locale the Arabic toggle switches to; only its direction is used. */
  rtlLocale: text(viteEnv.EMBED_RTL_LOCALE, 'ar'),
  table,
  datasetId,
  // The dataset's shape. Defaults describe Superset's own `birth_names`
  // example; point the app at another dataset and these are what you change.
  // `filterColumn` doubles as the dimension the charts group by — the host
  // filter only narrows them if they are grouped by the column it filters.
  filterColumn,
  filterValues: list(text(viteEnv.FILTER_VALUES, 'CA,NY,TX,IL,FL')),
  metric,
  /** A numeric column, for the ad hoc aggregate the saved metric demo contrasts with. */
  metricColumn: text(viteEnv.EMBED_METRIC_COLUMN, 'num'),
  secondMetric: text(viteEnv.EMBED_SECOND_METRIC, 'count'),
  /** A low-cardinality column, for the pie and the scoped filter. */
  category: text(viteEnv.EMBED_CATEGORY, 'gender'),
  categoryValues: list(text(viteEnv.EMBED_CATEGORY_VALUES, 'boy,girl')),
  /** A high-cardinality column, for the table's rows. */
  label: text(viteEnv.EMBED_LABEL, 'name'),
  /**
   * The second, independent provider of the isolation demo. Everything
   * defaults to the first provider's dataset, which already shows the point
   * (two filters, two tokens, one page); name another dataset to also show
   * two providers on different data.
   */
  second: {
    table: text(viteEnv.EMBED_B_DATASET_TABLE, table),
    datasetId: integer(viteEnv.EMBED_B_DATASET_ID, datasetId),
    metric: text(viteEnv.EMBED_B_METRIC, metric),
    dimension: text(viteEnv.EMBED_B_DIMENSION, filterColumn),
    values: list(
      text(viteEnv.EMBED_B_VALUES, text(viteEnv.FILTER_VALUES, 'CA,NY,TX')),
    ),
  } as DatasetShape,
};

/** The first provider's dataset, in the shape the isolation demo takes. */
export const firstShape = (): DatasetShape => ({
  table: config.table,
  datasetId: config.datasetId,
  metric: config.metric,
  dimension: config.filterColumn,
  values: config.filterValues,
});

/**
 * Asks the host's own backend (`server.mjs` here) for a guest token. The
 * browser never sees Superset credentials: it names an audience, and the
 * broker decides what a token for that audience may read.
 */
export async function fetchGuestToken(
  audience: Audience = 'a',
): Promise<string> {
  const response = await fetch(`/api/guest-token?audience=${audience}`, {
    method: 'POST',
  });
  const body = await response.text();
  if (!response.ok) {
    throw new Error(`Token broker responded ${response.status}: ${body}`);
  }
  return body;
}

/** The `SupersetProvider` props that authenticate `audience`. */
export const authFor = (audience: Audience) =>
  config.authMode === 'guest'
    ? {
        fetchGuestToken: () => fetchGuestToken(audience),
        // A different audience is a different token: the provider drops the
        // cached one and every widget fetches again.
        guestTokenKey: audience,
      }
    : {};

interface DatasetColumn {
  column_name: string;
  type_generic?: number;
}

interface DatasetDetails {
  columns: DatasetColumn[];
  metrics: { metric_name: string }[];
}

const NUMERIC = 0;
const STRING = 1;

async function read<T>(path: string): Promise<T | undefined> {
  try {
    const response = await fetch(`${config.supersetUrl}${path}`, {
      mode: 'cors',
      credentials: 'include',
    });
    if (!response.ok) return undefined;
    return ((await response.json()) as { result: T }).result;
  } catch {
    return undefined;
  }
}

/** Distinct values of a column, through the widget API rather than the dataset API. */
async function valuesOf(dataset: number, column: string): Promise<string[]> {
  try {
    const response = await fetch(`${config.supersetUrl}/api/v1/widget/values`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        widget: {
          type: 'filter.select',
          props: { datasetId: dataset, column },
        },
      }),
    });
    if (!response.ok) return [];
    const { result } = (await response.json()) as { result: unknown[] };
    return result.slice(0, 5).map(String);
  } catch {
    return [];
  }
}

async function datasetIdOf(name: string): Promise<number | undefined> {
  const query = `(filters:!((col:table_name,opr:eq,value:${name})),columns:!(id,table_name))`;
  const found = await read<{ id: number }[]>(
    `/api/v1/dataset/?q=${encodeURIComponent(query)}`,
  );
  return found?.length ? found[0].id : undefined;
}

const keep = <T>(value: T, available: T[], fallback: T | undefined): T =>
  available.includes(value) ? value : (fallback ?? value);

const named = (details: DatasetDetails, generic: number): string[] =>
  details.columns
    .filter(column => column.type_generic === generic)
    .map(column => column.column_name);

/** Makes `shape` name a dataset, a metric and a dimension that exist. */
async function resolveShape(shape: DatasetShape): Promise<void> {
  const target = shape;
  target.datasetId = (await datasetIdOf(shape.table)) ?? shape.datasetId;
  const details = await read<DatasetDetails>(
    `/api/v1/dataset/${target.datasetId}`,
  );
  if (!details) return;
  const strings = named(details, STRING);
  const metrics = details.metrics.map(entry => entry.metric_name);
  const dimension = keep(shape.dimension, strings, strings[0]);
  if (dimension !== shape.dimension || shape.values.length === 0) {
    target.dimension = dimension;
    target.values = await valuesOf(target.datasetId, dimension);
  }
  target.metric = keep(
    shape.metric,
    metrics,
    metrics.find(name => name !== 'count') ?? metrics[0],
  );
}

/**
 * Points the demo at datasets that can actually answer it.
 *
 * Dataset ids differ between deployments (and shift when Superset's examples
 * are reloaded), and a widget asking for a column its dataset does not have
 * fails its query — so the values above are a preference, not a promise.
 * Whatever the dataset turns out to hold wins. Guests cannot read the dataset
 * API, so guest mode keeps the configured values and relies on them being
 * right.
 */
export async function resolveDatasetShape(): Promise<void> {
  if (config.authMode === 'guest') return;

  config.datasetId = (await datasetIdOf(config.table)) ?? config.datasetId;
  const dataset = await read<DatasetDetails>(
    `/api/v1/dataset/${config.datasetId}`,
  );
  if (dataset) {
    const strings = named(dataset, STRING);
    const numbers = named(dataset, NUMERIC);
    const metrics = dataset.metrics.map(entry => entry.metric_name);

    const dimension = keep(config.filterColumn, strings, strings[0]);
    if (dimension !== config.filterColumn) {
      config.filterColumn = dimension;
      config.filterValues = await valuesOf(config.datasetId, dimension);
    }
    const category = keep(
      config.category,
      strings,
      strings.find(column => column !== dimension) ?? strings[0],
    );
    if (category !== config.category) {
      config.category = category;
      config.categoryValues = await valuesOf(config.datasetId, category);
    }
    config.label = keep(
      config.label,
      strings,
      strings.find(column => column !== dimension && column !== category) ??
        dimension,
    );
    config.metricColumn = keep(config.metricColumn, numbers, numbers[0]);
    config.metric = keep(
      config.metric,
      metrics,
      metrics.find(name => name !== 'count') ?? metrics[0],
    );
    config.secondMetric = keep(
      config.secondMetric,
      metrics,
      metrics.includes('count') ? 'count' : metrics[0],
    );
  }

  await resolveShape(config.second);
}
