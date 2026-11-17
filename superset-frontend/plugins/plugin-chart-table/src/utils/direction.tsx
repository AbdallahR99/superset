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
import { ReactNode } from 'react';
import { GenericDataType } from '@apache-superset/core/common';
import { DataColumnMeta } from '../types';

type PhysicalTextAlign = 'left' | 'center' | 'right';
type LogicalTextAlign = 'start' | 'center' | 'end';

/**
 * Maps a physical horizontal alignment to its logical equivalent, so that a
 * "left" aligned column sits at the start of the row and a "right" aligned
 * one at its end in both left-to-right and right-to-left tables. `center` is
 * returned as it is.
 */
export function toLogicalTextAlign(align: PhysicalTextAlign): LogicalTextAlign {
  if (align === 'left') {
    return 'start';
  }
  if (align === 'right') {
    return 'end';
  }
  return align;
}

/**
 * Keeps the reading order of a formatted cell value in a right-to-left table.
 *
 * Numbers are left-to-right by nature: without isolation the bidirectional
 * algorithm moves a leading minus sign, a currency symbol or a trailing
 * percent sign to the other side of the digits (`-12.5%` renders as `12.5%-`).
 * Temporal values are isolated with an automatic direction, so that the date
 * and the time parts of `2024-01-31 10:00:00` are not swapped while a value
 * formatted with right-to-left month names still reads right-to-left.
 *
 * Left-to-right tables get the text back untouched.
 */
export function isolateCellText(
  text: string,
  column: Pick<
    DataColumnMeta,
    'dataType' | 'isNumeric' | 'isMetric' | 'isPercentMetric'
  >,
  isRtl: boolean,
): ReactNode {
  if (!isRtl || !text) {
    return text;
  }
  if (column.isNumeric || column.isMetric || column.isPercentMetric) {
    return <bdi dir="ltr">{text}</bdi>;
  }
  if (column.dataType === GenericDataType.Temporal) {
    return <bdi>{text}</bdi>;
  }
  return text;
}
