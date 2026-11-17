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
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
} from 'react';
import {
  asBoolean,
  displayValue,
  resolveA2uiValue,
  type A2uiEvaluation,
} from './bindings';
import { componentProps, getComponentDefinition } from './catalog';
import {
  encodePointer,
  hasOwn,
  identifier,
  isObject,
  pointerParts,
  readA2uiData,
} from './json';
import {
  A2UI_VERSION,
  BASIC_A2UI_CATALOG_ID,
  NXTBI_A2UI_CATALOG_ID,
  type A2uiAction,
  type A2uiCatalog,
  type A2uiComponent,
  type A2uiJson,
  type A2uiJsonObject,
  type A2uiState,
  type A2uiSurface,
} from './types';

export interface A2uiCustomComponentProps {
  component: A2uiComponent;
  dataModel: A2uiJsonObject;
  props: A2uiJsonObject;
  renderChild(id: string): ReactNode;
  dispatchAction(event: A2uiAction['action']): void;
  setData(path: string, value: A2uiJson): void;
}

export interface A2uiReactCatalog extends A2uiCatalog {
  renderers: Readonly<Record<string, ComponentType<A2uiCustomComponentProps>>>;
}

export interface A2uiRendererProps {
  state: A2uiState;
  surfaceIds?: readonly string[];
  direction?: 'ltr' | 'rtl';
  locale?: string;
  catalogs?: readonly A2uiReactCatalog[];
  allowedActions?: readonly string[];
  onAction?: (action: A2uiAction) => void;
  onDataChange?: (surfaceId: string, path: string, value: A2uiJson) => void;
}

interface RenderNode {
  component: A2uiComponent;
  catalogId: string;
  scope: A2uiEvaluation;
  children: readonly RenderNode[];
}

type ViewOptions = Omit<A2uiRendererProps, 'state' | 'surfaceIds'> & {
  surfaceId: string;
};

const border = '1px solid var(--nxtbi-a2ui-border, #cbd8d4)';
const panel: CSSProperties = {
  border,
  borderRadius: 12,
  padding: 12,
  minWidth: 0,
};
const stack: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  minWidth: 0,
};
const fieldStyle: CSSProperties = {
  color: 'inherit',
  background: 'var(--nxtbi-a2ui-background, transparent)',
  font: 'inherit',
  border,
  borderRadius: 8,
  padding: '7px 9px',
  minWidth: 0,
  maxWidth: '100%',
};
const buttonStyle: CSSProperties = {
  ...fieldStyle,
  minHeight: 32,
  cursor: 'pointer',
};

const rtlLanguages = new Set(['ar', 'fa', 'he', 'ur', 'ps', 'dv', 'yi']);
const justifyValues: Readonly<Record<string, CSSProperties['justifyContent']>> =
  {
    start: 'flex-start',
    end: 'flex-end',
    center: 'center',
    spaceAround: 'space-around',
    spaceBetween: 'space-between',
    spaceEvenly: 'space-evenly',
    stretch: 'stretch',
  };
const alignValues: Readonly<Record<string, CSSProperties['alignItems']>> = {
  start: 'flex-start',
  end: 'flex-end',
  center: 'center',
  stretch: 'stretch',
};

/** Project a streaming adjacency list into a bounded tree with collection scopes. */
function projectSurface(
  surface: A2uiSurface,
  options: ViewOptions,
): RenderNode | undefined {
  let remaining = 800;

  function visit(
    id: string,
    scope: A2uiEvaluation,
    ancestors: readonly string[],
  ): RenderNode | undefined {
    if (
      remaining <= 0 ||
      ancestors.length > 24 ||
      ancestors.includes(id) ||
      !hasOwn(surface.components, id)
    ) {
      return undefined;
    }
    const component = surface.components[id];
    const selected = getComponentDefinition(
      component,
      surface.catalogId,
      options.catalogs,
    );
    if (!selected) return undefined;
    remaining -= 1;

    const props = componentProps(component);
    const ids = selected.definition.children?.(props) ?? [];
    const path = [...ancestors, id];
    const children: RenderNode[] = [];
    const template = props.children;
    if (
      isObject(template) &&
      identifier(template.componentId) &&
      ids.includes(template.componentId) &&
      typeof template.path === 'string'
    ) {
      const templateId = template.componentId;
      const dataPath = pointerParts(template.path, scope.path);
      const values = readA2uiData(scope.dataModel, dataPath);
      if (Array.isArray(values)) {
        values.slice(0, 200).forEach((_, index) => {
          const child = visit(
            templateId,
            { ...scope, path: [...dataPath, String(index)], index },
            path,
          );
          if (child) children.push(child);
        });
      }
    } else {
      ids.forEach(childId => {
        const child = visit(childId, scope, path);
        if (child) children.push(child);
      });
    }
    return { component, catalogId: selected.catalog.id, scope, children };
  }

  return visit(
    'root',
    { path: [], dataModel: surface.dataModel, locale: options.locale },
    [],
  );
}

function allowsAction(options: ViewOptions, name: string): boolean {
  return Boolean(
    options.onAction &&
    (!options.allowedActions || options.allowedActions.includes(name)),
  );
}

function dispatch(
  options: ViewOptions,
  component: A2uiComponent,
  event: { name: string; context: A2uiJsonObject; userMessage?: string },
): void {
  if (!allowsAction(options, event.name)) return;
  options.onAction?.({
    version: A2UI_VERSION,
    action: {
      name: event.name,
      surfaceId: options.surfaceId,
      sourceComponentId: component.id,
      timestamp: new Date().toISOString(),
      context: event.context,
      ...(event.userMessage !== undefined
        ? { userMessage: event.userMessage }
        : {}),
    },
  });
}

function checkMessage(checks: A2uiJson | undefined): string | undefined {
  if (!Array.isArray(checks)) return undefined;
  for (const check of checks) {
    if (!isObject(check) || asBoolean(check.condition)) continue;
    return (
      displayValue(check.message) ||
      (isObject(check.condition)
        ? displayValue(check.condition.message)
        : '') ||
      'Check this value'
    );
  }
  return undefined;
}

function getOptionList(
  value: A2uiJson | undefined,
): { label: string; value: string }[] {
  if (!Array.isArray(value)) return [];
  const options: { label: string; value: string }[] = [];
  const seen = new Set<string>();
  for (const item of value.slice(0, 300)) {
    if (
      isObject(item) &&
      typeof item.value === 'string' &&
      !seen.has(item.value)
    ) {
      seen.add(item.value);
      options.push({ label: displayValue(item.label), value: item.value });
    }
  }
  return options;
}

function InputFeedback({ message }: { message?: string }): ReactElement | null {
  return message ? (
    <small role="status" style={{ color: 'var(--nxtbi-a2ui-error, #a02828)' }}>
      {message}
    </small>
  ) : null;
}

function TabsView({
  node,
  props,
  options,
}: {
  node: RenderNode;
  props: A2uiJsonObject;
  options: ViewOptions;
}): ReactElement {
  const [selected, setSelected] = useState(0);
  const tabs = Array.isArray(props.tabs) ? props.tabs.filter(isObject) : [];
  const activeIndex = Math.min(selected, tabs.length - 1);
  const active = tabs[activeIndex];
  const child = node.children.find(
    entry => entry.component.id === active?.child,
  );

  return (
    <div style={stack}>
      <div role="tablist" style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {tabs.map((tab, index) => (
          <button
            key={`${index}-${displayValue(tab.child)}`}
            type="button"
            role="tab"
            aria-selected={activeIndex === index}
            style={{
              ...buttonStyle,
              fontWeight: activeIndex === index ? 700 : 400,
            }}
            onClick={() => setSelected(index)}
          >
            {displayValue(tab.title)}
          </button>
        ))}
      </div>
      {child && (
        <div role="tabpanel" aria-label={displayValue(active?.title)}>
          <NodeView node={child} options={options} />
        </div>
      )}
    </div>
  );
}

function ModalView({
  node,
  props,
  options,
}: {
  node: RenderNode;
  props: A2uiJsonObject;
  options: ViewOptions;
}): ReactElement {
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (open && element && !element.open) {
      if (typeof element.showModal === 'function') element.showModal();
      else element.setAttribute('open', '');
    }
  }, [open]);
  const trigger = node.children.find(
    entry => entry.component.id === props.trigger,
  );
  const content = node.children.find(
    entry => entry.component.id === props.content,
  );
  const closeLabel = options.locale?.startsWith('ar') ? 'إغلاق' : 'Close';
  const openLabel = options.locale?.startsWith('ar') ? 'فتح' : 'Open';

  return (
    <>
      {trigger?.component.component === 'Button' ? (
        <NodeView
          node={trigger}
          options={options}
          activate={() => setOpen(true)}
        />
      ) : (
        <button type="button" style={buttonStyle} onClick={() => setOpen(true)}>
          {trigger?.component.component === 'Text'
            ? displayValue(
                resolveA2uiValue(trigger.component.text, trigger.scope),
              )
            : openLabel}
        </button>
      )}
      {open && (
        <dialog
          ref={dialog}
          aria-label={openLabel}
          onClose={() => setOpen(false)}
          onCancel={event => {
            event.preventDefault();
            setOpen(false);
          }}
          style={{
            ...panel,
            maxWidth: 'min(90vw, 38rem)',
            color: 'inherit',
            background: 'var(--nxtbi-a2ui-background, Canvas)',
          }}
        >
          {content && <NodeView node={content} options={options} />}
          <button
            type="button"
            onClick={() => setOpen(false)}
            style={{ ...buttonStyle, marginBlockStart: 8 }}
          >
            {closeLabel}
          </button>
        </dialog>
      )}
    </>
  );
}

function DataTable({ props }: { props: A2uiJsonObject }): ReactElement {
  const columns = Array.isArray(props.columns)
    ? props.columns.filter(isObject)
    : [];
  const rows = Array.isArray(props.rows)
    ? props.rows.filter(isObject).slice(0, 200)
    : [];
  const caption = displayValue(props.caption);
  const cellStyle: CSSProperties = {
    borderBlockEnd: border,
    padding: '7px 9px',
    textAlign: 'start',
  };

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ borderCollapse: 'collapse', width: '100%' }}>
        {caption && (
          <caption
            style={{ textAlign: 'start', paddingBlockEnd: 8, fontWeight: 700 }}
          >
            {caption}
          </caption>
        )}
        <thead>
          <tr>
            {columns.map((column, index) => (
              <th
                key={`${index}-${displayValue(column.key)}`}
                scope="col"
                style={cellStyle}
              >
                {displayValue(column.label)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            // Rows are stateless display data; wire rows do not require stable IDs.
            // eslint-disable-next-line react/no-array-index-key
            <tr key={index}>
              {columns.map((column, columnIndex) => {
                const key = displayValue(column.key);
                return (
                  <td key={`${columnIndex}-${key}`} style={cellStyle}>
                    <bdi>{hasOwn(row, key) ? displayValue(row[key]) : ''}</bdi>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const icons: Readonly<Record<string, string>> = {
  check: '✓',
  close: '×',
  info: 'ⓘ',
  warning: '!',
  search: '⌕',
  add: '+',
  remove: '−',
  arrow_back: '←',
  arrow_forward: '→',
  mail: '✉',
  star: '★',
};

function NodeView({
  node,
  options,
  activate,
}: {
  node: RenderNode;
  options: ViewOptions;
  activate?: () => void;
}): ReactElement | null {
  const { component, scope } = node;
  const rawProps = componentProps(component);
  const resolved = resolveA2uiValue(rawProps, scope);
  const props = isObject(resolved) ? resolved : {};
  const [literal, setLiteral] = useState<{
    original: A2uiJson | undefined;
    value: A2uiJson;
  }>();
  const [touched, setTouched] = useState(false);
  const [query, setQuery] = useState('');
  const accessibility = resolveA2uiValue(component['@accessibility'], scope);
  const a11y = isObject(accessibility) ? accessibility : {};
  const live =
    a11y.live === 'off' || a11y.live === 'assertive' || a11y.live === 'polite'
      ? a11y.live
      : undefined;
  const error = checkMessage(props['@checks']);
  const feedback = <InputFeedback message={touched ? error : undefined} />;

  const original = rawProps.value;
  const pointer =
    isObject(original) && typeof original['@path'] === 'string'
      ? original['@path']
      : undefined;
  const value =
    literal && Object.is(literal.original, original) && pointer === undefined
      ? literal.value
      : props.value;
  const locked = pointer !== undefined && !options.onDataChange;
  const label = displayValue(props.label);
  const update = (next: A2uiJson): void => {
    setTouched(true);
    if (pointer !== undefined) {
      options.onDataChange?.(
        options.surfaceId,
        encodePointer(pointerParts(pointer, scope.path)),
        next,
      );
    } else {
      setLiteral({ original, value: next });
    }
  };
  const childViews = () =>
    node.children.map((child, index) => (
      <NodeView
        key={`${child.component.id}-${index}`}
        node={child}
        options={options}
      />
    ));
  const inputProps = {
    disabled: locked,
    'aria-invalid': Boolean(touched && error),
    onBlur: () => setTouched(true),
  };
  let content: ReactNode;

  if (
    node.catalogId !== BASIC_A2UI_CATALOG_ID &&
    node.catalogId !== NXTBI_A2UI_CATALOG_ID
  ) {
    const catalog = options.catalogs?.find(
      entry => entry.id === node.catalogId,
    );
    const Custom =
      catalog && hasOwn(catalog.renderers, component.component)
        ? catalog.renderers[component.component]
        : undefined;
    if (!Custom) return null;
    content = (
      <Custom
        component={component}
        dataModel={scope.dataModel}
        props={props}
        renderChild={id => {
          const child = node.children.find(entry => entry.component.id === id);
          return child ? <NodeView node={child} options={options} /> : null;
        }}
        dispatchAction={event => dispatch(options, component, event)}
        setData={(path, next) =>
          options.onDataChange?.(
            options.surfaceId,
            encodePointer(pointerParts(path, scope.path)),
            next,
          )
        }
      />
    );
  } else {
    switch (component.component) {
      case 'Text': {
        const text = displayValue(props.text);
        const heading = /^(#{1,6}) +(.+)$/u.exec(text);
        content = heading ? (
          <div
            role="heading"
            aria-level={heading[1].length}
            style={{ fontWeight: 700, fontSize: '1.15em' }}
          >
            <bdi>{heading[2]}</bdi>
          </div>
        ) : (
          <bdi
            style={{
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
              fontSize: props.variant === 'caption' ? '.875em' : undefined,
            }}
          >
            {text}
          </bdi>
        );
        break;
      }
      case 'Icon': {
        const name = displayValue(props.name);
        const icon =
          options.direction === 'rtl' && name === 'arrow_back'
            ? '→'
            : options.direction === 'rtl' && name === 'arrow_forward'
              ? '←'
              : icons[name];
        content = <span aria-hidden="true">{icon}</span>;
        break;
      }
      case 'Row':
      case 'Column':
      case 'List': {
        const horizontal =
          component.component === 'Row' || props.direction === 'horizontal';
        content = (
          <div
            style={{
              ...stack,
              flexDirection: horizontal ? 'row' : 'column',
              flexWrap: horizontal ? 'wrap' : undefined,
              alignItems: alignValues[displayValue(props.align)],
              justifyContent: justifyValues[displayValue(props.justify)],
            }}
          >
            {childViews()}
          </div>
        );
        break;
      }
      case 'Card':
        content = <div style={panel}>{childViews()}</div>;
        break;
      case 'Form':
        content = (
          <fieldset style={{ ...panel, ...stack }}>
            {props.legend && <legend>{displayValue(props.legend)}</legend>}
            {childViews()}
          </fieldset>
        );
        break;
      case 'Grid': {
        const columns = typeof props.columns === 'number' ? props.columns : 2;
        content = (
          <div
            style={{
              display: 'grid',
              gap: 8,
              gridTemplateColumns: `repeat(auto-fit, minmax(min(100%, max(9rem, calc(${100 / columns}% - ${((columns - 1) * 8) / columns}px))), 1fr))`,
            }}
          >
            {childViews()}
          </div>
        );
        break;
      }
      case 'Tabs':
        content = <TabsView node={node} props={props} options={options} />;
        break;
      case 'Modal':
        content = <ModalView node={node} props={props} options={options} />;
        break;
      case 'Divider':
        content =
          props.axis === 'vertical' ? (
            <span
              role="separator"
              aria-orientation="vertical"
              style={{
                display: 'block',
                minHeight: 20,
                borderInlineStart: border,
              }}
            />
          ) : (
            <hr style={{ border: 0, borderBlockStart: border }} />
          );
        break;
      case 'Button': {
        const event =
          isObject(props.action) && isObject(props.action.event)
            ? props.action.event
            : {};
        const name = displayValue(event.name);
        const child = node.children[0];
        const childLabel =
          child?.component.component === 'Text'
            ? displayValue(resolveA2uiValue(child.component.text, child.scope))
            : child?.component.component === 'Icon'
              ? icons[displayValue(child.component.name)]
              : undefined;
        const disabled =
          Boolean(error) ||
          !childLabel ||
          (!activate && !allowsAction(options, name));
        content = (
          <button
            type="button"
            disabled={disabled}
            aria-label={displayValue(a11y.label) || undefined}
            title={error}
            style={{
              ...buttonStyle,
              ...(props.variant === 'primary'
                ? {
                    background: 'var(--nxtbi-a2ui-primary, #126c59)',
                    color: 'var(--nxtbi-a2ui-on-primary, white)',
                  }
                : {}),
              ...(props.variant === 'borderless' ? { border: 0 } : {}),
              ...(disabled ? { opacity: 0.55, cursor: 'default' } : {}),
            }}
            onClick={() => {
              if (activate) activate();
              else
                dispatch(options, component, {
                  name,
                  context: isObject(event.context) ? event.context : {},
                  userMessage:
                    typeof event.userMessage === 'string'
                      ? event.userMessage
                      : undefined,
                });
            }}
          >
            <bdi>{childLabel}</bdi>
          </button>
        );
        break;
      }
      case 'TextField': {
        const common = {
          ...inputProps,
          maxLength: 16_000,
          placeholder: displayValue(props.placeholder),
          value: displayValue(value),
          style: fieldStyle,
        };
        content = (
          <label style={stack}>
            {label}
            {props.variant === 'longText' ? (
              <textarea
                {...common}
                onChange={event => update(event.target.value)}
              />
            ) : (
              <input
                {...common}
                type={
                  props.variant === 'obscured'
                    ? 'password'
                    : props.variant === 'number'
                      ? 'number'
                      : 'text'
                }
                onChange={event => update(event.target.value)}
              />
            )}
            {feedback}
          </label>
        );
        break;
      }
      case 'CheckBox':
        content = (
          <label>
            <input
              {...inputProps}
              type="checkbox"
              checked={asBoolean(value)}
              onChange={event => update(event.target.checked)}
            />{' '}
            {label}
            {feedback}
          </label>
        );
        break;
      case 'ChoicePicker': {
        const selected = Array.isArray(value) ? value : [];
        const multiple = props.variant === 'multipleSelection';
        const entries = getOptionList(props.options).filter(option =>
          option.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
        );
        const searchLabel = options.locale?.startsWith('ar')
          ? 'بحث'
          : 'Search options';
        content = (
          <fieldset style={{ ...stack, border: 0, margin: 0, padding: 0 }}>
            {label && <legend>{label}</legend>}
            {props.filterable && (
              <input
                aria-label={searchLabel}
                style={fieldStyle}
                value={query}
                onChange={event => setQuery(event.target.value)}
              />
            )}
            <div
              style={{
                display: 'flex',
                flexDirection:
                  props.displayStyle === 'chips' ? 'row' : 'column',
                flexWrap: 'wrap',
                gap: 8,
              }}
            >
              {entries.map(option => {
                const checked = selected.includes(option.value);
                return (
                  <label key={option.value}>
                    <input
                      {...inputProps}
                      type={multiple ? 'checkbox' : 'radio'}
                      name={
                        multiple
                          ? undefined
                          : `${options.surfaceId}/${component.id}${encodePointer(scope.path)}`
                      }
                      checked={checked}
                      onChange={() =>
                        update(
                          multiple
                            ? checked
                              ? selected.filter(entry => entry !== option.value)
                              : [...selected, option.value]
                            : [option.value],
                        )
                      }
                    />{' '}
                    {option.label}
                  </label>
                );
              })}
            </div>
            {feedback}
          </fieldset>
        );
        break;
      }
      case 'Select': {
        const entries = getOptionList(props.options);
        content = (
          <label style={stack}>
            {label}
            <select
              {...inputProps}
              style={fieldStyle}
              value={displayValue(value)}
              onChange={event => update(event.target.value)}
            >
              <option value="">{displayValue(props.placeholder)}</option>
              {entries.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {feedback}
          </label>
        );
        break;
      }
      case 'Slider': {
        const min = typeof props.min === 'number' ? props.min : 0;
        const max =
          typeof props.max === 'number' ? Math.max(min, props.max) : min;
        content = (
          <label style={stack}>
            {label}
            <input
              {...inputProps}
              type="range"
              min={min}
              max={max}
              step={
                typeof props.steps === 'number' && max > min
                  ? (max - min) / props.steps
                  : 'any'
              }
              value={typeof value === 'number' ? value : min}
              onChange={event => update(event.target.valueAsNumber)}
            />
            {feedback}
          </label>
        );
        break;
      }
      case 'DateTimeInput': {
        const type = props.enableTime
          ? props.enableDate
            ? 'datetime-local'
            : 'time'
          : 'date';
        content = (
          <label style={stack}>
            {label}
            <input
              {...inputProps}
              type={type}
              min={displayValue(props.min) || undefined}
              max={displayValue(props.max) || undefined}
              value={displayValue(value).slice(
                0,
                type === 'datetime-local' ? 16 : type === 'date' ? 10 : 8,
              )}
              onChange={event => update(event.target.value)}
              style={fieldStyle}
            />
            {feedback}
          </label>
        );
        break;
      }
      case 'Table':
        content = <DataTable props={props} />;
        break;
      case 'Metric':
        content = (
          <div style={{ ...panel, ...stack }}>
            <div>{label}</div>
            <strong>
              <bdi>{displayValue(props.value)}</bdi>
            </strong>
            {props.detail && <small>{displayValue(props.detail)}</small>}
          </div>
        );
        break;
      case 'Notice':
        content = (
          <div role="status" style={panel} data-tone={displayValue(props.tone)}>
            {displayValue(props.text)}
          </div>
        );
        break;
      default:
        return null;
    }
  }
  return (
    <div
      className="nxtbi-a2ui-component"
      data-a2ui-component={component.component}
      aria-label={displayValue(a11y.label) || undefined}
      aria-description={displayValue(a11y.description) || undefined}
      aria-hidden={asBoolean(a11y.hidden) || undefined}
      aria-live={live}
      style={{
        minWidth: 0,
        flexGrow: typeof props.weight === 'number' ? props.weight : undefined,
      }}
    >
      {content}
    </div>
  );
}

/** Render a validated surface without exposing raw HTML, URLs, or DOM callbacks. */
export function A2uiRenderer({
  state,
  surfaceIds,
  direction,
  locale,
  ...callbacks
}: A2uiRendererProps): ReactElement | null {
  const surfaces = surfaceIds
    ? [...new Set(surfaceIds)]
        .filter(id => hasOwn(state.surfaces, id))
        .map(id => state.surfaces[id])
    : Object.values(state.surfaces);
  if (surfaces.length === 0) return null;
  const displayDirection =
    direction ??
    (locale
      ? rtlLanguages.has(locale.toLowerCase().split(/[-_]/u)[0])
        ? 'rtl'
        : 'ltr'
      : undefined);

  return (
    <div
      className="nxtbi-a2ui"
      dir={displayDirection}
      lang={locale}
      style={stack}
    >
      {surfaces.map(surface => {
        const options = {
          ...callbacks,
          surfaceId: surface.surfaceId,
          direction: displayDirection,
          locale,
        };
        const root = projectSurface(surface, options);
        return root ? (
          <section
            key={surface.surfaceId}
            data-a2ui-surface={surface.surfaceId}
          >
            <NodeView node={root} options={options} />
          </section>
        ) : null;
      })}
    </div>
  );
}
