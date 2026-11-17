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
import Ajv from 'ajv';
import {
  createInterpretingValidator,
  type SchemaViolation,
} from './interpretingValidator';

const interpreter = createInterpretingValidator();
// The reference: Ajv configured the way JsonForms configures its own.
const reference = new Ajv({
  allErrors: true,
  verbose: true,
  strict: false,
  addUsedSchema: false,
});

/** The errors of one value, reduced to what a form shows and sorts by. */
const brief = (
  errors: readonly Partial<SchemaViolation>[] | null | undefined,
) =>
  (errors ?? [])
    .map(
      error =>
        `${error.instancePath}|${error.keyword}|${error.message}|${JSON.stringify(
          error.params,
        )}`,
    )
    .sort();

/** Validates with both and expects the same verdict and the same errors. */
function expectSameAsAjv(schema: object, data: unknown): boolean {
  const mine = interpreter.compile(schema);
  const theirs = reference.compile(schema);
  const valid = mine(data);
  expect({ data, valid }).toEqual({ data, valid: theirs(data) });
  expect(brief(mine.errors)).toEqual(
    brief(theirs.errors as Partial<SchemaViolation>[] | null),
  );
  return valid;
}

// The control schema the server generates for the ECharts widget, reduced to
// one of each construct it uses: `$defs` + `$ref`, nullable fields spelled as
// `anyOf` with `null`, enums, bounds, nested objects, arrays of strings and
// of anything, and vendor annotations (`x-*`).
const ECHARTS_CONTROLS = {
  $defs: {
    DataBinding: {
      type: 'object',
      title: 'DataBinding',
      properties: {
        datasetId: { type: 'integer', title: 'Dataset ID' },
        metrics: {
          type: 'array',
          items: {},
          'x-control': 'metric-multi',
          'x-language': 'json',
        },
        dimensions: { type: 'array', items: { type: 'string' } },
        rowLimit: { type: 'integer', minimum: 1, default: 1000 },
      },
      required: ['datasetId', 'metrics'],
    },
    EchartsChrome: {
      type: 'object',
      properties: {
        titleText: {
          anyOf: [{ type: 'string' }, { type: 'null' }],
          default: null,
        },
        legendShow: { type: 'boolean', default: true },
        legendPosition: {
          enum: ['top', 'bottom', 'left', 'right'],
          type: 'string',
        },
        xAxisRotate: {
          anyOf: [
            { type: 'integer', minimum: -90, maximum: 90 },
            { type: 'null' },
          ],
        },
      },
    },
  },
  type: 'object',
  title: 'EchartsControls',
  properties: {
    dataBinding: { $ref: '#/$defs/DataBinding' },
    chartType: { enum: ['bar', 'line', 'pie'], type: 'string' },
    echartsOptions: {
      type: 'object',
      additionalProperties: true,
      'x-hidden-in-form': true,
    },
    chrome: { anyOf: [{ $ref: '#/$defs/EchartsChrome' }, { type: 'null' }] },
    crossFilter: { type: 'boolean', default: false },
  },
  required: ['dataBinding'],
};

const FILTER_SELECT_CONTROLS = {
  type: 'object',
  properties: {
    datasetId: {
      type: 'integer',
      enum: [1, 2, 3],
      'x-dynamic': true,
      'x-enumNames': ['birth_names', 'video_game_sales', 'rls'],
    },
    column: {
      type: 'string',
      minLength: 1,
      default: '',
      enum: ['gender', 'name'],
      'x-dependsOn': ['datasetId'],
    },
    options: { type: 'array', items: { type: 'string' } },
    scope: {
      type: 'object',
      properties: { targets: { type: 'array', items: { type: 'string' } } },
    },
  },
  required: ['datasetId'],
};

test('accepts and refuses widget props exactly as Ajv does, error for error', () => {
  const cases: [object, unknown][] = [
    [ECHARTS_CONTROLS, { dataBinding: { datasetId: 1, metrics: ['count'] } }],
    [ECHARTS_CONTROLS, {}],
    [ECHARTS_CONTROLS, { dataBinding: { datasetId: '1' } }],
    [
      ECHARTS_CONTROLS,
      {
        dataBinding: {
          datasetId: 1.5,
          metrics: 'count',
          dimensions: ['gender', 7],
          rowLimit: 0,
        },
        chartType: 'radar',
        crossFilter: 'yes',
      },
    ],
    [
      ECHARTS_CONTROLS,
      {
        dataBinding: { datasetId: 1, metrics: [{ expressionType: 'SQL' }] },
        chrome: null,
        echartsOptions: { series: [{ type: 'bar' }] },
      },
    ],
    [
      ECHARTS_CONTROLS,
      {
        dataBinding: { datasetId: 1, metrics: [] },
        chrome: { titleText: null, legendPosition: 'top', xAxisRotate: 45 },
      },
    ],
    [
      ECHARTS_CONTROLS,
      {
        dataBinding: { datasetId: 1, metrics: [] },
        chrome: { titleText: 3, legendPosition: 'middle', xAxisRotate: 120 },
      },
    ],
    [ECHARTS_CONTROLS, { dataBinding: null, chrome: 'none' }],
    [ECHARTS_CONTROLS, null],
    [ECHARTS_CONTROLS, []],
    [FILTER_SELECT_CONTROLS, { datasetId: 2, column: 'gender' }],
    [FILTER_SELECT_CONTROLS, { datasetId: 9, column: '' }],
    [FILTER_SELECT_CONTROLS, { datasetId: 1, column: 'state' }],
    [FILTER_SELECT_CONTROLS, { column: 'gender', options: ['a', 1] }],
    [FILTER_SELECT_CONTROLS, { datasetId: 1, scope: { targets: 'all' } }],
  ];
  const verdicts = cases.map(([schema, data]) => expectSameAsAjv(schema, data));
  // Both outcomes are covered: the comparison is not between two validators
  // that accept everything.
  expect(verdicts.filter(Boolean)).toHaveLength(4);
});

test('each supported keyword gives the verdict and the errors Ajv gives', () => {
  const cases: [object, unknown[]][] = [
    [{ type: 'number' }, [1, 1.5, '1', null]],
    [{ type: ['string', 'null'] }, ['a', null, 1, {}]],
    [{ type: 'object' }, [{}, [], null, 'x']],
    [{ const: { a: [1, 2] } }, [{ a: [1, 2] }, { a: [2, 1] }, null]],
    [{ enum: ['a', 1, null, [1]] }, ['a', 1, null, [1], 'b', [2]]],
    [{ minimum: 0, maximum: 5 }, [-1, 0, 5, 6, 'not a number']],
    [{ exclusiveMinimum: 0, exclusiveMaximum: 5 }, [0, 1, 5]],
    [{ multipleOf: 0.5 }, [1.5, 1.25, 0]],
    [{ minLength: 2, maxLength: 3 }, ['a', 'ab', 'abcd', '😀😀', 7]],
    [{ pattern: '^#[0-9a-f]{6}$' }, ['#aabbcc', 'red', 1]],
    [{ minItems: 1, maxItems: 2 }, [[], [1], [1, 2, 3], 'ab']],
    [
      { uniqueItems: true },
      [
        [1, 2],
        [1, { a: 1 }, { a: 1 }],
      ],
    ],
    [
      { items: { type: 'integer' } },
      [
        [1, 2],
        [1, 'a', 2.5],
      ],
    ],
    [{ contains: { const: 'gender' } }, [['a', 'gender'], ['a'], []]],
    [
      {
        type: 'object',
        properties: { a: { type: 'string' } },
        additionalProperties: false,
      },
      [{ a: 'x' }, { a: 'x', b: 1, c: 2 }, { a: 1 }],
    ],
    [
      { additionalProperties: { type: 'integer' } },
      [{ a: 1 }, { a: 'x', 'b/c~d': 'y' }],
    ],
    [{ required: ['a', 'b'] }, [{ a: 1, b: 2 }, { a: 1 }, {}, []]],
    [{ allOf: [{ type: 'string' }, { minLength: 2 }] }, ['ab', 'a', 1]],
    [
      { anyOf: [{ type: 'string', minLength: 2 }, { type: 'integer' }] },
      ['ab', 3, 'a', 1.5, null],
    ],
    [
      { oneOf: [{ type: 'integer' }, { minimum: 2 }] },
      [1, 2.5, 3, 1.5, 'text'],
    ],
    [{ not: { type: 'string' } }, [1, 'a']],
    [
      {
        if: { properties: { kind: { const: 'bar' } }, required: ['kind'] },
        // eslint-disable-next-line unicorn/no-thenable -- the JSON Schema keyword
        then: { required: ['stack'] },
        else: { required: ['smooth'] },
      },
      [
        { kind: 'bar', stack: true },
        { kind: 'bar' },
        { kind: 'line' },
        { kind: 'line', smooth: true },
      ],
    ],
    [
      {
        $defs: {
          node: {
            properties: { child: { $ref: '#/$defs/node' } },
            required: ['id'],
          },
        },
        $ref: '#/$defs/node',
      },
      [
        { id: 1, child: { id: 2, child: { id: 3 } } },
        { id: 1, child: { child: {} } },
      ],
    ],
    [
      {
        definitions: { 'a/b': { type: 'integer' } },
        $ref: '#/definitions/a~1b',
      },
      [1, 'x'],
    ],
  ];
  cases.forEach(([schema, values]) =>
    values.forEach(value => expectSameAsAjv(schema, value)),
  );
});

test('an empty enum, which the server sends until a dataset is picked, refuses every value', () => {
  // Ajv refuses to compile such a schema at all; the form must still render.
  const schema = { properties: { column: { type: 'string', enum: [] } } };
  expect(interpreter.validate(schema, {})).toBe(true);
  expect(interpreter.validate(schema, { column: 'gender' })).toBe(false);
  expect(interpreter.errors?.map(error => error.keyword)).toEqual(['enum']);
});

test('boolean schemas accept everything or nothing', () => {
  expect(interpreter.validate(true, { any: 'thing' })).toBe(true);
  expect(interpreter.validate(false, 1)).toBe(false);
  expectSameAsAjv({ properties: { a: true, b: false } }, { a: 1 });
  expect(interpreter.validate({ properties: { b: false } }, { b: 1 })).toBe(
    false,
  );
});

test('errors carry what JsonForms reads: path, keyword, params, parent schema and data', () => {
  const validate = interpreter.compile(ECHARTS_CONTROLS);
  expect(validate({ dataBinding: { datasetId: 1 }, chartType: 'radar' })).toBe(
    false,
  );
  expect(validate.errors).toEqual([
    {
      keyword: 'required',
      instancePath: '/dataBinding',
      schemaPath: '#/$defs/DataBinding/required',
      params: { missingProperty: 'metrics' },
      message: "must have required property 'metrics'",
      schema: ['datasetId', 'metrics'],
      parentSchema: ECHARTS_CONTROLS.$defs.DataBinding,
      data: { datasetId: 1 },
    },
    {
      keyword: 'enum',
      instancePath: '/chartType',
      schemaPath: '#/properties/chartType/enum',
      params: { allowedValues: ['bar', 'line', 'pie'] },
      message: 'must be equal to one of the allowed values',
      schema: ['bar', 'line', 'pie'],
      parentSchema: ECHARTS_CONTROLS.properties.chartType,
      data: 'radar',
    },
  ]);
  // A later valid value clears them, as Ajv's validate function does.
  expect(validate({ dataBinding: { datasetId: 1, metrics: [] } })).toBe(true);
  expect(validate.errors).toBeNull();
});

test('validate() answers a rule condition and keeps the errors of the last call', () => {
  // The condition `buildUiSchema` writes for a field that depends on another.
  const condition = { not: { anyOf: [{ const: '' }, { const: null }] } };
  expect(interpreter.validate(condition, 3)).toBe(true);
  expect(interpreter.errors).toBeNull();
  expect(interpreter.validate(condition, '')).toBe(false);
  expect(interpreter.errors).toHaveLength(1);
  expect(interpreter.validate({ const: 'bar' }, undefined)).toBe(false);
});

test('a reference without a target is refused when the schema is compiled', () => {
  // JsonForms compiles a combinator's sub-schema on its own and treats a throw
  // as "not self-contained"; a silent pass would pick the wrong alternative.
  expect(() =>
    interpreter.compile({ properties: { a: { $ref: '#/$defs/Missing' } } }),
  ).toThrow("can't resolve reference #/$defs/Missing");
  expect(() => interpreter.compile({ $ref: 'https://example.com/s' })).toThrow(
    "can't resolve reference",
  );
  expect(() => interpreter.compile('not a schema')).toThrow(
    'schema must be object or boolean',
  );
});

test('schemas that reference themselves in a loop end', () => {
  expect(interpreter.validate({ $ref: '#' }, { a: 1 })).toBe(true);
  const mutual = {
    $defs: {
      a: { allOf: [{ $ref: '#/$defs/b' }] },
      b: { anyOf: [{ $ref: '#/$defs/a' }, { type: 'string' }] },
    },
    $ref: '#/$defs/a',
  };
  expect(interpreter.validate(mutual, 'text')).toBe(true);
});

test('keywords it does not know, and names from Object.prototype, never fail a value', () => {
  const schema = {
    type: 'object',
    format: 'made-up',
    'x-control': 'select',
    properties: { toString: { type: 'string' } },
    required: ['constructor'],
  };
  expect(interpreter.validate(schema, { constructor: 1, toString: 'x' })).toBe(
    true,
  );
  // `constructor` exists on every object through its prototype, which is not
  // the same as the author having set it.
  expect(interpreter.validate(schema, {})).toBe(false);
  expect(interpreter.validate({ type: 'colour' }, 1)).toBe(true);
  expect(interpreter.validate({ pattern: '(?P<py>x)' }, 'anything')).toBe(true);
});

test('no schema is ever turned into code', () => {
  // Under the production Content Security Policy `new Function` throws an
  // EvalError; this is that policy for the length of the test.
  // A function declaration, so that it can be called with `new` as well.
  function refuse(): never {
    throw new EvalError('unsafe-eval is not an allowed source of script');
  }
  const realFunction = global.Function;
  // Ajv logs the code it failed to run before it throws.
  const logged = jest.spyOn(console, 'error').mockImplementation(() => {});
  global.Function = refuse as unknown as FunctionConstructor;
  try {
    const validate = createInterpretingValidator().compile(ECHARTS_CONTROLS);
    expect(validate({ dataBinding: { datasetId: 1, metrics: [] } })).toBe(true);
    expect(validate({})).toBe(false);
    // The control: Ajv, given the same schema under the same policy, throws.
    expect(() => new Ajv({ strict: false }).compile(ECHARTS_CONTROLS)).toThrow(
      EvalError,
    );
  } finally {
    global.Function = realFunction;
    logged.mockRestore();
  }
});
