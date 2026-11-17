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
 * A JSON Schema validator that interprets the schema instead of compiling it.
 *
 * JsonForms validates form data and evaluates rule conditions through an Ajv
 * instance, and Ajv turns every schema into JavaScript source that it runs
 * with `new Function`. A page served under a Content Security Policy without
 * `'unsafe-eval'` refuses that, and the refusal takes the whole builder down.
 * The object built here has the two methods JsonForms calls on Ajv — `compile`
 * and `validate` — and reports errors in Ajv's `ErrorObject` shape, but walks
 * the schema at validation time and never generates code.
 *
 * It covers the subset of JSON Schema that the widget control schemas use
 * (they are generated from Pydantic models on the server): `type`, `enum`,
 * `const`, `required`, `properties`, `additionalProperties`, `items`,
 * `prefixItems`, `contains`, `minItems`/`maxItems`, `uniqueItems`,
 * `minimum`/`maximum`, `exclusiveMinimum`/`exclusiveMaximum`, `multipleOf`,
 * `minLength`/`maxLength`, `pattern`, `anyOf`/`oneOf`/`allOf`/`not`,
 * `if`/`then`/`else`, and local `$ref` pointers (`#/$defs/...`). Any other
 * keyword is an annotation here and never fails a value, the way Ajv treats
 * unknown keywords with `strict: false`. What is shown in the form is advice:
 * the server validates every edit and every save on its own.
 */
import { isEqual } from 'lodash-es';
import type Ajv from 'ajv';

type SchemaObject = Record<string, unknown>;
type Schema = SchemaObject | boolean;

/** One violation, in the shape of Ajv's `ErrorObject` (verbose mode). */
export interface SchemaViolation {
  keyword: string;
  instancePath: string;
  schemaPath: string;
  params: Record<string, unknown>;
  message: string;
  schema: unknown;
  parentSchema: SchemaObject;
  data: unknown;
}

/** What `compile` returns: Ajv's `ValidateFunction`, minus the code. */
export interface InterpretingValidateFunction {
  (data: unknown): boolean;
  errors: SchemaViolation[] | null;
  schema: Schema;
}

/** The part of Ajv's interface that JsonForms uses. */
export interface InterpretingValidator {
  compile(schema: unknown): InterpretingValidateFunction;
  validate(schema: unknown, data: unknown): boolean;
  errors: SchemaViolation[] | null;
}

const hasOwn = (object: object, key: string): boolean =>
  Object.prototype.hasOwnProperty.call(object, key);

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const isSchema = (value: unknown): value is Schema =>
  typeof value === 'boolean' || isPlainObject(value);

const isSchemaList = (value: unknown): value is Schema[] =>
  Array.isArray(value) && value.every(isSchema);

const escapePointer = (segment: string): string =>
  segment.replace(/~/g, '~0').replace(/\//g, '~1');

const unescapePointer = (segment: string): string =>
  decodeURIComponent(segment).replace(/~1/g, '/').replace(/~0/g, '~');

/** Length in code points, which is what JSON Schema counts. */
const codePoints = (value: string): number => Array.from(value).length;

function matchesType(type: string, data: unknown): boolean {
  switch (type) {
    case 'string':
      return typeof data === 'string';
    case 'number':
      return typeof data === 'number' && Number.isFinite(data);
    case 'integer':
      return typeof data === 'number' && Number.isInteger(data);
    case 'boolean':
      return typeof data === 'boolean';
    case 'null':
      return data === null;
    case 'array':
      return Array.isArray(data);
    case 'object':
      return isPlainObject(data);
    default:
      // An unknown type name constrains nothing rather than failing every
      // value: a schema this interpreter does not understand must not block
      // the author.
      return true;
  }
}

/**
 * Follows a local JSON pointer (`#`, `#/$defs/Name`, ...) from the schema
 * being validated. Anything else — a remote or relative reference, or a
 * pointer with no target — is an error, as it is for Ajv: JsonForms relies on
 * that to tell a self-contained sub-schema from one that is not.
 */
function resolveReference(root: Schema, reference: string): Schema {
  if (!reference.startsWith('#')) {
    throw new Error(`can't resolve reference ${reference}`);
  }
  const pointer = reference.slice(1);
  let target: unknown = root;
  if (pointer !== '') {
    if (!pointer.startsWith('/')) {
      throw new Error(`can't resolve reference ${reference}`);
    }
    pointer
      .slice(1)
      .split('/')
      .forEach(raw => {
        const segment = unescapePointer(raw);
        if (Array.isArray(target) && /^\d+$/.test(segment)) {
          target = target[Number(segment)];
        } else if (isPlainObject(target) && hasOwn(target, segment)) {
          target = target[segment];
        } else {
          target = undefined;
        }
      });
  }
  if (!isSchema(target)) {
    throw new Error(`can't resolve reference ${reference}`);
  }
  return target;
}

/** Keywords whose value is one sub-schema. */
const SCHEMA_KEYWORDS = [
  'additionalProperties',
  'items',
  'contains',
  'not',
  'if',
  'then',
  'else',
];
/** Keywords whose value is a list of sub-schemas. */
const SCHEMA_LIST_KEYWORDS = ['anyOf', 'oneOf', 'allOf', 'prefixItems'];
/** Keywords whose value maps names to sub-schemas. */
const SCHEMA_MAP_KEYWORDS = ['properties', '$defs', 'definitions'];

/**
 * Resolves every `$ref` reachable from `root` once, so a reference without a
 * target is reported when the schema is compiled and not on the first value
 * that happens to reach it.
 */
function checkReferences(root: Schema): void {
  const seen = new Set<object>();
  const pending: unknown[] = [root];
  while (pending.length > 0) {
    const schema = pending.pop();
    if (!isPlainObject(schema) || seen.has(schema)) continue;
    seen.add(schema);
    if (typeof schema.$ref === 'string') {
      pending.push(resolveReference(root, schema.$ref));
    }
    SCHEMA_KEYWORDS.forEach(keyword => pending.push(schema[keyword]));
    SCHEMA_LIST_KEYWORDS.forEach(keyword => {
      const list = schema[keyword];
      if (Array.isArray(list)) pending.push(...list);
    });
    SCHEMA_MAP_KEYWORDS.forEach(keyword => {
      const map = schema[keyword];
      if (isPlainObject(map)) pending.push(...Object.values(map));
    });
  }
}

/** One validation run: the root for `$ref`, the errors, the recursion guard. */
interface Run {
  root: Schema;
  errors: SchemaViolation[];
  /** Schema objects under evaluation, each with the instance paths it is on. */
  active: Map<object, Set<string>>;
}

function check(
  run: Run,
  schema: Schema,
  data: unknown,
  instancePath: string,
  schemaPath: string,
): boolean {
  if (schema === true) return true;
  if (schema === false) {
    run.errors.push({
      keyword: 'false schema',
      instancePath,
      schemaPath,
      params: {},
      message: 'boolean schema is false',
      schema: false,
      parentSchema: {},
      data,
    });
    return false;
  }

  // A schema that reaches itself on the same value without consuming any of
  // it (`{"$ref": "#"}`, or two definitions that reference each other) says
  // nothing more the second time round.
  const paths = run.active.get(schema) ?? new Set<string>();
  if (paths.has(instancePath)) return true;
  paths.add(instancePath);
  run.active.set(schema, paths);

  let valid = true;
  const fail = (
    keyword: string,
    params: Record<string, unknown>,
    message: string,
    at: string = instancePath,
  ): void => {
    valid = false;
    run.errors.push({
      keyword,
      instancePath: at,
      schemaPath: `${schemaPath}/${keyword}`,
      params,
      message,
      schema: schema[keyword],
      parentSchema: schema,
      data,
    });
  };
  /** Validates against a sub-schema, collecting its errors with the rest. */
  const descend = (
    sub: Schema,
    value: unknown,
    at: string,
    keywordPath: string,
  ): boolean => {
    const passed = check(run, sub, value, at, `${schemaPath}/${keywordPath}`);
    if (!passed) valid = false;
    return passed;
  };
  /** Validates against a sub-schema without reporting what it finds. */
  const probe = (sub: Schema, keywordPath: string): SchemaViolation[] => {
    const trial: Run = { root: run.root, errors: [], active: run.active };
    check(trial, sub, data, instancePath, `${schemaPath}/${keywordPath}`);
    return trial.errors;
  };

  if (typeof schema.$ref === 'string') {
    const target = resolveReference(run.root, schema.$ref);
    if (!check(run, target, data, instancePath, schema.$ref)) valid = false;
  }

  const { type } = schema;
  if (typeof type === 'string' || Array.isArray(type)) {
    const types = (Array.isArray(type) ? type : [type]).filter(
      (name): name is string => typeof name === 'string',
    );
    if (types.length > 0 && !types.some(name => matchesType(name, data))) {
      fail('type', { type }, `must be ${types.join(',')}`);
    }
  }

  if (Array.isArray(schema.enum)) {
    const allowed = schema.enum;
    if (!allowed.some(value => isEqual(value, data))) {
      fail(
        'enum',
        { allowedValues: allowed },
        'must be equal to one of the allowed values',
      );
    }
  }

  if (hasOwn(schema, 'const') && !isEqual(schema.const, data)) {
    fail('const', { allowedValue: schema.const }, 'must be equal to constant');
  }

  if (typeof data === 'number') {
    const bounds: [string, string, (limit: number) => boolean][] = [
      ['minimum', '>=', limit => data >= limit],
      ['maximum', '<=', limit => data <= limit],
      ['exclusiveMinimum', '>', limit => data > limit],
      ['exclusiveMaximum', '<', limit => data < limit],
    ];
    bounds.forEach(([keyword, comparison, holds]) => {
      const limit = schema[keyword];
      if (typeof limit === 'number' && !holds(limit)) {
        fail(keyword, { comparison, limit }, `must be ${comparison} ${limit}`);
      }
    });
    const { multipleOf } = schema;
    if (typeof multipleOf === 'number' && multipleOf > 0) {
      const quotient = data / multipleOf;
      if (Math.abs(quotient - Math.round(quotient)) > 1e-9) {
        fail('multipleOf', { multipleOf }, `must be multiple of ${multipleOf}`);
      }
    }
  }

  if (typeof data === 'string') {
    const { minLength, maxLength, pattern } = schema;
    if (typeof minLength === 'number' && codePoints(data) < minLength) {
      fail(
        'minLength',
        { limit: minLength },
        `must NOT have fewer than ${minLength} characters`,
      );
    }
    if (typeof maxLength === 'number' && codePoints(data) > maxLength) {
      fail(
        'maxLength',
        { limit: maxLength },
        `must NOT have more than ${maxLength} characters`,
      );
    }
    if (typeof pattern === 'string') {
      let expression: RegExp | undefined;
      try {
        expression = new RegExp(pattern, 'u');
      } catch {
        // A pattern this engine cannot read (Python-only syntax, say)
        // constrains nothing here; the server applies it.
        expression = undefined;
      }
      if (expression && !expression.test(data)) {
        fail('pattern', { pattern }, `must match pattern "${pattern}"`);
      }
    }
  }

  if (Array.isArray(data)) {
    const { minItems, maxItems, uniqueItems, contains } = schema;
    if (typeof minItems === 'number' && data.length < minItems) {
      fail(
        'minItems',
        { limit: minItems },
        `must NOT have fewer than ${minItems} items`,
      );
    }
    if (typeof maxItems === 'number' && data.length > maxItems) {
      fail(
        'maxItems',
        { limit: maxItems },
        `must NOT have more than ${maxItems} items`,
      );
    }
    if (uniqueItems === true) {
      for (let j = 1; j < data.length; j += 1) {
        const i = data.slice(0, j).findIndex(item => isEqual(item, data[j]));
        if (i !== -1) {
          fail(
            'uniqueItems',
            { i: j, j: i },
            `must NOT have duplicate items (items ## ${i} and ${j} are identical)`,
          );
          break;
        }
      }
    }
    // `prefixItems` describes the leading items one by one; `items` then
    // describes the rest (or every item, when there is no prefix). The older
    // spelling — `items` as a list — is read the same way as `prefixItems`.
    const prefix = isSchemaList(schema.prefixItems)
      ? schema.prefixItems
      : undefined;
    const tuple = !prefix && isSchemaList(schema.items) ? schema.items : prefix;
    const tupleKeyword = prefix ? 'prefixItems' : 'items';
    const rest =
      !Array.isArray(schema.items) && isSchema(schema.items)
        ? schema.items
        : undefined;
    data.forEach((item, index) => {
      const at = `${instancePath}/${index}`;
      if (tuple && index < tuple.length) {
        descend(tuple[index], item, at, `${tupleKeyword}/${index}`);
      } else if (rest !== undefined) {
        descend(rest, item, at, 'items');
      }
    });
    if (isSchema(contains)) {
      const attempts = data.map((item, index) => {
        const trial: Run = { root: run.root, errors: [], active: run.active };
        check(
          trial,
          contains,
          item,
          `${instancePath}/${index}`,
          `${schemaPath}/contains`,
        );
        return trial.errors;
      });
      if (!attempts.some(errors => errors.length === 0)) {
        run.errors.push(...attempts.flat());
        fail(
          'contains',
          { minContains: 1 },
          'must contain at least 1 valid item(s)',
        );
      }
    }
  }

  if (isPlainObject(data)) {
    const properties = isPlainObject(schema.properties)
      ? schema.properties
      : {};
    if (Array.isArray(schema.required)) {
      schema.required.forEach(name => {
        if (typeof name === 'string' && !hasOwn(data, name)) {
          fail(
            'required',
            { missingProperty: name },
            `must have required property '${name}'`,
          );
        }
      });
    }
    Object.keys(data).forEach(name => {
      const at = `${instancePath}/${escapePointer(name)}`;
      if (hasOwn(properties, name)) {
        const sub = properties[name];
        if (isSchema(sub)) {
          descend(sub, data[name], at, `properties/${escapePointer(name)}`);
        }
        return;
      }
      const { additionalProperties } = schema;
      if (additionalProperties === false) {
        fail(
          'additionalProperties',
          { additionalProperty: name },
          'must NOT have additional properties',
        );
      } else if (isPlainObject(additionalProperties)) {
        descend(additionalProperties, data[name], at, 'additionalProperties');
      }
    });
  }

  if (isSchemaList(schema.allOf)) {
    schema.allOf.forEach((sub, index) =>
      descend(sub, data, instancePath, `allOf/${index}`),
    );
  }

  if (isSchemaList(schema.anyOf)) {
    const attempts = schema.anyOf.map((sub, index) =>
      probe(sub, `anyOf/${index}`),
    );
    if (!attempts.some(errors => errors.length === 0)) {
      run.errors.push(...attempts.flat());
      fail('anyOf', {}, 'must match a schema in anyOf');
    }
  }

  if (isSchemaList(schema.oneOf)) {
    const attempts = schema.oneOf.map((sub, index) =>
      probe(sub, `oneOf/${index}`),
    );
    const passing = attempts
      .map((errors, index) => (errors.length === 0 ? index : -1))
      .filter(index => index !== -1);
    if (passing.length !== 1) {
      run.errors.push(...attempts.flat());
      fail(
        'oneOf',
        { passingSchemas: passing.length > 1 ? passing.slice(0, 2) : null },
        'must match exactly one schema in oneOf',
      );
    }
  }

  if (isSchema(schema.not) && probe(schema.not, 'not').length === 0) {
    fail('not', {}, 'must NOT be valid');
  }

  if (isSchema(schema.if)) {
    const branch = probe(schema.if, 'if').length === 0 ? 'then' : 'else';
    const sub = schema[branch];
    if (isSchema(sub) && !descend(sub, data, instancePath, branch)) {
      fail('if', { failingKeyword: branch }, `must match "${branch}" schema`);
    }
  }

  paths.delete(instancePath);
  if (paths.size === 0) run.active.delete(schema);
  return valid;
}

function toSchema(schema: unknown): Schema {
  if (!isSchema(schema)) {
    throw new Error('schema must be object or boolean');
  }
  return schema;
}

/**
 * Builds the validator. Each `compile` checks the schema's references and
 * returns a function that interprets it; nothing is cached between calls, so
 * a schema object that is edited in place is read as it stands.
 */
export function createInterpretingValidator(): InterpretingValidator {
  const validator: InterpretingValidator = {
    errors: null,
    compile(input: unknown): InterpretingValidateFunction {
      const schema = toSchema(input);
      checkReferences(schema);
      const validate: InterpretingValidateFunction = Object.assign(
        (data: unknown): boolean => {
          const run: Run = { root: schema, errors: [], active: new Map() };
          const valid = check(run, schema, data, '', '#');
          validate.errors = valid ? null : run.errors;
          return valid;
        },
        { errors: null, schema },
      );
      return validate;
    },
    validate(input: unknown, data: unknown): boolean {
      const validate = validator.compile(input);
      const valid = validate(data);
      validator.errors = validate.errors;
      return valid;
    },
  };
  return validator;
}

/**
 * The validator every JsonForms instance in the builder is given through its
 * `ajv` prop. Without it JsonForms creates a real Ajv, whose first `compile`
 * needs `'unsafe-eval'`.
 *
 * The cast is the seam between the two types: JsonForms declares the prop as
 * Ajv's class, of which it calls `compile` and `validate` only.
 */
export const interpretingAjv = createInterpretingValidator() as unknown as Ajv;
