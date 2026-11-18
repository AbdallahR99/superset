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
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { savedWidgetRef } from '../src/savedWidgetRef.ts';

const widgetId = '078bc660-0175-4624-9cee-de62944567b8';

test('the catalog accepts a saved widget UUID as its only property', () => {
  assert.equal(savedWidgetRef({ widgetId }), widgetId);
  assert.equal(
    savedWidgetRef({ widgetId, title: 'External title' }),
    undefined,
  );
  assert.equal(
    savedWidgetRef({ widgetId: { '@path': '/example' } }),
    undefined,
  );
  assert.equal(savedWidgetRef({ widgetId: '/widget/1' }), undefined);
});
