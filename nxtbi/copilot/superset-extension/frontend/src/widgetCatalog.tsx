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
import { lazy, Suspense } from 'react';
import type { A2uiReactCatalog } from '@nxtbi/copilot';
import { savedWidgetRef } from './savedWidgetRef';

const SavedWidgetPreview = lazy(() => import('./SavedWidgetPreview'));

export function createWidgetCatalog(
  base: string,
  locale: string,
  direction: 'ltr' | 'rtl',
): A2uiReactCatalog {
  return {
    id: 'urn:nxtbi:superset-widgets:1.0',
    components: {
      SupersetWidgetPreview: {
        validate(props) {
          if (!savedWidgetRef(props)) {
            throw new Error(
              'A Superset widget preview requires a saved widget UUID.',
            );
          }
        },
      },
    },
    renderers: {
      SupersetWidgetPreview({ props }) {
        const id = savedWidgetRef(props);
        const loading = locale.startsWith('ar')
          ? 'جارٍ تحميل المعاينة…'
          : 'Loading preview…';
        return id ? (
          <Suspense fallback={<p role="status">{loading}</p>}>
            <SavedWidgetPreview
              id={id}
              base={base}
              locale={locale}
              direction={direction}
            />
          </Suspense>
        ) : null;
      },
    },
  };
}
