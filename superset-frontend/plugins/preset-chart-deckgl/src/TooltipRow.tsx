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
import { useIsRtl } from '@apache-superset/core/theme';

type TooltipRowProps = {
  label: string;
  value: string;
};

const TooltipRow = ({ label, value }: TooltipRowProps) => {
  // In a right-to-left tooltip the value keeps its own reading order, so that
  // a coordinate such as `-122.41` or a left-to-right name is not reordered.
  const isRtl = useIsRtl();
  return (
    <div>
      {label}
      <strong dir={isRtl ? 'auto' : undefined}>{value}</strong>
    </div>
  );
};

export default TooltipRow;
