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

import type { LatestQueryFormData } from '@superset-ui/core';
import { metricTileSnippet } from './WidgetSdkEmbed';

const budgetTotal: LatestQueryFormData = {
  datasource: '12__table',
  viz_type: 'big_number_total',
  metric: 'allocated',
  subtitle: 'Allocated | المخصص',
  row_limit: 10000,
  adhoc_filters: [
    {
      expressionType: 'SIMPLE',
      clause: 'WHERE',
      subject: 'month',
      operator: 'TEMPORAL_RANGE',
      comparator: 'No filter',
    },
  ],
  extra_form_data: {},
};

test('exports the allocated budget as a session-authenticated SDK metric tile', () => {
  const snippet = metricTileSnippet(budgetTotal);
  expect(snippet).toContain("from '@apache-superset/widgets'");
  expect(snippet).toContain('"datasetId":12,"metrics":["allocated"]');
  expect(snippet).toContain('Allocated | المخصص');
});

test.each(['native_filters_key', 'slice_id'])(
  'accepts navigation-only chart URL parameter %s',
  key => {
    expect(
      metricTileSnippet({ ...budgetTotal, url_params: { [key]: '105' } }),
    ).toContain('MetricTile');
  },
);

test.each<LatestQueryFormData>([
  { url_params: { native_filters_key: 'key', region: 'East' } },
  {
    url_params: { native_filters_key: 'key' },
    extra_form_data: { filters: [{ col: 'region', op: 'IN', val: ['East'] }] },
  },
  {
    adhoc_filters: [
      { expressionType: 'SQL', clause: 'WHERE', sqlExpression: 'amount > 100' },
    ],
  },
  { time_range: 'Last year' },
  { viz_type: 'big_number' },
  { datasource: '12__semantic_view' },
  { metric: { expressionType: 'SQL', sqlExpression: 'count(*)' } },
])('withholds a snippet when the SDK query would differ', override => {
  expect(metricTileSnippet({ ...budgetTotal, ...override })).toBeUndefined();
});
