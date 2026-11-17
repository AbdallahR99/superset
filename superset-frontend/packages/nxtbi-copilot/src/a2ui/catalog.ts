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
  hasOwn,
  identifier,
  isObject,
  onlyKeys,
  pointerParts,
  requireValue,
} from './json';
import {
  BASIC_A2UI_CATALOG_ID,
  NXTBI_A2UI_CATALOG_ID,
  type A2uiCatalog,
  type A2uiCatalogComponent,
  type A2uiComponent,
  type A2uiJson,
  type A2uiJsonObject,
} from './types';

type Check = (value: A2uiJson | undefined) => boolean;
type Properties = Readonly<Record<string, Check>>;

const string: Check = value => typeof value === 'string';
const boolean: Check = value => typeof value === 'boolean';
const number: Check = value => typeof value === 'number';
const integer: Check = value =>
  typeof value === 'number' && Number.isInteger(value);
const enumOf =
  (...values: string[]): Check =>
  value =>
    typeof value === 'string' && values.includes(value);

const arrayOf =
  (check: Check): Check =>
  value =>
    Array.isArray(value) && value.every(item => check(item));

const objectOf =
  (required: Properties, optional: Properties = {}): Check =>
  value => {
    if (!isObject(value)) return false;
    return (
      Object.entries(required).every(([key, check]) => check(value[key])) &&
      Object.entries(value).every(([key, item]) => {
        const check = hasOwn(required, key)
          ? required[key]
          : hasOwn(optional, key)
            ? optional[key]
            : undefined;
        return typeof check === 'function' && check(item);
      })
    );
  };

export function isExpression(value: A2uiJson | undefined): boolean {
  return isObject(value) && (hasOwn(value, '@path') || hasOwn(value, '@call'));
}

const dynamic =
  (check: Check): Check =>
  value =>
    isExpression(value) || check(value);

const dynamicString = dynamic(string);
const dynamicNumber = dynamic(number);
const dynamicBoolean = dynamic(boolean);
const childList: Check = value =>
  arrayOf(identifier)(value) ||
  objectOf({ componentId: identifier, path: string })(value);

const option = objectOf({ label: dynamicString, value: identifier });
const options = arrayOf(option);
const action = objectOf({
  event: objectOf(
    { name: identifier },
    { context: isObject, userMessage: dynamicString },
  ),
});
const checks = arrayOf(
  objectOf({ condition: isExpression }, { message: string }),
);

const align = enumOf('start', 'center', 'end', 'stretch');
const justify = enumOf(
  'start',
  'center',
  'end',
  'stretch',
  'spaceBetween',
  'spaceAround',
  'spaceEvenly',
);

function childrenInList(props: A2uiJsonObject): readonly string[] {
  const { children } = props;
  if (Array.isArray(children)) return children.filter(identifier);
  return isObject(children) && identifier(children.componentId)
    ? [children.componentId]
    : [];
}

function childrenInFields(...keys: string[]) {
  return (props: A2uiJsonObject) =>
    keys.map(key => props[key]).filter(identifier);
}

function childrenInTabs(props: A2uiJsonObject): readonly string[] {
  return Array.isArray(props.tabs)
    ? props.tabs
        .filter(isObject)
        .map(tab => tab.child)
        .filter(identifier)
    : [];
}

function definition(
  required: Properties,
  optional: Properties = {},
  children?: A2uiCatalogComponent['children'],
): A2uiCatalogComponent {
  return {
    validate(props) {
      requireValue(
        objectOf(required, {
          weight: value =>
            integer(value) && Number(value) >= 0 && Number(value) <= 12,
          ...optional,
        })(props),
        'Invalid or unsupported A2UI component property',
      );
      if (isObject(props.children) && typeof props.children.path === 'string') {
        pointerParts(props.children.path);
      }
    },
    ...(children ? { children } : {}),
  };
}

const basicCatalog: A2uiCatalog = {
  id: BASIC_A2UI_CATALOG_ID,
  components: {
    Text: definition(
      { text: dynamicString },
      { variant: enumOf('body', 'caption') },
    ),
    Icon: definition({
      name: enumOf(
        'check',
        'close',
        'info',
        'warning',
        'search',
        'add',
        'remove',
        'arrow_back',
        'arrow_forward',
        'mail',
        'star',
      ),
    }),
    Row: definition(
      { children: childList },
      { justify, align },
      childrenInList,
    ),
    Column: definition(
      { children: childList },
      { justify, align },
      childrenInList,
    ),
    List: definition(
      { children: childList },
      { direction: enumOf('vertical', 'horizontal'), align },
      childrenInList,
    ),
    Card: definition({ child: identifier }, {}, childrenInFields('child')),
    Tabs: definition(
      {
        tabs: value =>
          Array.isArray(value) &&
          value.length > 0 &&
          arrayOf(objectOf({ title: dynamicString, child: identifier }))(value),
      },
      {},
      childrenInTabs,
    ),
    Modal: definition(
      { trigger: identifier, content: identifier },
      {},
      childrenInFields('trigger', 'content'),
    ),
    Divider: definition({}, { axis: enumOf('horizontal', 'vertical') }),
    Button: definition(
      { child: identifier, action },
      {
        variant: enumOf('default', 'primary', 'borderless'),
        '@checks': checks,
      },
      childrenInFields('child'),
    ),
    TextField: definition(
      { label: dynamicString, value: dynamicString },
      {
        placeholder: dynamicString,
        variant: enumOf('shortText', 'longText', 'number', 'obscured'),
        '@checks': checks,
      },
    ),
    CheckBox: definition(
      { label: dynamicString, value: dynamicBoolean },
      { '@checks': checks },
    ),
    ChoicePicker: definition(
      { options, value: dynamic(arrayOf(string)) },
      {
        label: dynamicString,
        variant: enumOf('mutuallyExclusive', 'multipleSelection'),
        displayStyle: enumOf('checkbox', 'chips'),
        filterable: boolean,
        '@checks': checks,
      },
    ),
    Slider: definition(
      { value: dynamicNumber, max: number },
      {
        label: dynamicString,
        min: number,
        steps: value => integer(value) && Number(value) > 0,
        '@checks': checks,
      },
    ),
    DateTimeInput: definition(
      { value: dynamicString },
      {
        label: dynamicString,
        enableDate: boolean,
        enableTime: boolean,
        min: dynamicString,
        max: dynamicString,
        '@checks': checks,
      },
    ),
  },
};

const nxtbiCatalog: A2uiCatalog = {
  id: NXTBI_A2UI_CATALOG_ID,
  components: {
    Form: definition(
      { children: childList },
      { legend: dynamicString },
      childrenInList,
    ),
    Grid: definition(
      { children: childList },
      {
        columns: value =>
          integer(value) && Number(value) >= 1 && Number(value) <= 4,
      },
      childrenInList,
    ),
    Select: definition(
      { label: dynamicString, value: dynamicString, options: dynamic(options) },
      { placeholder: dynamicString, '@checks': checks },
    ),
    Table: definition(
      {
        columns: arrayOf(objectOf({ key: identifier, label: dynamicString })),
        rows: dynamic(arrayOf(isObject)),
      },
      { caption: dynamicString },
    ),
    Metric: definition(
      {
        label: dynamicString,
        value: dynamic(value => string(value) || number(value)),
      },
      { detail: dynamicString },
    ),
    Notice: definition(
      { text: dynamicString },
      { tone: enumOf('info', 'success', 'warning', 'error') },
    ),
  },
};

const functionParameters = {
  required: [['value'], []],
  length: [['value'], ['min', 'max']],
  numeric: [['value'], ['min', 'max']],
  email: [['value'], []],
  formatString: [['value'], []],
  formatNumber: [['value'], ['decimals', 'grouping']],
  formatCurrency: [
    ['value', 'currency'],
    ['decimals', 'grouping'],
  ],
  pluralize: [
    ['value', 'other'],
    ['zero', 'one', 'two', 'few', 'many'],
  ],
  and: [['values'], []],
  or: [['values'], []],
  not: [['value'], []],
  '@index': [[], ['offset']],
} as const;

function validateExpressions(value: A2uiJson): void {
  if (Array.isArray(value)) {
    value.forEach(validateExpressions);
    return;
  }
  if (!isObject(value)) return;
  if (hasOwn(value, '@path')) {
    onlyKeys(value, ['@path']);
    requireValue(
      typeof value['@path'] === 'string',
      'Expected an A2UI data path',
    );
    pointerParts(value['@path']);
    return;
  }
  if (hasOwn(value, '@call')) {
    onlyKeys(value, ['@call', 'args', 'catalogId']);
    const name = value['@call'];
    requireValue(
      typeof name === 'string' && hasOwn(functionParameters, name),
      'Unsupported A2UI function',
    );
    requireValue(
      !hasOwn(value, 'catalogId') || value.catalogId === BASIC_A2UI_CATALOG_ID,
      'Unsupported A2UI function catalog',
    );
    const [required, optional] =
      functionParameters[name as keyof typeof functionParameters];
    const args = hasOwn(value, 'args') ? value.args : {};
    requireValue(isObject(args), 'Invalid A2UI function arguments');
    onlyKeys(args, [...required, ...optional]);
    requireValue(
      required.every(key => hasOwn(args, key)),
      'Missing A2UI function argument',
    );
    Object.values(args).forEach(validateExpressions);
    return;
  }
  Object.values(value).forEach(validateExpressions);
}

const commonKeys = [
  'id',
  'component',
  '@catalogId',
  '@accessibility',
  '@metadata',
];

export function componentProps(component: A2uiComponent): A2uiJsonObject {
  return Object.fromEntries(
    Object.entries(component).filter(([key]) => !commonKeys.includes(key)),
  );
}

export function getA2uiCatalog(
  id: string,
  catalogs: readonly A2uiCatalog[] = [],
): A2uiCatalog | undefined {
  if (id === BASIC_A2UI_CATALOG_ID) return basicCatalog;
  if (id === NXTBI_A2UI_CATALOG_ID) return nxtbiCatalog;
  return catalogs.find(catalog => catalog.id === id);
}

export function getComponentDefinition(
  component: A2uiComponent,
  defaultCatalog?: string,
  catalogs: readonly A2uiCatalog[] = [],
): { catalog: A2uiCatalog; definition: A2uiCatalogComponent } | undefined {
  const id = component['@catalogId'] ?? defaultCatalog;
  if (typeof id === 'string') {
    const catalog = getA2uiCatalog(id, catalogs);
    if (catalog && hasOwn(catalog.components, component.component)) {
      return { catalog, definition: catalog.components[component.component] };
    }
    return undefined;
  }
  const possible = [basicCatalog, nxtbiCatalog, ...catalogs].filter(catalog =>
    hasOwn(catalog.components, component.component),
  );
  if (possible.length !== 1) return undefined;
  return {
    catalog: possible[0],
    definition: possible[0].components[component.component],
  };
}

export function validateMetadata(value: A2uiJson): void {
  requireValue(isObject(value), 'Invalid A2UI metadata');
  onlyKeys(value, ['extensions']);
  requireValue(
    !hasOwn(value, 'extensions') || isObject(value.extensions),
    'Invalid A2UI extensions metadata',
  );
}

export function validateComponent(
  value: A2uiJson,
  defaultCatalog?: string,
  catalogs: readonly A2uiCatalog[] = [],
): A2uiComponent {
  requireValue(
    isObject(value) && identifier(value.id) && identifier(value.component),
    'An A2UI component must have an ID and a type',
  );
  requireValue(
    !hasOwn(value, '@catalogId') || identifier(value['@catalogId']),
    'Invalid A2UI catalog identifier',
  );
  const component = value as A2uiComponent;
  const selected = getComponentDefinition(component, defaultCatalog, catalogs);
  requireValue(
    selected !== undefined,
    `Unsupported A2UI component: ${component.component}`,
  );
  const props = componentProps(component);
  validateExpressions(props);
  selected.definition.validate(props);
  if (hasOwn(component, '@metadata')) validateMetadata(component['@metadata']);
  if (hasOwn(component, '@accessibility')) {
    const accessibility = component['@accessibility'];
    requireValue(
      objectOf(
        {},
        {
          label: dynamicString,
          description: dynamicString,
          live: enumOf('off', 'polite', 'assertive'),
          hidden: dynamicBoolean,
        },
      )(accessibility),
      'Invalid A2UI accessibility properties',
    );
    validateExpressions(accessibility);
  }
  return component;
}
