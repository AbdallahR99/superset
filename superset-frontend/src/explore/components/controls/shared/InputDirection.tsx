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
import { cloneElement, type ReactElement } from 'react';
import { DirectionProvider, useIsRtl } from '@apache-superset/core/theme';

export interface InputDirectionProps {
  /**
   * `ltr` for values that read left-to-right whatever the language of the
   * interface: formats, expressions, markup, URLs. `auto` for free text, which
   * then follows the script of what was typed.
   */
  mode: 'ltr' | 'auto';
  /**
   * Current value of the field, for `auto`: an empty field keeps the direction
   * of the interface, so that its placeholder and caret stay on the usual side.
   */
  value?: unknown;
  /** A single text field (`Input`, `Input.TextArea`, ...). */
  children: ReactElement<{ dir?: string }>;
}

/**
 * Gives a text field the direction of its content in right-to-left layouts,
 * where a format such as `%Y-%m-%d`, a URL or a negative number would
 * otherwise be reordered by the bidirectional algorithm.
 *
 * The field gets a `dir` attribute. Ant Design pins `direction: rtl` on its
 * inputs with a class, which would win over the attribute, so the field is
 * rendered in a left-to-right Ant Design context. In left-to-right layouts the
 * field is returned untouched.
 */
export default function InputDirection({
  mode,
  value,
  children,
}: InputDirectionProps) {
  const isRtl = useIsRtl();
  if (!isRtl) {
    return children;
  }
  const isEmpty = value === undefined || value === null || value === '';
  const dir = mode === 'auto' && isEmpty ? undefined : mode;
  return (
    <DirectionProvider direction="ltr">
      {dir ? cloneElement(children, { dir }) : children}
    </DirectionProvider>
  );
}
