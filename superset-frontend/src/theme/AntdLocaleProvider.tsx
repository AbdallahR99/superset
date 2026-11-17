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
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { AntdThemeProvider } from '@superset-ui/core/components/AntdThemeProvider';
import getBootstrapData from 'src/utils/getBootstrapData';
import { getLoadedAntdLocale, loadAntdLocale } from 'src/hooks/useLocale';

/**
 * Gives Ant Design its own translations (pagination, pickers, empty states)
 * for the active locale. Text direction is handled by the theme provider;
 * this only concerns the strings Ant Design ships itself.
 */
export function AntdLocaleProvider({ children }: { children: ReactNode }) {
  const localeCode = getBootstrapData().common?.locale;
  const [locale, setLocale] = useState(() => getLoadedAntdLocale(localeCode));

  useEffect(() => {
    let active = true;
    if (!locale) {
      loadAntdLocale(localeCode)
        .then(loaded => {
          if (active && loaded) {
            setLocale(loaded);
          }
        })
        .catch(() => undefined);
    }
    return () => {
      active = false;
    };
  }, [locale, localeCode]);

  return <AntdThemeProvider locale={locale}>{children}</AntdThemeProvider>;
}
