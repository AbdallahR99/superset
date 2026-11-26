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
import { SupersetClient } from '@superset-ui/core';
import { fetchQueryData } from './chartData';

const grouped = {
  datasetId: 1,
  dimensions: ['month', 'district'],
  metrics: ['count', 'revenue'],
  rowLimit: 12,
};

function mockQuery() {
  return jest.spyOn(SupersetClient, 'post').mockResolvedValue({
    response: new Response(),
    json: { result: [{}] },
  });
}

afterEach(() => jest.restoreAllMocks());

test('ranks by the saved metric and breaks ties by the grouping columns', async () => {
  const post = mockQuery();
  await fetchQueryData({ ...grouped, orderByMetric: true });
  expect(post).toHaveBeenCalledWith(
    expect.objectContaining({
      endpoint: '/api/v1/chart/data',
      jsonPayload: expect.objectContaining({
        queries: [
          expect.objectContaining({
            orderby: [
              ['count', false],
              ['month', true],
              ['district', true],
            ],
            row_limit: 12,
          }),
        ],
      }),
    }),
  );
});

test('explicit dimension ordering takes precedence over ranking', async () => {
  const post = mockQuery();
  await fetchQueryData({
    ...grouped,
    orderByMetric: true,
    orderByDimension: true,
  });
  expect(post.mock.calls[0][0].jsonPayload).toMatchObject({
    queries: [
      {
        orderby: [
          ['month', true],
          ['district', true],
        ],
      },
    ],
  });
});

test.each([
  { ...grouped },
  { ...grouped, dimensions: [], orderByMetric: true },
  {
    ...grouped,
    metrics: [
      {
        expressionType: 'SIMPLE',
        aggregate: 'COUNT',
        column: { column_name: 'district' },
        label: 'Rows',
      },
      'count',
    ],
    orderByMetric: true,
  },
])(
  'does not add ranking without an opt-in grouped saved metric',
  async binding => {
    const post = mockQuery();
    await fetchQueryData(binding);
    expect(post.mock.calls[0][0].jsonPayload).toMatchObject({
      queries: [expect.not.objectContaining({ orderby: expect.any(Array) })],
    });
  },
);
