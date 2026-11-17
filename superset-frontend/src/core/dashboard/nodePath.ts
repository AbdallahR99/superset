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
import { createContext } from 'react';
import { getDocumentLimits } from './documentTree';

/**
 * The ids of the nodes a render has already passed through on its way down
 * to here, outermost first.
 *
 * Rendering a node renders its children, through whichever container widget
 * arranges them, so a tree that names one of its own ancestors as a child
 * would render without end. The store repairs a document into a strict tree
 * when it loads one, but a renderer is also handed stores it did not load
 * (`DashboardStoreContext`), and a frozen tab is too high a price for
 * trusting every one of them. `WidgetView` provides this as it descends and
 * refuses a node already on the path.
 */
export const NodePathContext = createContext<readonly string[]>([]);

/** Whether rendering `nodeId` beneath `path` would repeat a node or go too deep. */
export const isUnrenderable = (
  path: readonly string[],
  nodeId: string,
): boolean =>
  path.length > getDocumentLimits().maxDepth || path.includes(nodeId);
