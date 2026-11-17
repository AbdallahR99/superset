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
import type { HostFilter } from '@apache-superset/widgets';

/**
 * The filter a set of chips stands for, in the shape `SupersetProvider`'s
 * `filters` prop takes. `null` lifts it.
 */
export function hostFilter(
  datasetId: number,
  column: string,
  selected: string[],
): HostFilter | null {
  return selected.length
    ? { datasetId, column, operator: 'IN', value: selected }
    : null;
}

/**
 * A filter control that belongs to the host app. It knows nothing of
 * Superset: it shows the host's own state and reports changes. Whoever owns
 * that state hands it to `<SupersetProvider filters>`.
 */
export function HostFilterBar({
  label,
  values,
  selected,
  onChange,
}: {
  label: string;
  values: string[];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  return (
    <fieldset className="filter-bar">
      <legend className="filter-label">{label}</legend>
      {values.map(value => {
        const active = selected.includes(value);
        return (
          <button
            type="button"
            key={value}
            className={active ? 'chip chip-active' : 'chip'}
            aria-pressed={active}
            onClick={() =>
              onChange(
                active
                  ? selected.filter(item => item !== value)
                  : [...selected, value],
              )
            }
          >
            {value}
          </button>
        );
      })}
      <button
        type="button"
        className="chip"
        disabled={!selected.length}
        onClick={() => onChange([])}
      >
        Clear
      </button>
    </fieldset>
  );
}
