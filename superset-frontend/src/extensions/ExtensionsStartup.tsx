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
import { useEffect } from 'react';
import { FeatureFlag, isFeatureEnabled } from '@superset-ui/core';
// eslint-disable-next-line no-restricted-syntax
import * as supersetCore from '@apache-superset/core';
import {
  authentication,
  chat,
  core,
  commands,
  dashboard,
  editors,
  extensions,
  menus,
  navigation,
  useNavigationTracker,
  sqlLab,
  views,
} from 'src/core';
import { useSelector } from 'react-redux';
import { RootState } from 'src/views/store';
import ExtensionsLoader from './ExtensionsLoader';
import 'src/extensions/Namespaces';

const ExtensionsStartup: React.FC<{ children?: React.ReactNode }> = ({
  children,
}) => {
  useNavigationTracker();

  const userId = useSelector<RootState, number | undefined>(
    ({ user }) => user.userId,
  );

  useEffect(() => {
    if (userId == null) return;

    // Provide the implementations for @apache-superset/core.
    // Namespaces are listed explicitly — do not spread the core package here,
    // as that would leak un-contracted symbols onto window.superset.
    window.superset = {
      ...supersetCore,
      authentication,
      chat,
      core,
      commands,
      // The Dashboard v2 API is part of the contract only where Dashboard v2
      // is turned on. With the flag off extensions are given no handle on a
      // node tree no page renders, and the key is set rather than left out
      // because the core package spread above carries a declaration-only
      // `dashboard` of its own that would otherwise stand in for it.
      dashboard: isFeatureEnabled(FeatureFlag.DashboardV2)
        ? dashboard
        : undefined,
      editors,
      extensions,
      menus,
      navigation,
      sqlLab,
      views,
    };

    if (isFeatureEnabled(FeatureFlag.EnableExtensions)) {
      ExtensionsLoader.getInstance().initializeExtensions();
    }
  }, [userId]);

  return <>{children}</>;
};

export default ExtensionsStartup;
