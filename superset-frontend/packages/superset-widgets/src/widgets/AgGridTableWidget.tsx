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
import { useId, useMemo, useRef, useState } from 'react';
import { styled } from '@apache-superset/core/theme';
import { t } from '@apache-superset/core/translation';
import {
  Button,
  Flex,
  Loading,
  ThemedAgGridReact,
  Typography,
} from '@superset-ui/core/components';
import type {
  ColDef,
  GridReadyEvent,
} from '@superset-ui/core/components/ThemedAgGridReact';
import { formatTemporalLabel } from '../resolveBindings';
import type {
  QueryDataResult,
  WidgetDataBindingSpec,
  WidgetProps,
} from '../types';
import { useWidgetData } from '../useWidgetData';

const TYPE = 'ag-grid-table';
const ROWS_PER_PAGE = 50;

type GridApi = GridReadyEvent['api'];

interface AgGridTableWidgetProps extends WidgetProps {
  /** The host's displayed title after any dashboard content translation. */
  accessibleTitle?: string;
  /** The dashboard viewer opts into the native table as its initial view. */
  preferNativeTable?: boolean;
}

const TableScroll = styled.section`
  flex: 1;
  min-block-size: 0;
  overflow: auto;

  &:focus-visible {
    outline: 2px solid ${({ theme }) => theme.colorPrimary};
    outline-offset: -2px;
  }

  table {
    border-collapse: separate;
    border-spacing: 0;
    inline-size: 100%;
    font-size: ${({ theme }) => theme.fontSizeSM}px;
  }

  th,
  td {
    border-block-end: 1px solid ${({ theme }) => theme.colorBorderSecondary};
    min-inline-size: 8ch;
    overflow-wrap: anywhere;
    padding: ${({ theme }) => theme.sizeXXS}px ${({ theme }) => theme.sizeXS}px;
    text-align: start;
  }

  thead th {
    background: ${({ theme }) => theme.colorBgContainer};
    inset-block-start: 0;
    position: sticky;
    z-index: 1;
  }

  tbody th {
    font-weight: inherit;
  }
`;

// No module registration needed here, unlike `ChartWidget`'s own
// `echarts.use([...])` call — `setupAGGridModules()` runs once before any
// grid renders: at app bootstrap in Superset (see `src/views/App.tsx`), and
// from `SupersetProvider` in a host page.

function deriveColumnDefs(columns: string[]): ColDef[] {
  return columns.map(field => ({ field, headerName: field }));
}

/**
 * The column settings an authored `columnDefs` entry may carry, by the type
 * each must have. A column definition is data — stored with a saved widget or
 * passed by a host — but AG Grid compiles string "expressions" in fields such
 * as `valueGetter`, `valueFormatter` and `cellClassRules` into functions and
 * runs them, and hands `cellRenderer` / `headerComponent` / tooltip
 * components the DOM. Only declarative settings are let through — an
 * allowlist, so a setting AG Grid adds later is refused until it is listed —
 * and a definition written by one user can never run script, or place
 * markup, in the page of another.
 *
 * Text settings (`headerName`, `headerTooltip`) are drawn by AG Grid as text
 * content. Settings that name something (`type`, `cellDataType`, `sort`,
 * `pinned`, `valueFormat`) accept only the built-in names below.
 *
 * The settings are the ones the server accepts when a definition is stored
 * (`AG_GRID_COLUMN_SETTINGS` in `superset/widgets/safety.py`), which refuses
 * any other by name; `safety.parity.test.ts` reads both lists and compares.
 */
type ColumnRule =
  | 'string'
  | 'number'
  | 'boolean'
  | 'identifier'
  | readonly string[];

export const COLUMN_SETTINGS: Readonly<Record<string, ColumnRule>> = {
  field: 'identifier',
  colId: 'identifier',
  headerName: 'string',
  headerTooltip: 'string',
  type: ['numericColumn', 'rightAligned'],
  cellDataType: ['text', 'number', 'boolean', 'date', 'dateString', 'object'],
  valueFormat: ['date', 'decimal', 'percent'],
  valueFormatPrecision: 'number',
  sort: ['asc', 'desc'],
  pinned: ['left', 'right'],
  width: 'number',
  minWidth: 'number',
  maxWidth: 'number',
  flex: 'number',
  sortIndex: 'number',
  hide: 'boolean',
  sortable: 'boolean',
  resizable: 'boolean',
  filter: 'boolean',
  wrapText: 'boolean',
  autoHeight: 'boolean',
  wrapHeaderText: 'boolean',
  autoHeaderHeight: 'boolean',
  suppressMovable: 'boolean',
  lockPosition: 'boolean',
};

const MAX_COLUMNS = 500;
const MAX_TEXT_LENGTH = 500;
// A dotted `field` is a path AG Grid walks into the row: it must not be able
// to name anything on a prototype.
const UNSAFE_PATH = /(^|\.)(__proto__|constructor|prototype)(\.|$)/;

function columnSetting(
  rule: ColumnRule,
  value: unknown,
): string | number | boolean | undefined {
  if (typeof rule !== 'string') {
    return typeof value === 'string' && rule.includes(value)
      ? value
      : undefined;
  }
  if (rule === 'number') {
    return typeof value === 'number' && Number.isFinite(value)
      ? value
      : undefined;
  }
  if (rule === 'boolean') return typeof value === 'boolean' ? value : undefined;
  if (typeof value !== 'string' || value.length > MAX_TEXT_LENGTH) {
    return undefined;
  }
  if (rule === 'identifier' && UNSAFE_PATH.test(value)) return undefined;
  return value;
}

function formatDateCell({ value }: { value?: unknown }): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(formatTemporalLabel(value))
    : '';
}

/** Build grid columns from the allowed settings in authored definitions. */
export function sanitizeColumnDefs(
  columnDefs: unknown,
  locale?: string,
): ColDef[] {
  if (!Array.isArray(columnDefs)) return [];
  return columnDefs.slice(0, MAX_COLUMNS).flatMap(entry => {
    if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) {
      return [];
    }
    const authored = entry as Record<string, unknown>;
    const column: Record<string, string | number | boolean> = {};
    Object.keys(COLUMN_SETTINGS).forEach(key => {
      if (!Object.prototype.hasOwnProperty.call(authored, key)) return;
      const value = columnSetting(COLUMN_SETTINGS[key], authored[key]);
      if (value !== undefined) column[key] = value;
    });
    // A column that names no field shows nothing; schema-driven forms seed
    // such empty entries.
    if (typeof column.field !== 'string' || column.field === '') return [];

    const { valueFormat, valueFormatPrecision, ...gridColumn } = column;
    // AG Grid still sorts by the raw field.
    if (valueFormat === 'date') {
      return [{ ...gridColumn, valueFormatter: formatDateCell } as ColDef];
    }
    if (valueFormat === 'decimal' || valueFormat === 'percent') {
      const precision =
        typeof valueFormatPrecision === 'number' &&
        Number.isInteger(valueFormatPrecision) &&
        valueFormatPrecision >= 0 &&
        valueFormatPrecision <= 10
          ? valueFormatPrecision
          : 0;
      const formatter = new Intl.NumberFormat(locale, {
        style: valueFormat,
        minimumFractionDigits: precision,
        maximumFractionDigits: precision,
      });
      const valueFormatter = ({ value }: { value?: unknown }): string => {
        const number =
          typeof value === 'number' ||
          (typeof value === 'string' && value.trim())
            ? Number(value)
            : NaN;
        return Number.isFinite(number) ? formatter.format(number) : '';
      };
      return [{ ...gridColumn, valueFormatter } as ColDef];
    }
    return [gridColumn as ColDef];
  });
}

/** Show the visible grid columns and its filtered, sorted display values. */
function NativeDataTable({
  api,
  title,
  rowHeaderField,
}: {
  api: GridApi;
  title: string;
  rowHeaderField?: string;
}) {
  const captionId = useId();
  const scrollRef = useRef<HTMLElement>(null);
  const [page, setPage] = useState(0);
  const columns = api.getAllDisplayedColumns();
  const rowCount = api.getDisplayedRowCount();
  const lastPage = Math.max(0, Math.ceil(rowCount / ROWS_PER_PAGE) - 1);
  const currentPage = Math.min(page, lastPage);
  const start = currentPage * ROWS_PER_PAGE;
  const end = Math.min(start + ROWS_PER_PAGE, rowCount);

  const changePage = (newPage: number) => {
    if (newPage === currentPage) return;
    setPage(newPage);
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  };

  if (columns.length === 0)
    return <Typography.Text>{t('No data')}</Typography.Text>;

  return (
    <>
      {lastPage > 0 && (
        <Flex align="center" wrap gap={4}>
          <Button
            size="small"
            aria-disabled={currentPage === 0}
            onClick={() => changePage(Math.max(0, currentPage - 1))}
          >
            {t('Previous')}
          </Button>
          <output>
            {t('Rows %s–%s of %s', start + 1, end, rowCount)}
          </output>
          <Button
            size="small"
            aria-disabled={currentPage === lastPage}
            onClick={() => changePage(Math.min(lastPage, currentPage + 1))}
          >
            {t('Next')}
          </Button>
        </Flex>
      )}
      <TableScroll
        ref={scrollRef}
        aria-labelledby={captionId}
        tabIndex={rowCount > 0 ? 0 : undefined}
      >
        <table>
          <caption
            id={captionId}
            style={{
              position: 'absolute',
              width: 1,
              height: 1,
              overflow: 'hidden',
              clipPath: 'inset(50%)',
              whiteSpace: 'nowrap',
            }}
          >
            {title}
          </caption>
          <thead>
            <tr>
              {columns.map(column => (
                <th key={column.getColId()} scope="col">
                  {api.getDisplayNameForColumn(column, 'header')}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: end - start }, (_, offset) => {
              const rowNode = api.getDisplayedRowAtIndex(start + offset);
              if (!rowNode) return null;
              return (
                <tr key={rowNode.id ?? start + offset}>
                  {columns.map((column, columnIndex) => {
                    const value: unknown = api.getCellValue({
                      rowNode,
                      colKey: column,
                      useFormatter: true,
                    });
                    const Cell =
                      columnIndex === 0 &&
                      rowHeaderField !== undefined &&
                      column.getColDef().field === rowHeaderField
                        ? 'th'
                        : 'td';
                    return (
                      <Cell
                        key={column.getColId()}
                        scope={Cell === 'th' ? 'row' : undefined}
                      >
                        <bdi>{value == null ? '' : String(value)}</bdi>
                      </Cell>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
        {rowCount === 0 && <Typography.Text>{t('No data')}</Typography.Text>}
      </TableScroll>
    </>
  );
}

/** Keep the interactive grid mounted so switching views preserves its state. */
function TableViews({
  result,
  columnDefs,
  title,
  rowHeaderField,
  showNative,
  onToggleView,
}: {
  result: QueryDataResult;
  columnDefs: ColDef[];
  title: string;
  rowHeaderField?: string;
  showNative: boolean;
  onToggleView: () => void;
}) {
  const [gridModel, setGridModel] = useState<{ api: GridApi }>();
  const viewId = useId();

  return (
    <Flex vertical style={{ height: '100%', minHeight: 0 }}>
      <Button
        type="link"
        size="small"
        onClick={onToggleView}
        aria-controls={viewId}
        style={{ alignSelf: 'flex-end' }}
      >
        {showNative ? t('Interactive grid') : t('View as table')}
      </Button>
      <Flex id={viewId} vertical style={{ flex: 1, minHeight: 0 }}>
        <div hidden={showNative} style={{ height: '100%' }}>
          <ThemedAgGridReact
            rowData={result.rows}
            columnDefs={columnDefs}
            onModelUpdated={({ api }) => setGridModel({ api })}
          />
        </div>
        {showNative &&
          (gridModel ? (
            <NativeDataTable
              api={gridModel.api}
              title={title}
              rowHeaderField={rowHeaderField}
            />
          ) : (
            <Loading position="inline-centered" size="s" />
          ))}
      </Flex>
    </Flex>
  );
}
/**
 * The built-in `ag-grid-table` widget — registered like any other
 * widget (see `registry.ts`). Fetches its `dataBinding` the same way
 * `ChartWidget` does (see `useWidgetData`), then hands the rows to AG Grid
 * through the themed `ThemedAgGridReact` wrapper, which also mirrors the grid
 * in a right-to-left page. `columnDefs` can optionally be authored (custom
 * headers, widths, pinning); when omitted, columns are derived one-to-one
 * from the query's own result columns.
 * In the published dashboard viewer, inline widgets can also show AG Grid's
 * displayed data in a native table for structural navigation.
 */
export default function AgGridTableWidget(widgetProps: AgGridTableWidgetProps) {
  const { accessibleTitle, preferNativeTable, props, savedId } = widgetProps;
  const [showInteractive, setShowInteractive] = useState(false);
  const dataBinding = props.dataBinding as WidgetDataBindingSpec | undefined;
  const useTableViews = preferNativeTable && !savedId && dataBinding;
  const title =
    accessibleTitle?.trim() ||
    (typeof props.label === 'string' && props.label.trim()) ||
    t('Table');
  const { result, error, loading } = useWidgetData(
    TYPE,
    widgetProps,
    'This table widget has no dataBinding.',
  );

  const authoredKey = JSON.stringify(props.columnDefs ?? null);
  const locale =
    globalThis.document?.documentElement.lang.replaceAll('_', '-') || undefined;
  const columnDefs = useMemo(() => {
    const authored = sanitizeColumnDefs(props.columnDefs, locale);
    if (authored.length > 0) return authored;
    return result ? deriveColumnDefs(result.columns) : undefined;
    // `authoredKey` is the value of `props.columnDefs`, which is a new array
    // on every render of an inline widget.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authoredKey, result, locale]);

  return (
    <div
      style={{
        // Fills the box its container gives this
        // widget — always a definite pixel box, same as `ChartWidget`.
        width: '100%',
        height: '100%',
        // Surface, border and corners belong to the card a host
        // draws around this widget and the name above it, so that the name is
        // inside the frame rather than over it.
        overflow: 'hidden',
      }}
    >
      {error && (
        <Flex
          align="center"
          justify="center"
          style={{ width: '100%', height: '100%' }}
        >
          <Typography.Text type="danger">{error}</Typography.Text>
        </Flex>
      )}
      {!error && loading && (
        <Flex
          align="center"
          justify="center"
          style={{ width: '100%', height: '100%' }}
        >
          <Loading position="inline-centered" size="s" />
        </Flex>
      )}
      {!error &&
        result &&
        columnDefs &&
        (useTableViews ? (
          <TableViews
            result={result}
            columnDefs={columnDefs}
            title={title}
            rowHeaderField={dataBinding.dimensions?.[0]}
            showNative={!showInteractive}
            onToggleView={() => setShowInteractive(show => !show)}
          />
        ) : (
          <ThemedAgGridReact rowData={result.rows} columnDefs={columnDefs} />
        ))}
    </div>
  );
}
