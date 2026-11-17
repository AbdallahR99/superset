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

// The app is type-checked together with the Superset packages it consumes
// from source, whose own declarations already cover assets such as `*.svg`.
// So instead of referencing `vite/client` wholesale (which declares those
// differently), only what this app uses of Vite is declared here.
declare module '*?raw' {
  const source: string;
  export default source;
}

declare module '*.css';

// Only what `vite.config.ts` exposes to the browser (`envPrefix`). The
// broker's credentials are deliberately not among them.
interface ImportMetaEnv {
  readonly SUPERSET_URL?: string;
  readonly EMBED_AUTH?: string;
  readonly EMBED_WIDGET_IDS?: string;
  readonly EMBED_EXTENSION_WIDGET?: string;
  readonly EMBED_RTL_LOCALE?: string;
  readonly EMBED_METRIC?: string;
  readonly EMBED_SECOND_METRIC?: string;
  readonly EMBED_METRIC_COLUMN?: string;
  readonly EMBED_CATEGORY?: string;
  readonly EMBED_CATEGORY_VALUES?: string;
  readonly EMBED_LABEL?: string;
  readonly EMBED_B_DATASET_TABLE?: string;
  readonly EMBED_B_DATASET_ID?: string;
  readonly EMBED_B_METRIC?: string;
  readonly EMBED_B_DIMENSION?: string;
  readonly EMBED_B_VALUES?: string;
  readonly FILTER_DATASET_TABLE?: string;
  readonly FILTER_DATASET_ID?: string;
  readonly FILTER_COLUMN?: string;
  readonly FILTER_VALUES?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
