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
import { styled } from '@apache-superset/core/theme';

/**
 * Width a popover gains while its resize grip is dragged from `startX` to
 * `clientX`. The grip sits on the bottom inline-end corner, which is the left
 * one in right-to-left layouts, so there the pointer travels left to widen it.
 */
export const getResizeDeltaX = (
  startX: number,
  clientX: number,
  isRtl: boolean,
): number => (isRtl ? startX - clientX : clientX - startX);

export const ExplorePopoverContent = styled.div`
  .edit-popover-resize {
    /* The grip floats to the inline-end corner (mirrored automatically); the
       arrows and the cursor must follow the diagonal of that corner. */
    transform: ${({ theme }) =>
      theme.direction === 'rtl' ? 'none' : 'scaleX(-1)'};
    float: right;
    margin-top: ${({ theme }) => theme.margin}px;
    margin-right: ${({ theme }) => theme.marginXXS * -1}px;
    color: ${({ theme }) => theme.colorIcon};
    cursor: ${({ theme }) =>
      theme.direction === 'rtl' ? 'nesw-resize' : 'nwse-resize'};
  }
  .filter-sql-editor {
    border: ${({ theme }) => theme.colorBorder} solid thin;
  }
  && .ant-tabs-nav {
    margin-bottom: ${({ theme }) => theme.marginSM}px;
  }
  && .ant-form-item {
    margin-bottom: ${({ theme }) => theme.marginXS}px;
  }
`;
