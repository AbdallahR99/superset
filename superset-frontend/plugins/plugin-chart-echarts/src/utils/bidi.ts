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

/**
 * Helpers for text that mixes right-to-left words (Arabic, Hebrew, ...) with
 * numbers and left-to-right words in ONE plain string, as chart labels do
 * (`name: value (percent)`).
 *
 * Such a string is drawn on a canvas, where no markup is available, so its
 * parts are wrapped in Unicode directional isolates instead of `<bdi>`.
 * Without them the bidirectional algorithm reorders the punctuation and the
 * number around the right-to-left word: `الصحة: 19.11%` is displayed with the
 * percent sign detached from the number and the colon on the wrong side.
 */

/** LEFT-TO-RIGHT ISOLATE: the wrapped text is left-to-right. */
export const LRI = '⁦';
/** FIRST STRONG ISOLATE: the wrapped text takes its own direction. */
export const FSI = '⁨';
/** POP DIRECTIONAL ISOLATE: closes LRI / FSI. */
export const PDI = '⁩';

// Hebrew, Arabic, Syriac, Thaana, N'Ko, Samaritan, Mandaic, Arabic Extended
// and the Hebrew / Arabic presentation forms.
const RTL_CHARACTERS = /[֐-ࣿיִ-﷿ﹰ-ﻼ]/;

/**
 * Whether a value contains at least one right-to-left character.
 */
export function hasRtlCharacters(text: unknown): boolean {
  return typeof text === 'string' && RTL_CHARACTERS.test(text);
}

/**
 * Wraps text in a first-strong isolate, so that it keeps its own direction
 * and does not reorder what surrounds it.
 */
export function isolateBidi(text: string): string {
  return text ? `${FSI}${text}${PDI}` : text;
}

/**
 * Wraps text that is left-to-right by nature (a formatted number, a percent,
 * a date) in a left-to-right isolate.
 */
export function isolateLtr(text: string): string {
  return text ? `${LRI}${text}${PDI}` : text;
}

/**
 * Isolates one part of a label that mixes directions: text with
 * right-to-left characters keeps its own direction, anything else (a number,
 * a percentage, a left-to-right word) stays left-to-right.
 */
export function isolatePart(text: string): string {
  return hasRtlCharacters(text) ? isolateBidi(text) : isolateLtr(text);
}

/**
 * Template tag that composes a mixed-direction label:
 *
 *   bidi`${name}: ${formattedValue} (${formattedPercent})`
 *
 * When none of the interpolated parts contains a right-to-left character the
 * result is exactly the plain template string, so left-to-right labels are
 * unchanged. Otherwise every part is isolated: parts with right-to-left
 * characters keep their own direction, the others (numbers, percentages,
 * left-to-right words) stay left-to-right, and the literal text between them
 * follows the direction of the surrounding context.
 */
export function bidi(
  strings: TemplateStringsArray,
  ...values: unknown[]
): string {
  const parts = values.map(value => String(value));
  const isMixed = parts.some(hasRtlCharacters);
  return strings.reduce((result, literal, index) => {
    if (index >= parts.length) {
      return result + literal;
    }
    const part = parts[index];
    if (!isMixed) {
      return result + literal + part;
    }
    return result + literal + isolatePart(part);
  }, '');
}

/**
 * Composes a translated sentence around a value that is left-to-right by
 * nature (a formatted number, a percentage):
 *
 *   bidiSentence(value => t('Total: %s', value), formattedTotal)
 *
 * A left-to-right sentence is returned exactly as composed. A right-to-left
 * sentence (an Arabic translation, for example) is drawn on a left-to-right
 * canvas, where the bidirectional algorithm would attach the digits to the
 * right-to-left words and leave the unit behind (`4.54B` split around the
 * label). The value is therefore isolated as left-to-right, and the whole
 * sentence is isolated so that it reads in its own direction.
 */
export function bidiSentence(
  compose: (value: string) => string,
  value: string,
): string {
  const sentence = compose(value);
  if (!hasRtlCharacters(sentence)) {
    return sentence;
  }
  return isolateBidi(compose(isolateLtr(value)));
}
