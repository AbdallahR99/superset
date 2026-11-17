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

// Embedding
export { SupersetProvider } from './embed/SupersetProvider';
export type {
  SupersetProviderProps,
  ThemeModeName,
} from './embed/SupersetProvider';
export {
  Chart,
  FilterSelect,
  Markdown,
  MetricTile,
  Table,
  Widget,
} from './embed/Widget';
export type {
  ChartProps,
  CommonWidgetProps,
  FilterSelectProps,
  MarkdownProps,
  MetricTileProps,
  TableProps,
  WidgetElementProps,
} from './embed/Widget';
export {
  hostFilterPayload,
  useSupersetFilter,
  useWidgetEvent,
  useWidgetValue,
} from './embed/hooks';
export { createGuestTokenSource, guestTokenExpiry } from './embed/guestToken';
export type { GuestTokenSource } from './embed/guestToken';
export { createApiFetch, createHttpWidgetClient } from './embed/httpClient';
export {
  ExtensionWidgetLoaderContext,
  createExtensionWidgetLoader,
  isExtensionWidgetType,
  parseExtensionWidgetType,
  useExtensionWidget,
} from './embed/extensionLoader';
export type {
  ExtensionWidgetLoader,
  ExtensionWidgetLoaderOptions,
  ExtensionWidgetState,
} from './embed/extensionLoader';
export { createExtensionHost } from './embed/extensionHost';
export type { ExtensionHost, ExtensionInfo } from './embed/extensionHost';
export type {
  ApiFetch,
  ApiFetchOptions,
  HttpWidgetClientOptions,
} from './embed/httpClient';

// Errors a host can classify and act on
export {
  WidgetApiError,
  WidgetErrorContext,
  isAbortError,
  useWidgetErrorReporter,
} from './errors';
export type {
  WidgetErrorInfo,
  WidgetErrorKind,
  WidgetErrorPhase,
  WidgetErrorReporter,
} from './errors';

// Host contracts (the dashboard builder implements these too)
export {
  WidgetBusContext,
  createWidgetBus,
  useWidgetBus,
  useWidgetBusRevision,
} from './bus';
export {
  WidgetDataClientContext,
  sessionDataClient,
  useWidgetDataClient,
  widgetRef,
} from './dataClient';
export {
  WidgetApplySourceContext,
  useWidgetApplySource,
} from './deferredApply';
export {
  WidgetComponentsContext,
  builtInWidgetComponents,
  getWidgetComponent,
  registerWidgetComponent,
  unregisterWidgetComponent,
} from './registry';
export { useWidgetData } from './useWidgetData';
export type { WidgetDataState } from './useWidgetData';
export {
  DEFAULT_MAX_TREE_DEPTH,
  DEFAULT_MAX_TREE_NODES,
  collectSubtreeIds,
  findParentId,
  getAncestorIds,
  isNodeOrDescendant,
  sanitizeTree,
  subtreeDepth,
  validateTree,
  walkTree,
} from './tree';
export type {
  NodeLookup,
  NodeSource,
  TreeIssue,
  TreeIssueKind,
  TreeLimits,
  TreeNodeLike,
  TreeVisit,
} from './tree';
export {
  getActiveAdhocFilters,
  getActiveResolvedFilters,
  toAdhocFilters,
} from './activeFilters';
export { FILTER_BAR_APPLY_EVENT } from './filterVocabulary';
export type {
  FilterOperator,
  FilterValueChangedPayload,
  ResolvedFilter,
} from './filterVocabulary';
export { describeFetchError, fetchQueryData } from './chartData';
export { resolveBindings } from './resolveBindings';
export { sanitizeColumnDefs } from './widgets/AgGridTableWidget';
export { sanitizeEchartsOption } from './widgets/echartsSafety';
export type {
  DataBindingSpec,
  DataRow,
  HostFilter,
  InlineWidgetRef,
  QueryDataResult,
  SavedWidget,
  SavedWidgetRef,
  WidgetBus,
  WidgetComponent,
  WidgetDataClient,
  WidgetDataRequest,
  WidgetEvent,
  WidgetProps,
  WidgetRef,
  WidgetRequestOptions,
  WidgetValuesRequest,
} from './types';
