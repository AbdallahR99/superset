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
import { Drawer as AntdDrawer } from 'antd';
import { flipPlacement, useDirection } from '@apache-superset/core/theme';
import type { DrawerProps } from './types';

/**
 * Ant Design drawer whose side follows the text direction: `placement` names
 * the side in a left-to-right layout (`right` by default, as in Ant Design)
 * and is mirrored in a right-to-left one, so a navigation drawer opened from
 * the start edge stays on the start edge.
 */
export const Drawer = ({ placement = 'right', ...props }: DrawerProps) => {
  const direction = useDirection();
  return (
    <AntdDrawer placement={flipPlacement(placement, direction)} {...props} />
  );
};

export type { DrawerProps };
