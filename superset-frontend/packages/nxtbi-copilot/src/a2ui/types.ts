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
export const A2UI_VERSION = '1.0';
export const BASIC_A2UI_CATALOG_ID =
  'https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json';
export const NXTBI_A2UI_CATALOG_ID = 'urn:nxtbi:a2ui:1.0';

export type A2uiJson =
  | null
  | string
  | number
  | boolean
  | A2uiJsonObject
  | A2uiJson[];

export interface A2uiJsonObject {
  [key: string]: A2uiJson;
}

export type A2uiComponent = A2uiJsonObject & { id: string; component: string };

interface SurfaceReference {
  surfaceId: string;
}

type Envelope<Key extends string, Payload> = {
  version: typeof A2UI_VERSION;
} & {
  [Name in Key]: Payload;
};

/** The A2UI 1.0 surface messages supported by the Copilot. */
export type A2uiMessage =
  | Envelope<
      'createSurface',
      SurfaceReference & {
        catalogId?: string;
        components?: readonly A2uiComponent[];
        dataModel?: A2uiJsonObject;
        sendDataModel?: false;
        metadata?: A2uiJsonObject;
      }
    >
  | Envelope<
      'updateComponents',
      SurfaceReference & {
        components: readonly A2uiComponent[];
      }
    >
  | Envelope<
      'updateDataModel',
      SurfaceReference & {
        path?: string;
        value: A2uiJson;
      }
    >
  | Envelope<'deleteSurface', SurfaceReference>;

export type A2uiAction = Envelope<
  'action',
  SurfaceReference & {
    name: string;
    sourceComponentId: string;
    timestamp: string;
    context: A2uiJsonObject;
    userMessage?: string;
  }
>;

export interface A2uiSurface {
  readonly surfaceId: string;
  readonly catalogId?: string;
  readonly components: Readonly<Record<string, A2uiComponent>>;
  readonly dataModel: A2uiJsonObject;
}

export interface A2uiState {
  readonly surfaces: Readonly<Record<string, A2uiSurface>>;
}

/** Trusted host code can register declarative properties and structural child references. */
export interface A2uiCatalogComponent {
  validate(props: A2uiJsonObject): void;
  children?(props: A2uiJsonObject): readonly string[];
}

export interface A2uiCatalog {
  readonly id: string;
  readonly components: Readonly<Record<string, A2uiCatalogComponent>>;
}
