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
import { render } from 'spec/helpers/testing-library';

import ResizableContainer, {
  ResizableContainerProps,
} from 'src/dashboard/components/resizable/ResizableContainer';

// eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks
describe('ResizableContainer', () => {
  const props = {
    editMode: false,
    id: 'id',
    heightMultiple: 0,
    widthMultiple: 0,
  };

  const setup = (overrides?: ResizableContainerProps) => (
    <ResizableContainer {...props} {...overrides} />
  );

  test('should render a Resizable container', () => {
    const rendered = render(setup());
    const resizableContainer = rendered.container.querySelector(
      '.resizable-container',
    );
    expect(resizableContainer).toBeVisible();
  });
});

const editableProps: ResizableContainerProps = {
  editMode: true,
  id: 'id',
  heightMultiple: 10,
  widthMultiple: 4,
};

const widthHandle = (container: HTMLElement) =>
  container.querySelector<HTMLElement>('.resizable-container-handle--right');

test('left-to-right puts the width handles on the right edge', () => {
  const { container } = render(<ResizableContainer {...editableProps} />);
  expect(widthHandle(container)?.style.right).toBe('-5px');
  expect(widthHandle(container)?.style.left).toBe('');
  const corner = container.querySelector('.resize-handle--bottom-right')
    ?.parentElement as HTMLElement;
  expect(corner.style.right).toBe('-10px');
  expect(corner.style.cursor).toBe('se-resize');
});

test('right-to-left puts the width handles on the left edge', () => {
  const { container } = render(<ResizableContainer {...editableProps} />, {
    direction: 'rtl',
  });
  // same class and handle components (their styles are mirrored), but
  // re-resizable anchors them to the physical left edge
  expect(widthHandle(container)?.style.left).toBe('-5px');
  expect(widthHandle(container)?.style.right).toBe('');
  expect(
    widthHandle(container)?.querySelector('.resize-handle--right'),
  ).toBeInTheDocument();
  const corner = container.querySelector('.resize-handle--bottom-right')
    ?.parentElement as HTMLElement;
  expect(corner.style.left).toBe('-10px');
  expect(corner.style.cursor).toBe('sw-resize');
  expect(
    container.querySelector('.resizable-container-handle--bottom'),
  ).toBeInTheDocument();
});

test('the height label keeps its physical offset from the pointer in right-to-left', () => {
  render(<ResizableContainer {...editableProps} />, { direction: 'rtl' });
  // rendered in a portal on document.body, positioned with physical pixels
  const label = Array.from(document.body.children).find(
    node => (node as HTMLElement).style.display === 'none',
  );
  expect(label).toHaveStyleRule('transform', 'translate(12px, 12px)');
});
