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

/** What the server refused about particular nodes, one line per problem. */
export type NodeErrors = Readonly<Record<string, readonly string[]>>;

const NONE: NodeErrors = Object.freeze({});

/**
 * The problems a refused save named, by node id.
 *
 * A save is refused as a whole, but the reason is often one widget's
 * properties, and a toast that names a node id is no help in finding it.
 * Whoever owns the save (the builder page, from its session) provides the
 * record here, and `WidgetView` draws each node's lines on that node. A tree
 * rendered without a provider has nothing to show and shows nothing.
 */
export const NodeErrorsContext = createContext<NodeErrors>(NONE);
