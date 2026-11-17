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
import { render, screen } from 'spec/helpers/testing-library';
import { Input } from '@superset-ui/core/components';
import InputDirection from './InputDirection';

test('leaves the field untouched in left-to-right layouts', () => {
  render(
    <InputDirection mode="ltr">
      <Input aria-label="format" defaultValue="%Y-%m-%d" />
    </InputDirection>,
  );

  expect(screen.getByLabelText('format')).not.toHaveAttribute('dir');
});

test('keeps a left-to-right value left-to-right in right-to-left layouts', () => {
  render(
    <InputDirection mode="ltr">
      <Input aria-label="format" defaultValue="%Y-%m-%d" />
    </InputDirection>,
    { direction: 'rtl' },
  );

  const input = screen.getByLabelText('format');
  expect(input).toHaveAttribute('dir', 'ltr');
  // Ant Design pins `direction: rtl` through this class, which would win
  // over the attribute.
  expect(input).not.toHaveClass('ant-input-rtl');
});

test('lets free text follow its own script in right-to-left layouts', () => {
  render(
    <InputDirection mode="auto" value="https://example.com/">
      <Input aria-label="url" value="https://example.com/" readOnly />
    </InputDirection>,
    { direction: 'rtl' },
  );

  const input = screen.getByLabelText('url');
  expect(input).toHaveAttribute('dir', 'auto');
  expect(input).not.toHaveClass('ant-input-rtl');
});

test('keeps an empty field in the direction of the interface', () => {
  render(
    <InputDirection mode="auto" value="">
      <Input aria-label="title" value="" readOnly />
    </InputDirection>,
    { direction: 'rtl' },
  );

  // `dir="auto"` resolves to left-to-right for an empty field, which would
  // move the placeholder and the caret to the left.
  expect(screen.getByLabelText('title')).not.toHaveAttribute('dir');
});

test('the Ant Design class that pins the direction is present without the wrapper', () => {
  // Guards the reason for the wrapper: if Ant Design stops adding this class,
  // the left-to-right context can go.
  render(<Input aria-label="plain" />, { direction: 'rtl' });

  expect(screen.getByLabelText('plain')).toHaveClass('ant-input-rtl');
});
