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
  bidi,
  bidiSentence,
  FSI,
  hasRtlCharacters,
  isolateBidi,
  isolateLtr,
  isolatePart,
  LRI,
  PDI,
} from './bidi';

const ARABIC = 'الصحة';
const HEBREW = 'בריאות';

test('hasRtlCharacters detects right-to-left scripts only', () => {
  expect(hasRtlCharacters(ARABIC)).toBe(true);
  expect(hasRtlCharacters(HEBREW)).toBe(true);
  expect(hasRtlCharacters(`Health (${ARABIC})`)).toBe(true);
  expect(hasRtlCharacters('Health')).toBe(false);
  expect(hasRtlCharacters('19.11%')).toBe(false);
  expect(hasRtlCharacters('-$4.54B')).toBe(false);
  expect(hasRtlCharacters('')).toBe(false);
  expect(hasRtlCharacters(42)).toBe(false);
  expect(hasRtlCharacters(null)).toBe(false);
  expect(hasRtlCharacters(undefined)).toBe(false);
});

test('the isolate controls are the Unicode directional isolates', () => {
  expect(LRI).toBe(String.fromCharCode(0x2066));
  expect(FSI).toBe(String.fromCharCode(0x2068));
  expect(PDI).toBe(String.fromCharCode(0x2069));
});

test('isolateBidi and isolateLtr wrap text and skip empty strings', () => {
  expect(isolateBidi(ARABIC)).toBe(`${FSI}${ARABIC}${PDI}`);
  expect(isolateLtr('19.11%')).toBe(`${LRI}19.11%${PDI}`);
  expect(isolateBidi('')).toBe('');
  expect(isolateLtr('')).toBe('');
});

test('isolatePart picks the isolate from the content', () => {
  expect(isolatePart(ARABIC)).toBe(`${FSI}${ARABIC}${PDI}`);
  expect(isolatePart('19.11%')).toBe(`${LRI}19.11%${PDI}`);
  expect(isolatePart('Health')).toBe(`${LRI}Health${PDI}`);
});

test('bidi leaves left-to-right labels exactly as a plain template string', () => {
  const name = 'Health';
  const value = '1,234';
  const percent = '19.11%';
  expect(bidi`${name}: ${value}`).toBe('Health: 1,234');
  expect(bidi`${name}: ${value} (${percent})`).toBe('Health: 1,234 (19.11%)');
  expect(bidi`${name}`).toBe('Health');
  expect(bidi`no interpolation`).toBe('no interpolation');
});

test('bidi isolates every part of a label with a right-to-left name', () => {
  const value = '1,234';
  const percent = '19.11%';
  expect(bidi`${ARABIC}: ${percent}`).toBe(
    `${FSI}${ARABIC}${PDI}: ${LRI}19.11%${PDI}`,
  );
  expect(bidi`${ARABIC}: ${value} (${percent})`).toBe(
    `${FSI}${ARABIC}${PDI}: ${LRI}1,234${PDI} (${LRI}19.11%${PDI})`,
  );
});

test('bidi keeps the logical order of the parts', () => {
  const label = bidi`${ARABIC}: ${'19.11%'}`;
  // The name comes first and the number last in the string; the isolates
  // only stop the bidirectional algorithm from reordering them on screen.
  expect(label.indexOf(ARABIC)).toBeLessThan(label.indexOf('19.11%'));
  expect(label.split(PDI)).toHaveLength(3);
});

test('bidi stringifies non-string values like a template string', () => {
  expect(bidi`${'A'}: ${5}`).toBe('A: 5');
  expect(bidi`${ARABIC}: ${5}`).toBe(`${FSI}${ARABIC}${PDI}: ${LRI}5${PDI}`);
  expect(bidi`${ARABIC}: ${''}`).toBe(`${FSI}${ARABIC}${PDI}: `);
});

test('bidiSentence leaves a left-to-right sentence exactly as composed', () => {
  expect(bidiSentence(value => `Total: ${value}`, '4.54B')).toBe(
    'Total: 4.54B',
  );
  expect(bidiSentence(value => `Total: ${value}`, '')).toBe('Total: ');
});

test('bidiSentence isolates the value and the right-to-left sentence', () => {
  expect(bidiSentence(value => `الإجمالي: ${value}`, '4.54B')).toBe(
    `${FSI}الإجمالي: ${LRI}4.54B${PDI}${PDI}`,
  );
  expect(bidiSentence(value => `الإجمالي: ${value}`, '-$3.87B')).toBe(
    `${FSI}الإجمالي: ${LRI}-$3.87B${PDI}${PDI}`,
  );
});
