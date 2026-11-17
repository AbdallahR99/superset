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
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { COLUMN_SETTINGS } from './AgGridTableWidget';
import {
  DOM_EVENTS,
  ECHARTS_FORBIDDEN_KEYS,
  ECHARTS_OPTION_KEYS,
  ECHARTS_TOOLBOX_FEATURES,
} from './echartsSafety';

// The server's rules, read from the module that enforces them rather than
// from a copy kept here: what this file guards against is the two lists
// drifting apart, and a copy would drift with them.
const SERVER_RULES = readFileSync(
  resolve(__dirname, '../../../../../superset/widgets/safety.py'),
  'utf8',
);

const quoted = (source: string): string[] =>
  [...source.matchAll(/"([^"]+)"/g)].map(match => match[1]);

/** The members of `NAME = frozenset({...})` in the server module. */
function serverSet(name: string): string[] {
  const match = new RegExp(
    `^${name} = frozenset\\(\\s*\\{([^}]*)\\}`,
    'm',
  ).exec(SERVER_RULES);
  if (!match) throw new Error(`${name} was not found in safety.py`);
  return quoted(match[1]).sort();
}

/** The entries of the server's `AG_GRID_COLUMN_SETTINGS`, as `[key, type]`. */
function serverColumnSettings(): [string, string][] {
  const match = /^AG_GRID_COLUMN_SETTINGS: [^=]+= \{([^}]*)\}/m.exec(
    SERVER_RULES,
  );
  if (!match) {
    throw new Error('AG_GRID_COLUMN_SETTINGS was not found in safety.py');
  }
  return [...match[1].matchAll(/"(\w+)":\s*(\w+)/g)].map(
    ([, key, type]): [string, string] => [key, type],
  );
}

test('the top-level ECharts components drawn are exactly the ones the server stores', () => {
  const server = serverSet('ECHARTS_OPTION_KEYS');

  expect(server.length).toBeGreaterThan(30);
  expect([...ECHARTS_OPTION_KEYS].sort()).toEqual(server);
});

test('the toolbox features drawn are exactly the ones the server stores', () => {
  expect([...ECHARTS_TOOLBOX_FEATURES].sort()).toEqual(
    serverSet('ECHARTS_TOOLBOX_FEATURES'),
  );
  expect([...ECHARTS_TOOLBOX_FEATURES].sort()).toEqual([
    'dataZoom',
    'magicType',
    'restore',
    'saveAsImage',
  ]);
});

test('every key the server forbids at any depth is dropped at any depth', () => {
  expect([...ECHARTS_FORBIDDEN_KEYS].sort()).toEqual(
    serverSet('ECHARTS_FORBIDDEN_KEYS'),
  );
  expect([...DOM_EVENTS].sort()).toEqual(serverSet('_DOM_EVENTS'));
});

test('the column settings kept are exactly the ones the server stores, with the same types', () => {
  const server = serverColumnSettings();
  const typeOf = (key: string): string => {
    const rule = COLUMN_SETTINGS[key];
    if (rule === 'number') return 'float';
    if (rule === 'boolean') return 'bool';
    // Free text, an identifier or one of a list of names: text either way.
    return 'str';
  };

  expect(server.length).toBeGreaterThan(20);
  expect(Object.keys(COLUMN_SETTINGS).sort()).toEqual(
    server.map(([key]) => key).sort(),
  );
  expect(
    Object.keys(COLUMN_SETTINGS)
      .sort()
      .map(key => [key, typeOf(key)]),
  ).toEqual([...server].sort(([left], [right]) => (left < right ? -1 : 1)));
});
