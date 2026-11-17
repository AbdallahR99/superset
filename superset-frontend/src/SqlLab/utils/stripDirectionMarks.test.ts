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
import { extendedDayjs } from '@superset-ui/core/utils/dates';
import 'dayjs/locale/ar';
import stripDirectionMarks from './stripDirectionMarks';

test('removes direction marks and keeps everything else', () => {
  expect(stripDirectionMarks('17/‏11/‏2026 15:06:21')).toBe(
    '17/11/2026 15:06:21',
  );
  expect(stripDirectionMarks('‎a؜b')).toBe('ab');
  expect(stripDirectionMarks('11/17/2026 15:06:21')).toBe(
    '11/17/2026 15:06:21',
  );
});

test('yields a plain numeric timestamp for the Arabic date format', () => {
  const formatted = extendedDayjs('2026-11-17T15:06:21')
    .locale('ar')
    .format('L HH:mm:ss');

  expect(formatted).toMatch(/‏/);
  expect(stripDirectionMarks(formatted)).toBe('17/11/2026 15:06:21');
});
