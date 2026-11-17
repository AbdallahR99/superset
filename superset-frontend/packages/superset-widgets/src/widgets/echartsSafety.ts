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
 * @fileoverview Keeps an authored ECharts option from reaching the DOM as
 * markup or script.
 *
 * A widget's `echartsOptions` is data: written by whoever defined the widget,
 * drawn in the page of whoever looks at it — another Superset user, or a host
 * application's visitor. Most of an option paints onto a canvas, where text
 * is only ever text. The exceptions, all of which ECharts writes into the
 * page as HTML or opens as a URL, are:
 *
 * - `toolbox.feature.dataView` (`lang`, `title`, `optionToContent`) and the
 *   fallback window of `saveAsImage` (`lang`);
 * - a `tooltip` in HTML mode, at any level of the option: its `formatter`
 *   template, its `content`, `extraCssText` / `className`, and the colours
 *   ECharts splices into the markup of the tooltip's arrow;
 * - `link` / `sublink`, opened when a title or a tree node is clicked;
 * - handlers on `graphic` elements.
 *
 * The option is therefore reduced to an allowlist: only top-level keys known
 * to draw on the canvas are passed on, a `tooltip` and the `toolbox` are
 * rebuilt from the settings listed here, and everything else those two could
 * carry is dropped. This runs last, on the finished option, after `$bind`
 * markers are resolved, so a bound value cannot put back what was removed.
 *
 * A function is something only host code can supply (JSON cannot), and it is
 * kept where a setting takes one — a tooltip `formatter` written by the host
 * page is the host's own code. `graphic` is the exception: nothing callable
 * is kept there.
 */

const MAX_DEPTH = 64;
const MAX_CSS_LENGTH = 200;

/**
 * Top-level option keys whose whole subtree is drawn on the canvas (with the
 * nested `tooltip`, `link` and handler rules below still applied). Absent on
 * purpose: `baseOption` / `media` / `options` / `timeline` (each nests whole
 * options), and components this package does not register.
 */
const TOP_LEVEL_KEYS: ReadonlySet<string> = new Set([
  'angleAxis',
  'animation',
  'animationDelay',
  'animationDelayUpdate',
  'animationDuration',
  'animationDurationUpdate',
  'animationEasing',
  'animationEasingUpdate',
  'animationThreshold',
  'aria',
  'axisPointer',
  'backgroundColor',
  'blendMode',
  'calendar',
  'color',
  'darkMode',
  'dataZoom',
  'dataset',
  'graphic',
  'grid',
  'hoverLayerThreshold',
  'legend',
  'parallel',
  'parallelAxis',
  'polar',
  'radar',
  'radiusAxis',
  'series',
  'singleAxis',
  'stateAnimation',
  'textStyle',
  'title',
  'toolbox',
  'tooltip',
  'useUTC',
  'visualMap',
  'xAxis',
  'yAxis',
]);

const LINK_KEYS = new Set(['link', 'sublink']);
// Matched after dropping what a URL parser ignores inside a scheme.
const SAFE_LINK = /^(https?:|mailto:|\/|#|\.{0,2}\/|[^:]*$)/i;

function isSafeLink(link: string): boolean {
  // eslint-disable-next-line no-control-regex
  return SAFE_LINK.test(link.replace(/[\u0000- ]/g, ''));
}

/**
 * A CSS value that cannot leave the declaration it is written into: no
 * quotes, angle brackets, semicolons, braces or backslashes, and no `url()`.
 * ECharts concatenates tooltip colours into the markup of the tooltip arrow.
 */
const CSS_VALUE = /^[\w\s#%.,()+\-/]*$/;

function isSafeCss(value: string): boolean {
  return (
    value.length <= MAX_CSS_LENGTH &&
    CSS_VALUE.test(value) &&
    !/url\s*\(|expression\s*\(/i.test(value)
  );
}

const HTML_ESCAPES: Readonly<Record<string, string>> = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;',
};

// Formatting tags with no attributes at all: inert in any position.
const INERT_TAG = /&lt;(\/?)(b|i|u|em|strong|small|sub|sup|br)\s*(\/?)&gt;/gi;

/**
 * A tooltip template with its markup turned into text. ECharts encodes the
 * values it substitutes for `{a}`, `{b}`, `{c}`… but assigns the template
 * itself as HTML. A handful of attribute-less formatting tags survive.
 */
export function escapeTooltipTemplate(template: string): string {
  return template
    .replace(/[&<>"']/g, character => HTML_ESCAPES[character])
    .replace(INERT_TAG, '<$1$2$3>');
}

const isPlainObject = (value: unknown): value is Record<string, unknown> => {
  if (value === null || typeof value !== 'object') return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
};

type Rule = (value: unknown) => unknown;

const bool: Rule = value => (typeof value === 'boolean' ? value : undefined);
const finite: Rule = value =>
  typeof value === 'number' && Number.isFinite(value) ? value : undefined;
const css: Rule = value =>
  typeof value === 'string' && isSafeCss(value) ? value : undefined;
const size: Rule = value => finite(value) ?? css(value);
const callable: Rule = value =>
  typeof value === 'function' ? value : undefined;
const oneOf =
  (...allowed: string[]): Rule =>
  value =>
    typeof value === 'string' && allowed.includes(value) ? value : undefined;
const listOf =
  (rule: Rule): Rule =>
  value => {
    if (!Array.isArray(value)) return undefined;
    const kept = value.slice(0, 64).map(rule);
    return kept.every(item => item !== undefined) ? kept : undefined;
  };
const either =
  (...rules: Rule[]): Rule =>
  value => {
    for (const rule of rules) {
      const kept = rule(value);
      if (kept !== undefined) return kept;
    }
    return undefined;
  };

/** A new object holding only the `rules` keys whose value passes its rule. */
function pick(
  value: unknown,
  rules: Readonly<Record<string, Rule>>,
): Record<string, unknown> | undefined {
  if (!isPlainObject(value)) return undefined;
  const kept: Record<string, unknown> = {};
  Object.keys(rules).forEach(key => {
    if (!Object.prototype.hasOwnProperty.call(value, key)) return;
    const cleaned = rules[key](value[key]);
    if (cleaned !== undefined) kept[key] = cleaned;
  });
  return kept;
}

const objectOf =
  (rules: Readonly<Record<string, Rule>>): Rule =>
  value =>
    pick(value, rules);

/** Becomes inline CSS on the tooltip element and on spans inside it. */
const TOOLTIP_TEXT_STYLE: Readonly<Record<string, Rule>> = {
  color: css,
  fontStyle: oneOf('normal', 'italic', 'oblique'),
  fontWeight: either(
    finite,
    oneOf('normal', 'bold', 'bolder', 'lighter', '100', '200', '300', '400'),
    oneOf('500', '600', '700', '800', '900'),
  ),
  fontFamily: css,
  fontSize: finite,
  lineHeight: finite,
  width: finite,
  height: finite,
  textBorderColor: css,
  textBorderWidth: finite,
  textShadowColor: css,
  textShadowBlur: finite,
  textShadowOffsetX: finite,
  textShadowOffsetY: finite,
  overflow: oneOf('none', 'truncate', 'break', 'breakAll'),
  ellipsis: css,
  decoration: oneOf('none', 'underline', 'overline', 'line-through'),
  align: oneOf('left', 'center', 'right'),
};

/**
 * What a `tooltip` may carry, wherever it sits (the option, a series, a data
 * item, an axis, the legend). Not here, and so never passed on: `content`,
 * `formatterParams`, `extraCssText`, `className`, `appendTo`.
 */
function tooltipRules(cleanCanvas: Rule): Readonly<Record<string, Rule>> {
  return {
    show: bool,
    showContent: bool,
    alwaysShowContent: bool,
    enterable: bool,
    confine: bool,
    appendToBody: bool,
    displayTransition: bool,
    showDelay: finite,
    hideDelay: finite,
    transitionDuration: finite,
    borderWidth: finite,
    borderRadius: finite,
    shadowBlur: finite,
    shadowOffsetX: finite,
    shadowOffsetY: finite,
    trigger: oneOf('item', 'axis', 'none'),
    triggerOn: oneOf('mousemove', 'click', 'mousemove|click', 'none'),
    renderMode: oneOf('html', 'richText'),
    order: oneOf('seriesAsc', 'seriesDesc', 'valueAsc', 'valueDesc'),
    backgroundColor: css,
    borderColor: css,
    shadowColor: css,
    padding: either(finite, listOf(finite)),
    position: either(css, listOf(size), callable),
    formatter: value =>
      typeof value === 'string'
        ? escapeTooltipTemplate(value)
        : callable(value),
    valueFormatter: callable,
    textStyle: objectOf(TOOLTIP_TEXT_STYLE),
    // The pointer is drawn on the canvas.
    axisPointer: cleanCanvas,
  };
}

const AXIS_INDEX: Rule = either(
  finite,
  bool,
  listOf(finite),
  oneOf('all', 'none'),
);

/**
 * The toolbox, reduced to tools that draw nothing into the DOM and take no
 * text of the author's: no `dataView`, no custom `my*` tool, no `magicType`
 * (it carries option fragments), no titles, icons or tooltips.
 */
const TOOLBOX_RULES: Readonly<Record<string, Rule>> = {
  show: bool,
  showTitle: bool,
  orient: oneOf('horizontal', 'vertical'),
  itemSize: finite,
  itemGap: finite,
  left: size,
  top: size,
  right: size,
  bottom: size,
  width: size,
  height: size,
  z: finite,
  zlevel: finite,
  feature: objectOf({
    saveAsImage: objectOf({
      show: bool,
      type: oneOf('png', 'jpg', 'jpeg'),
      backgroundColor: css,
      pixelRatio: finite,
    }),
    restore: objectOf({ show: bool }),
    dataZoom: objectOf({
      show: bool,
      xAxisIndex: AXIS_INDEX,
      yAxisIndex: AXIS_INDEX,
      filterMode: oneOf('filter', 'weakFilter', 'empty', 'none'),
    }),
  }),
};

interface Walk {
  depth: number;
  ancestors: Set<object>;
  /** Inside `graphic`: nothing callable and no `on…` handler is kept. */
  inert: boolean;
}

/** One of a `tooltip` / `toolbox` value, or each of an array of them. */
function eachOf(value: unknown, rule: Rule): unknown {
  if (Array.isArray(value)) {
    return value
      .slice(0, 64)
      .map(rule)
      .filter(item => item !== undefined);
  }
  return rule(value);
}

/**
 * A cleaned copy of `value`. Only plain objects and arrays are entered:
 * anything else (a gradient instance, a function a host passed in code) is
 * not something JSON can author and is kept as it is, except inside
 * `graphic`.
 */
function clean(value: unknown, walk: Walk): unknown {
  const isArray = Array.isArray(value);
  if (!isArray && !isPlainObject(value)) {
    if (walk.inert && typeof value === 'function') return undefined;
    return value;
  }
  const container = value as object;
  // Past the cap, or back at an ancestor: nothing below is passed on.
  if (walk.depth > MAX_DEPTH || walk.ancestors.has(container)) return undefined;
  walk.ancestors.add(container);
  const below: Walk = { ...walk, depth: walk.depth + 1 };
  try {
    if (isArray) {
      return (value as unknown[]).map(item => clean(item, below));
    }
    const copy: Record<string, unknown> = {};
    Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
      // Assigning it would replace the copy's prototype.
      if (key === '__proto__') return;
      let cleaned: unknown;
      if (key === 'tooltip') {
        const rules = tooltipRules(nested => clean(nested, below));
        cleaned = eachOf(child, objectOf(rules));
      } else if (key === 'toolbox') {
        cleaned = eachOf(child, objectOf(TOOLBOX_RULES));
      } else if (LINK_KEYS.has(key) && typeof child === 'string') {
        cleaned = isSafeLink(child) ? child : undefined;
      } else if (walk.inert && /^on/i.test(key)) {
        cleaned = undefined;
      } else {
        cleaned = clean(
          child,
          key === 'graphic' ? { ...below, inert: true } : below,
        );
      }
      if (cleaned !== undefined) copy[key] = cleaned;
    });
    return copy;
  } finally {
    walk.ancestors.delete(container);
  }
}

/**
 * A copy of `option` holding only what is safe to hand to ECharts; see the
 * file overview. The option passed in is left untouched: it may be the
 * author's own (frozen) object.
 */
export function sanitizeEchartsOption<T extends Record<string, unknown>>(
  option: T,
): T {
  if (!isPlainObject(option)) return {} as T;
  const allowed: Record<string, unknown> = {};
  Object.keys(option).forEach(key => {
    if (TOP_LEVEL_KEYS.has(key)) allowed[key] = option[key];
  });
  return clean(allowed, {
    depth: 0,
    // The option itself, so a reference back to it is seen as one.
    ancestors: new Set<object>([option]),
    inert: false,
  }) as T;
}
