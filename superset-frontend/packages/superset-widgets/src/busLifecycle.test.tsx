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
import { StrictMode, useContext, useEffect, type ReactNode } from 'react';
import { dashboard as dashboardApi } from '@apache-superset/core';
import { act, render, screen, waitFor } from 'spec/helpers/testing-library';
import { getActiveResolvedFilters } from './activeFilters';
import { WidgetBusContext, createWidgetBus } from './bus';
import { WidgetDataClientContext } from './dataClient';
import { WidgetApplySourceContext } from './deferredApply';
import { Widget } from './embed/Widget';
import { useWidgetEvent, useWidgetValue } from './embed/hooks';
import { FILTER_BAR_APPLY_EVENT } from './filterVocabulary';
import type { FilterValueChangedPayload } from './filterVocabulary';
import { registerWidgetComponent } from './registry';
import type { WidgetBus, WidgetDataClient, WidgetProps } from './types';

const EVENT = dashboardApi.VALUE_CHANGED_EVENT;
const WEST: FilterValueChangedPayload = {
  selection: 'west',
  resolved: {
    column: 'region',
    operator: 'EQUALS',
    value: 'west',
    datasource: 1,
  },
};

const client: WidgetDataClient = {
  fetchData: jest.fn(async () => ({ columns: [], rows: [] })),
  fetchValues: jest.fn(async () => []),
};

const inPage = (bus: WidgetBus, ui: ReactNode) => (
  <WidgetBusContext.Provider value={bus}>
    <WidgetDataClientContext.Provider value={client}>
      {ui}
    </WidgetDataClientContext.Provider>
  </WidgetBusContext.Provider>
);

/** Emits a filter under whatever id it was given, and shows that id. */
function Emitter({ instanceId }: WidgetProps) {
  const bus = useContext(WidgetBusContext) as WidgetBus;
  useEffect(() => {
    bus.emit(instanceId, EVENT, WEST);
  }, [bus, instanceId]);
  return <span data-test="emitter">{instanceId}</span>;
}

registerWidgetComponent('test.emitter', Emitter);

test('two buses share no value, source, listener or revision', () => {
  const left = createWidgetBus();
  const right = createWidgetBus();
  const heard: string[] = [];
  right.on(EVENT, event => heard.push(event.nodeId));
  const rightTicks = jest.fn();
  right.subscribe(rightTicks);

  left.emit('filter', EVENT, WEST);

  expect(left.getValue('filter', EVENT)).toEqual(WEST);
  expect(right.getValue('filter', EVENT)).toBeUndefined();
  expect(right.getSourceIds(EVENT)).toEqual([]);
  expect(getActiveResolvedFilters(right, 1, 'chart')).toEqual([]);
  expect(heard).toEqual([]);
  expect(rightTicks).not.toHaveBeenCalled();
  expect(right.getRevision()).toBe(0);
});

test('a forgotten source stops filtering and subscribers are told once', () => {
  const bus = createWidgetBus();
  bus.emit('filter', EVENT, WEST);
  bus.emit('filter', 'other', 1);
  const ticks = jest.fn();
  bus.subscribe(ticks);

  bus.forget?.('filter');

  expect(bus.getSourceIds(EVENT)).toEqual([]);
  expect(bus.getValue('filter', EVENT)).toBeUndefined();
  expect(bus.getValue('filter', 'other')).toBeUndefined();
  expect(getActiveResolvedFilters(bus, 1, 'chart')).toEqual([]);
  expect(ticks).toHaveBeenCalledTimes(1);

  // Forgetting what was never there is silent.
  bus.forget?.('filter');
  bus.forget?.('never');
  expect(ticks).toHaveBeenCalledTimes(1);
});

test('a listener that throws does not stop the others or the emitter', () => {
  const bus = createWidgetBus();
  const consoleError = jest.spyOn(console, 'error').mockImplementation();
  const heard = jest.fn();
  const ticks = jest.fn();
  bus.on(EVENT, () => {
    throw new Error('listener bug');
  });
  bus.on(EVENT, heard);
  bus.subscribe(() => {
    throw new Error('subscriber bug');
  });
  bus.subscribe(ticks);

  expect(() => bus.emit('filter', EVENT, WEST)).not.toThrow();

  expect(heard).toHaveBeenCalledTimes(1);
  expect(ticks).toHaveBeenCalledTimes(1);
  expect(bus.getValue('filter', EVENT)).toEqual(WEST);
  consoleError.mockRestore();
});

test('a listener may unsubscribe itself, or another, while an event is delivered', () => {
  const bus = createWidgetBus();
  const second = jest.fn();
  let secondSubscription = { dispose: () => {} };
  const first = bus.on(EVENT, () => {
    first.dispose();
    secondSubscription.dispose();
  });
  secondSubscription = bus.on(EVENT, second);

  bus.emit('a', EVENT, WEST);
  bus.emit('a', EVENT, WEST);

  // Delivered to both for the event in flight, to neither afterwards.
  expect(second).toHaveBeenCalledTimes(1);
});

test('widgets in separate React roots on one shared bus get ids of their own', async () => {
  const bus = createWidgetBus();
  const first = document.body.appendChild(document.createElement('div'));
  const second = document.body.appendChild(document.createElement('div'));

  // Two roots: `useId` hands the same id to the first component of each.
  render(inPage(bus, <Widget type="test.emitter" />), { container: first });
  render(inPage(bus, <Widget type="test.emitter" />), { container: second });

  await waitFor(() => expect(bus.getSourceIds(EVENT)).toHaveLength(2));
  const [one, two] = screen
    .getAllByTestId('emitter')
    .map(element => element.textContent);
  expect(one).not.toBe(two);
  // Each is filtered by the other, and by neither's own selection.
  expect(getActiveResolvedFilters(bus, 1, one as string)).toHaveLength(1);
  expect(getActiveResolvedFilters(bus, 1, two as string)).toHaveLength(1);
});

test('a widget that unmounts is forgotten by the bus; hooks unsubscribe', async () => {
  const bus = createWidgetBus();
  const heard: string[] = [];
  function Listener() {
    useWidgetEvent(EVENT, event => heard.push(event.nodeId));
    const value = useWidgetValue('w1') as FilterValueChangedPayload | undefined;
    return <span>{value?.resolved ? 'w1 filters' : 'w1 idle'}</span>;
  }
  const page = (withWidget: boolean, withListener: boolean) =>
    inPage(
      bus,
      <>
        {withListener && <Listener />}
        {withWidget && <Widget type="test.emitter" instanceId="w1" />}
      </>,
    );

  const { rerender } = render(page(true, true));
  expect(await screen.findByText('w1 filters')).toBeInTheDocument();
  expect(heard).toEqual(['w1']);

  rerender(page(false, true));
  expect(await screen.findByText('w1 idle')).toBeInTheDocument();
  expect(bus.getSourceIds(EVENT)).toEqual([]);

  rerender(page(false, false));
  act(() => bus.emit('later', EVENT, WEST));
  expect(heard).toEqual(['w1']);
});

const selectProps = (targets: string[]) => ({
  datasetId: 1,
  column: 'region',
  options: ['west', 'east'],
  defaultSelection: ['west'],
  scope: { targets },
});

test('a filter applies its default once, also when strict mode replays its effects', async () => {
  const bus = createWidgetBus();

  render(
    <StrictMode>
      {inPage(
        bus,
        <Widget type="filter.select" props={selectProps([])} instanceId="f1" />,
      )}
    </StrictMode>,
  );

  await waitFor(() =>
    expect(bus.getValue('f1', EVENT)).toEqual({
      selection: ['west'],
      resolved: {
        column: 'region',
        operator: 'EQUALS',
        value: 'west',
        datasource: 1,
      },
    }),
  );
  expect(getActiveResolvedFilters(bus, 1, 'chart')).toHaveLength(1);
});

test('a deferred filter applies with the scope it has when Apply is pressed, not when it was drawn', async () => {
  const bus = createWidgetBus();
  // The author's default is applied on mount; a later Apply carries whatever
  // the filter is scoped to at that moment.
  const page = (targets: string[]) =>
    inPage(
      bus,
      <WidgetApplySourceContext.Provider value="bar">
        <Widget
          type="filter.select"
          props={selectProps(targets)}
          instanceId="f1"
        />
      </WidgetApplySourceContext.Provider>,
    );
  const { rerender } = render(page(['chart-a']));
  await waitFor(() => expect(bus.getValue('f1', EVENT)).toBeDefined());
  expect(
    (bus.getValue('f1', EVENT) as FilterValueChangedPayload).targets,
  ).toEqual(['chart-a']);

  // Pick a value: held until Apply.
  const { default: userEvent } = await import('@testing-library/user-event');
  await userEvent.click(screen.getByRole('combobox'));
  await userEvent.click(await screen.findByTitle('east'));
  expect(
    (bus.getValue('f1', EVENT) as FilterValueChangedPayload).selection,
  ).toEqual(['west']);

  // The scope is edited while the selection is pending.
  rerender(page(['chart-b']));
  act(() => bus.emit('bar', FILTER_BAR_APPLY_EVENT, undefined));

  expect(bus.getValue('f1', EVENT)).toEqual({
    selection: ['west', 'east'],
    resolved: {
      column: 'region',
      operator: 'IN',
      value: ['west', 'east'],
      datasource: 1,
    },
    targets: ['chart-b'],
  });
});
