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
import {
  styled,
  useDirection,
  getDocumentDirection,
} from '@apache-superset/core/theme';
import { Button } from '@superset-ui/core/components';
import { render, screen } from './testing-library';

const Box = styled.div`
  margin-left: 4px;
`;

const Probe = () => <span data-test="direction">{useDirection()}</span>;

test('renders left-to-right by default', () => {
  render(
    <>
      <Box data-test="box" />
      <Probe />
    </>,
  );
  expect(document.documentElement).not.toHaveAttribute('dir');
  expect(screen.getByTestId('direction')).toHaveTextContent('ltr');
  expect(screen.getByTestId('box')).toHaveStyleRule('margin-left', '4px');
});

test('the direction option renders the tree right-to-left', () => {
  render(
    <>
      <Box data-test="box" />
      <Probe />
      <Button>Save</Button>
    </>,
    { direction: 'rtl' },
  );
  // The document, for code that reads it directly...
  expect(document.documentElement).toHaveAttribute('dir', 'rtl');
  expect(getDocumentDirection()).toBe('rtl');
  // ...the hooks, mirrored styled components and Ant Design.
  expect(screen.getByTestId('direction')).toHaveTextContent('rtl');
  expect(screen.getByTestId('box')).toHaveStyleRule('margin-right', '4px');
  expect(screen.getByTestId('box')).not.toHaveStyleRule('margin-left', '4px');
  expect(screen.getByRole('button', { name: 'Save' })).toHaveClass(
    'ant-btn-rtl',
  );
});

test('the direction of a previous test does not leak into the next one', () => {
  expect(document.documentElement).not.toHaveAttribute('dir');
  render(<Probe />);
  expect(screen.getByTestId('direction')).toHaveTextContent('ltr');
});

test('restores a direction that was set on the document before rendering', () => {
  document.documentElement.setAttribute('dir', 'rtl');
  render(<Probe />, { direction: 'ltr' });
  expect(document.documentElement).toHaveAttribute('dir', 'ltr');
  expect(screen.getByTestId('direction')).toHaveTextContent('ltr');
});

test('the document direction of the previous test was restored, then reset here', () => {
  // The helper put back what the previous test had set by hand.
  expect(document.documentElement).toHaveAttribute('dir', 'rtl');
  document.documentElement.removeAttribute('dir');
});

test('the direction option composes with the other providers', () => {
  render(<Probe />, {
    direction: 'rtl',
    useRedux: true,
    useRouter: true,
    useTheme: true,
  });
  expect(screen.getByTestId('direction')).toHaveTextContent('rtl');
});
