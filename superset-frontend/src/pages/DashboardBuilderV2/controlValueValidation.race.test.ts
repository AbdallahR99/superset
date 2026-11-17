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
import DashboardProvider from 'src/core/dashboard/DashboardProvider';
import { commitWidgetProps } from './controlValueValidation';

const provider = DashboardProvider.getInstance();
const postSpy = jest.spyOn(SupersetClient, 'post');

type ValidationResponse = Awaited<ReturnType<typeof SupersetClient.post>>;

/** A validation request that answers only when the test says so. */
const pendingValidation = () => {
  let answer: (values: Record<string, unknown> | null) => void = () => {};
  postSpy.mockReturnValue(
    new Promise<ValidationResponse>(resolve => {
      answer = values =>
        resolve({
          json: { result: { errors: [], values } },
        } as unknown as ValidationResponse);
    }),
  );
  return (values: Record<string, unknown> | null) => answer(values);
};

beforeEach(() => {
  provider.reset();
  postSpy.mockReset();
});

const mount = (props: Record<string, unknown>) =>
  provider.addWidget(provider.getRoot().id, 0, { type: 'metric-tile', props });

test('a prop written while validation was in flight is not reverted by the commit', async () => {
  const id = mount({ datasetId: 1, label: 'Before' });
  const answer = pendingValidation();

  const committing = commitWidgetProps(id, 'metric-tile', { label: 'After' });
  // Saving the widget for embedding writes its id while the label is still
  // being validated.
  provider.updateProps(id, { embedWidgetId: 'uuid-1' });
  answer({ datasetId: 1, label: 'After' });
  await committing;

  expect(provider.getNode(id)?.props).toEqual({
    datasetId: 1,
    label: 'After',
    embedWidgetId: 'uuid-1',
  });
});

test('a different control committed meanwhile keeps its value', async () => {
  const id = mount({ datasetId: 1, label: 'Before', metrics: ['count'] });
  const answer = pendingValidation();

  const committing = commitWidgetProps(id, 'metric-tile', { label: 'After' });
  provider.updateProps(id, { metrics: ['sum'] });
  // Validated against the props as they were, so it still says `count`.
  answer({ datasetId: 1, label: 'After', metrics: ['count'] });
  await committing;

  expect(provider.getNode(id)?.props).toMatchObject({
    label: 'After',
    metrics: ['sum'],
  });
});

test('the key the commit is about wins over a concurrent write to the same key', async () => {
  const id = mount({ label: 'Before' });
  const answer = pendingValidation();

  const committing = commitWidgetProps(id, 'metric-tile', { label: 'Mine' });
  provider.updateProps(id, { label: 'Theirs' });
  answer({ label: 'Mine' });
  await committing;

  expect(provider.getNode(id)?.props?.label).toBe('Mine');
});

test('a commit started before the dashboard was reloaded does not write into the reloaded copy', async () => {
  // The same ids before and after, as a reload of one dashboard gives.
  const stored = {
    root: { type: 'grid', children: ['node_3'] },
    node_3: { type: 'metric-tile', props: { label: 'Saved' } },
  };
  provider.loadDocument(stored);
  const answer = pendingValidation();

  const committing = commitWidgetProps('node_3', 'metric-tile', {
    label: 'Discarded edit',
  });
  // The author chooses to discard their edits and reload.
  provider.loadDocument(stored);
  const versionAfterReload = provider.getDocumentVersion();
  answer({ label: 'Discarded edit' });

  await expect(committing).resolves.toEqual({ ok: false, errors: [] });
  expect(provider.getNode('node_3')?.props).toEqual({ label: 'Saved' });
  // Nothing was written, so the reloaded dashboard is not dirty.
  expect(provider.getDocumentVersion()).toBe(versionAfterReload);
});

test('a commit started on one dashboard does not write into a node of the same id on another', async () => {
  provider.loadDocument({
    root: { type: 'grid', children: ['node_1'] },
    node_1: { type: 'metric-tile', props: { label: 'On dashboard A' } },
  });
  const answer = pendingValidation();

  const committing = commitWidgetProps('node_1', 'metric-tile', {
    label: 'Edit made on A',
  });
  provider.loadDocument({
    root: { type: 'grid', children: ['node_1'] },
    node_1: { type: 'markdown', props: { content: 'On dashboard B' } },
  });
  answer({ label: 'Edit made on A' });

  await expect(committing).resolves.toEqual({ ok: false, errors: [] });
  expect(provider.getNode('node_1')).toMatchObject({
    type: 'markdown',
    props: { content: 'On dashboard B' },
  });
});

test('validation errors about a dashboard that is no longer on screen are not reported', async () => {
  provider.loadDocument({
    root: { type: 'grid', children: ['node_1'] },
    node_1: { type: 'metric-tile', props: {} },
  });
  let reject: (
    errors: { loc: (string | number)[]; message: string }[],
  ) => void = () => {};
  postSpy.mockReturnValue(
    new Promise<ValidationResponse>(resolve => {
      reject = errors =>
        resolve({
          json: { result: { errors, values: null } },
        } as unknown as ValidationResponse);
    }),
  );

  const committing = commitWidgetProps('node_1', 'metric-tile', { label: 1 });
  provider.newDocument();
  reject([{ loc: ['label'], message: 'Must be text' }]);

  await expect(committing).resolves.toEqual({ ok: false, errors: [] });
});

test('a commit on a blank dashboard that was replaced by another blank one is dropped too', async () => {
  const id = mount({ label: 'Before' });
  const answer = pendingValidation();

  const committing = commitWidgetProps(id, 'metric-tile', { label: 'After' });
  provider.newDocument();
  answer({ label: 'After' });

  await expect(committing).resolves.toEqual({ ok: false, errors: [] });
  expect(provider.getNode(id)).toBeUndefined();
});

test('a node removed while validation was in flight is not written to, and nothing throws', async () => {
  const id = mount({ label: 'Before' });
  const answer = pendingValidation();

  const committing = commitWidgetProps(id, 'metric-tile', { label: 'After' });
  provider.removeWidget(id);
  answer({ label: 'After' });

  await expect(committing).resolves.toEqual({ ok: false, errors: [] });
  expect(provider.getNode(id)).toBeUndefined();
});
