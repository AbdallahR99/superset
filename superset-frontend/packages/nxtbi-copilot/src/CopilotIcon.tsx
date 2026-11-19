/*
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

const paths = {
  history: 'M3 12a9 9 0 1 1 3 6.7M3 16v-4h4m5-5v5l3 2',
  dock: 'M3 5h18v14H3zM15 5v14m3-10v6',
  float: 'M9 5h12v10M9 15l10-8m-9 2H3v10h14v-4',
  data: 'M20 6c0 1.7-3.6 3-8 3S4 7.7 4 6s3.6-3 8-3 8 1.3 8 3ZM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3',
  dashboard: 'M3 5h18v14H3zM3 9h18m-9 0v10',
  search: 'M15.5 15.5 21 21m-10-4a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z',
  attach:
    'M20 11.5 11.5 20a4 4 0 0 1-5.7-5.7l9.2-9.2a2.75 2.75 0 0 1 3.9 3.9l-8.5 8.5a1.4 1.4 0 0 1-2-2l7.8-7.8',
} as const;

/** A decorative icon whose containing control supplies its accessible name. */
export function CopilotIcon({ name }: { name: keyof typeof paths }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={paths[name]} />
    </svg>
  );
}
