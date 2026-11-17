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
import { FeatureFlag, isFeatureEnabled } from '@superset-ui/core';
import { useTheme } from '@apache-superset/core/theme';

// Matches antd's screenSMMax token; used only when no theme is in scope.
const FALLBACK_MOBILE_MAX_WIDTH = 767;

/**
 * Whether the mobile consumption-only experience is enabled for this
 * deployment. Non-hook variant for use inside styled-component
 * interpolations; prefer `useIsMobile` in components.
 */
export function isMobileConsumptionEnabled(): boolean {
  return isFeatureEnabled(FeatureFlag.MobileConsumptionMode);
}

/**
 * Reads the current match synchronously so the hook's initial render
 * already reflects the real viewport instead of defaulting to desktop.
 * Guarded for environments without `window`/`matchMedia` (SSR, older
 * browsers), where it falls back to the desktop (non-mobile) value.
 */
function getInitialIsSmallScreen(enabled: boolean, maxWidth: number): boolean {
  if (!enabled || typeof window === 'undefined' || !window.matchMedia) {
    return false;
  }
  return window.matchMedia(`(max-width: ${maxWidth}px)`).matches;
}

/** Tracks the theme's small-screen breakpoint for responsive layout. */
export function useIsSmallScreen(enabled = true): boolean {
  const theme = useTheme();
  const maxWidth = theme?.screenSMMax ?? FALLBACK_MOBILE_MAX_WIDTH;
  const [isSmallScreen, setIsSmallScreen] = useState(() =>
    getInitialIsSmallScreen(enabled, maxWidth),
  );

  useEffect(() => {
    if (!enabled || typeof window === 'undefined' || !window.matchMedia) {
      return undefined;
    }
    const mediaQuery = window.matchMedia(`(max-width: ${maxWidth}px)`);
    const update = () => setIsSmallScreen(mediaQuery.matches);
    update();
    // Safari < 14 lacks addEventListener on MediaQueryList
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', update);
      return () => mediaQuery.removeEventListener('change', update);
    }
    mediaQuery.addListener(update);
    return () => mediaQuery.removeListener(update);
  }, [enabled, maxWidth]);

  return enabled && isSmallScreen;
}

/** Gates consumption-only navigation and controls by feature flag and viewport. */
export function useIsMobile(): boolean {
  return useIsSmallScreen(isMobileConsumptionEnabled());
}
