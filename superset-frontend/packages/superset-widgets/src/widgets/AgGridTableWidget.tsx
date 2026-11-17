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
import { useMemo } from 'react';
import {
  Flex,
  Loading,
  ThemedAgGridReact,
  Typography,
} from '@superset-ui/core/components';
import type { ColDef } from '@superset-ui/core/components/ThemedAgGridReact';
import type { WidgetProps } from '../types';
import { useWidgetData } from '../useWidgetData';

const TYPE = 'ag-grid-table';

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
 * runs them. Only declarative settings are let through, so a definition
 * written by one user can never run script in the page of another.
 */
const COLUMN_SETTINGS: Readonly<
  Record<string, 'string' | 'number' | 'boolean'>
> = {
  field: 'string',
  colId: 'string',
  headerName: 'string',
  headerTooltip: 'string',
  type: 'string',
  cellDataType: 'string',
  sort: 'string',
  pinned: 'string',
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

/** The declarative part of authored column definitions; see {@link COLUMN_SETTINGS}. */
export function sanitizeColumnDefs(columnDefs: unknown): ColDef[] {
  if (!Array.isArray(columnDefs)) return [];
  return columnDefs.slice(0, MAX_COLUMNS).flatMap(entry => {
    if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) {
      return [];
    }
    const authored = entry as Record<string, unknown>;
    const column: Record<string, string | number | boolean> = {};
    Object.keys(COLUMN_SETTINGS).forEach(key => {
      const value = authored[key];
      if (typeof value === COLUMN_SETTINGS[key]) {
        column[key] = value as string | number | boolean;
      }
    });
    // A column that names no field shows nothing; schema-driven forms seed
    // such empty entries.
    return typeof column.field === 'string' && column.field !== ''
      ? [column as ColDef]
      : [];
  });
}

/**
 * The built-in `ag-grid-table` widget — registered like any other
 * widget (see `registry.ts`). Fetches its `dataBinding` the same way
 * `ChartWidget` does (see `useWidgetData`), then hands the rows to AG Grid
 * through the themed `ThemedAgGridReact` wrapper, which also mirrors the grid
 * in a right-to-left page. `columnDefs` can optionally be authored (custom
 * headers, widths, pinning); when omitted, columns are derived one-to-one
 * from the query's own result columns.
 */
export default function AgGridTableWidget(widgetProps: WidgetProps) {
  const { props } = widgetProps;
  const { result, error, loading } = useWidgetData(
    TYPE,
    widgetProps,
    'This table widget has no dataBinding.',
  );

  const authoredKey = JSON.stringify(props.columnDefs ?? null);
  const columnDefs = useMemo(() => {
    const authored = sanitizeColumnDefs(props.columnDefs);
    if (authored.length > 0) return authored;
    return result ? deriveColumnDefs(result.columns) : undefined;
    // `authoredKey` is the value of `props.columnDefs`, which is a new array
    // on every render of an inline widget.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authoredKey, result]);

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
      {!error && result && columnDefs && (
        <ThemedAgGridReact rowData={result.rows} columnDefs={columnDefs} />
      )}
    </div>
  );
}
