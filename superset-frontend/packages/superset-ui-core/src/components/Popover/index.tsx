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
import { forwardRef } from 'react';
import { Popover as AntdPopover } from 'antd';
import { PopoverProps as AntdPopoverProps } from 'antd/es/popover';
import type { TooltipRef } from 'antd/es/tooltip';
import { flipPlacement, useDirection } from '@apache-superset/core/theme';

export interface PopoverProps extends AntdPopoverProps {
  forceRender?: boolean;
  /**
   * Mirror an explicit `placement` in right-to-left layouts (`left` becomes
   * `right`, `bottomLeft` becomes `bottomRight`, ...). Set to `false` when the
   * placement is physical by nature, for example computed from the position
   * of the trigger in the viewport.
   * @default true
   */
  mirrorPlacement?: boolean;
}

export const Popover = forwardRef<TooltipRef, PopoverProps>(
  ({ mirrorPlacement = true, placement, ...props }, ref) => {
    const direction = useDirection();
    return (
      <AntdPopover
        ref={ref}
        // antd mirrors only its default placement in right-to-left layouts
        placement={
          mirrorPlacement ? flipPlacement(placement, direction) : placement
        }
        {...props}
      />
    );
  },
);
