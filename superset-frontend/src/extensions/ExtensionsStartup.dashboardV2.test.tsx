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
import { render, waitFor } from 'spec/helpers/testing-library';
import { FeatureFlag, isFeatureEnabled } from '@superset-ui/core';
import ExtensionsStartup from './ExtensionsStartup';
import type { Namespaces } from './Namespaces';

jest.mock('@superset-ui/core', () => ({
  ...jest.requireActual('@superset-ui/core'),
  isFeatureEnabled: jest.fn(),
}));

const mockIsFeatureEnabled = isFeatureEnabled as jest.MockedFunction<
  typeof isFeatureEnabled
>;

type HostWindow = { superset?: Namespaces };

const host = (): HostWindow => window as unknown as HostWindow;

const start = (...enabled: FeatureFlag[]) => {
  mockIsFeatureEnabled.mockImplementation(flag => enabled.includes(flag));
  render(<ExtensionsStartup />, {
    useRedux: true,
    useRouter: true,
    initialState: { user: { userId: 1 } },
  });
};

beforeEach(() => {
  delete host().superset;
  mockIsFeatureEnabled.mockReset();
});

afterEach(() => {
  delete host().superset;
});

test('with the flag off extensions are given no dashboard namespace', async () => {
  start();

  await waitFor(() => expect(host().superset).toBeDefined());
  // Not the host's implementation, and not the declaration-only namespace
  // the core package exports under the same name either.
  expect(host().superset?.dashboard).toBeUndefined();
  // The rest of the contract is untouched by the flag.
  expect(host().superset?.views).toBeDefined();
  expect(host().superset?.sqlLab).toBeDefined();
});

test('with the flag on the dashboard namespace is part of the contract', async () => {
  start(FeatureFlag.DashboardV2);

  await waitFor(() => expect(host().superset?.dashboard).toBeDefined());
  expect(typeof host().superset?.dashboard?.addWidget).toBe('function');
  expect(typeof host().superset?.dashboard?.getRoot).toBe('function');
});
