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
import { render, screen, userEvent } from '@superset-ui/core/spec';
import { Collapse } from '.';
import type { CollapseProps } from './types';

function renderCollapse(props?: CollapseProps) {
  return render(
    <Collapse
      {...props}
      items={[
        {
          key: '1',
          label: 'Header 1',
          children: 'Content 1',
        },
        {
          key: '2',
          label: 'Header 2',
          children: 'Content 2',
        },
      ]}
    />,
  );
}

test('renders collapsed with default props', () => {
  renderCollapse();

  const headers = screen.getAllByRole('button');

  expect(headers[0]).toHaveTextContent('Header 1');
  expect(headers[1]).toHaveTextContent('Header 2');
  expect(screen.queryByText('Content 1')).not.toBeInTheDocument();
  expect(screen.queryByText('Content 2')).not.toBeInTheDocument();
});

test('renders with one item expanded by default', () => {
  renderCollapse({ defaultActiveKey: ['1'] });

  const headers = screen.getAllByRole('button');

  expect(headers[0]).toHaveTextContent('Header 1');
  expect(headers[1]).toHaveTextContent('Header 2');
  expect(screen.getByText('Content 1')).toBeInTheDocument();
  expect(screen.queryByText('Content 2')).not.toBeInTheDocument();
});

test('expands on click', async () => {
  renderCollapse();

  expect(screen.queryByText('Content 1')).not.toBeInTheDocument();
  expect(screen.queryByText('Content 2')).not.toBeInTheDocument();

  await userEvent.click(screen.getAllByRole('button')[0]);

  expect(screen.getByText('Content 1')).toBeInTheDocument();
  expect(screen.queryByText('Content 2')).not.toBeInTheDocument();
});

test('collapses on click', async () => {
  renderCollapse({ defaultActiveKey: ['1'] });

  expect(screen.getByText('Content 1')).toBeInTheDocument();
  expect(screen.queryByText('Content 2')).not.toBeInTheDocument();

  await userEvent.click(screen.getAllByRole('button')[0]);

  // antd v6 moved the hidden state to the panel wrapper element
  // (ant-collapse-panel-hidden) instead of the content wrapper.
  expect(screen.getByText('Content 1').parentElement).toHaveClass(
    'ant-collapse-panel-hidden',
  );
  expect(screen.queryByText('Content 2')).not.toBeInTheDocument();
});

// Rotation the stylesheet gives the chevron's svg for a selector, or
// `undefined` when no rule targets it.
function arrowRotation(match: (selector: string) => boolean) {
  const rotations: string[] = [];
  for (const sheet of Array.from(document.styleSheets)) {
    for (const rule of Array.from(sheet.cssRules)) {
      const { selectorText, style } = rule as CSSStyleRule;
      if (selectorText && match(selectorText) && style.transform) {
        rotations.push(style.transform);
      }
    }
  }
  return rotations[rotations.length - 1];
}

const isRtlRule = (selector: string) => selector.includes('.ant-collapse-rtl');
const isActiveRule = (selector: string) =>
  selector.includes('.ant-collapse-item-active');

test('an end-positioned chevron points down when collapsed and up when expanded', () => {
  renderCollapse({ expandIconPosition: 'end' });

  expect(arrowRotation(s => !isRtlRule(s) && !isActiveRule(s))).toBe(
    'rotate(90deg)',
  );
  expect(arrowRotation(s => !isRtlRule(s) && isActiveRule(s))).toBe(
    'rotate(-90deg)',
  );
});

test('right-to-left reverses the chevron rotation that Ant Design turns by 180 degrees', () => {
  const { container } = render(
    <Collapse
      expandIconPosition="end"
      items={[{ key: '1', label: 'Header 1', children: 'Content 1' }]}
    />,
    { direction: 'rtl' },
  );

  expect(container.querySelector('.ant-collapse')).toHaveClass(
    'ant-collapse-rtl',
  );
  expect(arrowRotation(s => isRtlRule(s) && !isActiveRule(s))).toBe(
    'rotate(-90deg)',
  );
  expect(arrowRotation(s => isRtlRule(s) && isActiveRule(s))).toBe(
    'rotate(90deg)',
  );
});
