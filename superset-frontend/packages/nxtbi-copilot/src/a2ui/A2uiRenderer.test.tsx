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
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import {
  A2uiRenderer,
  applyA2uiMessage,
  BASIC_A2UI_CATALOG_ID,
  initialA2uiState,
  NXTBI_A2UI_CATALOG_ID,
  parseA2uiMessage,
  updateA2uiData,
  type A2uiReactCatalog,
} from './index';

const form = {
  version: '1.0',
  createSurface: {
    surfaceId: 'form',
    catalogId: BASIC_A2UI_CATALOG_ID,
    components: [
      { id: 'root', component: 'Card', child: 'fields' },
      {
        id: 'fields',
        component: 'Column',
        children: ['title', 'name', 'submit'],
      },
      { id: 'title', component: 'Text', text: '# بيانات التقرير' },
      {
        id: 'name',
        component: 'TextField',
        label: 'الاسم',
        value: { '@path': '/fields/name' },
      },
      {
        id: 'submit',
        component: 'Button',
        child: 'submit_text',
        action: {
          event: {
            name: 'nxtbi.submit-form',
            context: { name: { '@path': '/fields/name' } },
          },
        },
      },
      { id: 'submit_text', component: 'Text', text: 'إرسال' },
    ],
    dataModel: { fields: { name: '' }, internal: 'not part of the event' },
  },
};

test('renders a localized form, tracks two-way bindings and dispatches only the selected action context', () => {
  const onAction = jest.fn();
  function Harness() {
    const [state, setState] = useState(() =>
      applyA2uiMessage(initialA2uiState, parseA2uiMessage(form)),
    );
    return (
      <A2uiRenderer
        state={state}
        locale="ar"
        allowedActions={['nxtbi.submit-form']}
        onAction={onAction}
        onDataChange={(id, path, value) =>
          setState(current => updateA2uiData(current, id, path, value))
        }
      />
    );
  }

  render(<Harness />);
  expect(
    screen.getByRole('heading', { name: 'بيانات التقرير' }).closest('[dir]'),
  ).toHaveAttribute('dir', 'rtl');
  fireEvent.change(screen.getByRole('textbox', { name: 'الاسم' }), {
    target: { value: 'ليلى' },
  });
  fireEvent.click(screen.getByRole('button', { name: 'إرسال' }));
  expect(onAction).toHaveBeenCalledWith({
    version: '1.0',
    action: {
      name: 'nxtbi.submit-form',
      surfaceId: 'form',
      sourceComponentId: 'submit',
      timestamp: expect.stringMatching(/^\d{4}-\d\d-\d\dT/),
      context: { name: 'ليلى' },
    },
  });
});

test('composes a templated list, a registered component, and a table on one surface', () => {
  const host: A2uiReactCatalog = {
    id: 'urn:host:status',
    components: {
      HostStatus: {
        validate(props) {
          if (Object.keys(props).join() !== 'label')
            throw new Error('Invalid properties');
        },
      },
    },
    renderers: {
      HostStatus: ({ props }) => <strong>{String(props.label)}</strong>,
    },
  };
  const catalogs = [host];
  const state = applyA2uiMessage(
    initialA2uiState,
    parseA2uiMessage(
      {
        version: '1.0',
        createSurface: {
          surfaceId: 'metrics',
          catalogId: BASIC_A2UI_CATALOG_ID,
          components: [
            {
              id: 'root',
              component: 'Column',
              children: ['list', 'table', 'literal'],
            },
            {
              id: 'list',
              component: 'List',
              children: { path: '/rows', componentId: 'item' },
            },
            {
              id: 'item',
              component: 'HostStatus',
              '@catalogId': host.id,
              label: { '@path': 'name' },
            },
            {
              id: 'table',
              component: 'Table',
              '@catalogId': NXTBI_A2UI_CATALOG_ID,
              columns: [{ key: 'value', label: 'Amount' }],
              rows: { '@path': '/rows' },
            },
            {
              id: 'literal',
              component: 'Text',
              text: '<img src="https://example.com">',
            },
          ],
          dataModel: {
            rows: [
              { name: 'North', value: 12 },
              { name: 'South', value: 19 },
            ],
          },
        },
      },
      catalogs,
    ),
    catalogs,
  );
  const { container } = render(
    <A2uiRenderer state={state} catalogs={catalogs} />,
  );
  expect(screen.getByText('North')).toBeVisible();
  expect(screen.getByText('South')).toBeVisible();
  expect(screen.getByRole('columnheader', { name: 'Amount' })).toBeVisible();
  expect(screen.getByRole('cell', { name: '19' })).toBeVisible();
  expect(screen.getByText('<img src="https://example.com">')).toBeVisible();
  expect(container.querySelector('img')).toBeNull();
});

test('never dispatches actions excluded by the host', () => {
  const onAction = jest.fn();
  const state = applyA2uiMessage(initialA2uiState, parseA2uiMessage(form));
  render(
    <A2uiRenderer
      state={state}
      locale="ar"
      allowedActions={[]}
      onAction={onAction}
    />,
  );
  const button = screen.getByRole('button', { name: 'إرسال' });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(onAction).not.toHaveBeenCalled();
});

test('uses selector and checkbox state to enable and populate an action', () => {
  const onAction = jest.fn();
  const message = parseA2uiMessage({
    version: '1.0',
    createSurface: {
      surfaceId: 'selectors',
      components: [
        { id: 'root', component: 'Column', children: ['regions', 'confirmed', 'apply'] },
        {
          id: 'regions',
          component: 'ChoicePicker',
          label: 'Regions',
          variant: 'multipleSelection',
          options: [{ label: 'North', value: 'north' }, { label: 'South', value: 'south' }],
          value: { '@path': '/regions' },
        },
        { id: 'confirmed', component: 'CheckBox', label: 'Confirm selection', value: { '@path': '/confirmed' } },
        {
          id: 'apply',
          component: 'Button',
          child: 'buttonLabel',
          '@checks': [{ condition: { '@path': '/confirmed' } }],
          action: { event: { name: 'apply-selection', context: { regions: { '@path': '/regions' } } } },
        },
        { id: 'buttonLabel', component: 'Text', text: 'Apply selection' },
      ],
      dataModel: { regions: [], confirmed: false },
    },
  });
  function Harness() {
    const [state, setState] = useState(() => applyA2uiMessage(initialA2uiState, message));
    return <A2uiRenderer state={state} onAction={onAction}
      onDataChange={(id, path, value) => setState(current => updateA2uiData(current, id, path, value))} />;
  }

  render(<Harness />);
  const apply = screen.getByRole('button', { name: 'Apply selection' });
  expect(apply).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'North' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'South' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Confirm selection' }));
  fireEvent.click(apply);
  expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
    action: expect.objectContaining({ context: { regions: ['north', 'south'] } }),
  }));
});
