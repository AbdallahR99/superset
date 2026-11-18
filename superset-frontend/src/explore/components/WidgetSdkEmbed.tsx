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
import { buildQueryContext, LatestQueryFormData } from '@superset-ui/core';
import { t } from '@apache-superset/core/translation';
import { ModalTrigger, Typography } from '@superset-ui/core/components';
import { isEqual } from 'lodash-es';
import { URL_PARAMS } from 'src/constants';
import { AppLink, getShareableUrl } from 'src/utils/navigationUtils';

/** Export a metric only when the chart compiles to the same unfiltered query. */
export function metricTileSnippet(formData?: LatestQueryFormData) {
  const datasource = formData?.datasource;
  const vizType = formData?.viz_type;
  const metric: unknown = formData?.metric;
  if (
    !formData ||
    !datasource ||
    vizType !== 'big_number_total' ||
    !/^[1-9]\d*__table$/.test(datasource) ||
    typeof metric !== 'string' ||
    !metric
  )
    return undefined;

  const datasetId = Number(datasource.split('__')[0]);
  if (!Number.isSafeInteger(datasetId)) return undefined;
  const total = { datasource, viz_type: vizType, metric };
  const noFilters = formData.adhoc_filters?.filter(
    filter =>
      filter.expressionType === 'SIMPLE' &&
      filter.clause === 'WHERE' &&
      filter.operator === 'TEMPORAL_RANGE' &&
      filter.comparator === 'No filter',
  );
  // Big Number Total uses buildQueryContext without further transformations.
  // Compare its effective query so dashboard overrides cannot be dropped.
  const expected = buildQueryContext({
    ...total,
    // The classic dashboard and Explore carry their navigation identifiers
    // into chart requests. Native filter values are checked in the query.
    url_params: Object.fromEntries(
      Object.entries(formData.url_params ?? {}).filter(
        ([key]) =>
          key === URL_PARAMS.nativeFiltersKey.name ||
          key === URL_PARAMS.sliceId.name,
      ),
    ),
    adhoc_filters: noFilters,
    time_range: formData.time_range === 'No filter' ? 'No filter' : undefined,
    row_limit: Number(formData.row_limit) > 0 ? formData.row_limit : undefined,
    order_desc: formData.order_desc,
  });
  const actual = buildQueryContext({
    ...formData,
    datasource,
    viz_type: vizType,
  });
  if (!isEqual(expected.queries, actual.queries)) return undefined;

  const props = {
    dataBinding: { datasetId, metrics: [metric] },
    ...(typeof formData.subtitle === 'string' && { label: formData.subtitle }),
  };
  const domain = getShareableUrl('/').replace(/\/$/, '');
  return [
    "import { MetricTile, SupersetProvider } from '@apache-superset/widgets';",
    '',
    'export default function EmbeddedMetric() {',
    '  return (',
    `    <SupersetProvider supersetDomain={${JSON.stringify(domain)}}>`,
    `      <MetricTile {...${JSON.stringify(props)}} />`,
    '    </SupersetProvider>',
    '  );',
    '}',
  ].join('\n');
}

function WidgetSdkContent({ formData }: { formData?: LatestQueryFormData }) {
  const snippet = metricTileSnippet(formData);
  return snippet ? (
    <>
      <Typography.Paragraph>
        {t(
          'This React metric tile queries the same saved metric using the Superset session of the viewer. The SDK controls its number formatting and appearance.',
        )}
      </Typography.Paragraph>
      <Typography.Paragraph copyable={{ text: snippet }}>
        <pre dir="ltr">{snippet}</pre>
      </Typography.Paragraph>
    </>
  ) : (
    <Typography.Paragraph>
      {t(
        'SDK export from classic charts supports Big Number Total with one saved metric and no active filters. To embed a different visualization, create a widget in Dashboard V2 and choose Embed widget.',
      )}{' '}
      <AppLink href="/dashboard/v2/new/">{t('Open Dashboard V2')}</AppLink>
    </Typography.Paragraph>
  );
}

export default function WidgetSdkEmbed({
  formData,
}: {
  formData?: LatestQueryFormData;
}) {
  return (
    <ModalTrigger
      triggerNode={<span>{t('Embed with Widget SDK')}</span>}
      modalTitle={t('Embed with Widget SDK')}
      modalBody={<WidgetSdkContent formData={formData} />}
      responsive
    />
  );
}
