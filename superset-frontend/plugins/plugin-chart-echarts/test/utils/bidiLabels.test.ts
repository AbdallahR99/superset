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
import {
  ChartProps,
  getNumberFormatter,
  SqlaFormData,
} from '@superset-ui/core';
import { supersetTheme } from '@apache-superset/core/theme';
import {
  addTranslation,
  configure,
  resetTranslation,
} from '@apache-superset/core/translation';
import type { PieSeriesOption } from 'echarts/charts';
import type {
  CallbackDataParams,
  LabelFormatterCallback,
} from 'echarts/types/src/util/types';
import transformPieProps from '../../src/Pie/transformProps';
import { EchartsPieChartProps } from '../../src/Pie/types';
import { formatLabel as formatSunburstLabel } from '../../src/Sunburst/transformProps';
import { EchartsSunburstLabelType } from '../../src/Sunburst/types';
import { formatLabel as formatTreemapLabel } from '../../src/Treemap/transformProps';
import { EchartsTreemapLabelType } from '../../src/Treemap/types';
import { FSI, LRI, PDI } from '../../src/utils/bidi';

const ARABIC = 'الصحة';
const numberFormatter = getNumberFormatter(',d');

const pieParams: CallbackDataParams = {
  componentType: '',
  componentSubType: '',
  componentIndex: 0,
  seriesType: 'pie',
  seriesIndex: 0,
  seriesId: 'seriesId',
  seriesName: 'test',
  name: ARABIC,
  dataIndex: 0,
  data: {},
  value: 1234,
  percent: 19.11,
  $vars: [],
};

const formatPieLabel = (
  form: Partial<SqlaFormData>,
  params: CallbackDataParams = pieParams,
) => {
  const formData: SqlaFormData = {
    colorScheme: 'bnbColors',
    datasource: '3__table',
    granularity_sqla: 'ds',
    metric: 'sum__num',
    groupby: ['foo'],
    viz_type: 'pie',
    number_format: ',d',
    ...form,
  };
  const { echartOptions } = transformPieProps(
    new ChartProps({
      formData,
      width: 800,
      height: 600,
      queriesData: [{ data: [{ foo: ARABIC, sum__num: 1234 }] }],
      theme: supersetTheme,
    }) as EchartsPieChartProps,
  );
  const formatter = (echartOptions.series as PieSeriesOption[])[0].label
    ?.formatter as LabelFormatterCallback;
  return formatter(params);
};

test('treemap and sunburst labels isolate a right-to-left name from its value', () => {
  const expected = `${FSI}${ARABIC}${PDI}: ${LRI}1,234${PDI}`;
  expect(
    formatTreemapLabel({
      params: { name: ARABIC, value: 1234 } as never,
      labelType: EchartsTreemapLabelType.KeyValue,
      numberFormatter,
    }),
  ).toBe(expected);
  expect(
    formatSunburstLabel({
      params: { name: ARABIC, value: 1234 } as CallbackDataParams,
      labelType: EchartsSunburstLabelType.KeyValue,
      numberFormatter,
    }),
  ).toBe(expected);
});

test('treemap and sunburst labels are unchanged for left-to-right names', () => {
  expect(
    formatTreemapLabel({
      params: { name: 'Health', value: 1234 } as never,
      labelType: EchartsTreemapLabelType.KeyValue,
      numberFormatter,
    }),
  ).toBe('Health: 1,234');
  expect(
    formatSunburstLabel({
      params: { name: 'Health', value: 1234 } as CallbackDataParams,
      labelType: EchartsSunburstLabelType.KeyValue,
      numberFormatter,
    }),
  ).toBe('Health: 1,234');
});

test('single-part labels carry no isolates', () => {
  expect(
    formatTreemapLabel({
      params: { name: ARABIC, value: 1234 } as never,
      labelType: EchartsTreemapLabelType.Key,
      numberFormatter,
    }),
  ).toBe(ARABIC);
  expect(
    formatTreemapLabel({
      params: { name: ARABIC, value: 1234 } as never,
      labelType: EchartsTreemapLabelType.Value,
      numberFormatter,
    }),
  ).toBe('1,234');
});

test('pie labels isolate a right-to-left category from value and percent', () => {
  expect(formatPieLabel({ label_type: 'key_percent' })).toBe(
    `${FSI}${ARABIC}${PDI}: ${LRI}19.11%${PDI}`,
  );
  expect(formatPieLabel({ label_type: 'key_value_percent' })).toBe(
    `${FSI}${ARABIC}${PDI}: ${LRI}1,234${PDI} (${LRI}19.11%${PDI})`,
  );
});

test('pie labels are unchanged for left-to-right categories', () => {
  const params = { ...pieParams, name: 'Health' };
  expect(formatPieLabel({ label_type: 'key_percent' }, params)).toBe(
    'Health: 19.11%',
  );
  expect(formatPieLabel({ label_type: 'key_value_percent' }, params)).toBe(
    'Health: 1,234 (19.11%)',
  );
});

test('pie label templates isolate their values and keep line breaks', () => {
  expect(
    formatPieLabel({
      label_type: 'template',
      label_template: '{name}: {value}\\n{percent}',
    }),
  ).toBe(`${FSI}${ARABIC}${PDI}: ${LRI}1,234${PDI}\n${LRI}19.11%${PDI}`);
  expect(
    formatPieLabel(
      {
        label_type: 'template',
        label_template: '{name}: {value}\\n{percent}',
      },
      { ...pieParams, name: 'Health' },
    ),
  ).toBe('Health: 1,234\n19.11%');
});

const pieTotalText = () => {
  const { echartOptions } = transformPieProps(
    new ChartProps({
      formData: {
        colorScheme: 'bnbColors',
        datasource: '3__table',
        granularity_sqla: 'ds',
        metric: 'sum__num',
        groupby: ['foo'],
        viz_type: 'pie',
        number_format: ',d',
        show_total: true,
      },
      width: 800,
      height: 600,
      queriesData: [{ data: [{ foo: 'Health', sum__num: 1234 }] }],
      theme: supersetTheme,
    }) as unknown as EchartsPieChartProps,
  );
  return (echartOptions.graphic as { style: { text: string } }).style.text;
};

test('pie total is unchanged in a left-to-right language', () => {
  expect(pieTotalText()).toBe('Total: 1,234');
});

test('pie total keeps the number together in a right-to-left language', () => {
  configure();
  addTranslation('Total: %s', ['الإجمالي: %s']);
  try {
    expect(pieTotalText()).toBe(`${FSI}الإجمالي: ${LRI}1,234${PDI}${PDI}`);
  } finally {
    resetTranslation();
  }
});
