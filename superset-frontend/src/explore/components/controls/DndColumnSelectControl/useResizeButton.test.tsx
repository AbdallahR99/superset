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
  fireEvent,
  render,
  screen,
  waitFor,
} from 'spec/helpers/testing-library';
import {
  POPOVER_INITIAL_HEIGHT,
  POPOVER_INITIAL_WIDTH,
} from 'src/explore/constants';
import useResizeButton from './useResizeButton';

const Harness = () => {
  const [resizeButton, width, height] = useResizeButton(100, 100);
  return (
    <div data-test="popover" data-width={width} data-height={height}>
      {resizeButton}
    </div>
  );
};

const size = () => {
  const popover = screen.getByTestId('popover');
  return {
    width: Number(popover.getAttribute('data-width')),
    height: Number(popover.getAttribute('data-height')),
  };
};

const drag = (
  from: { clientX: number; clientY: number },
  to: { clientX: number; clientY: number },
) => {
  fireEvent.mouseDown(screen.getByRole('button', { name: 'Resize' }), from);
  fireEvent.mouseMove(document, to);
};

test('widens the popover when the grip is dragged right', async () => {
  render(<Harness />);

  drag({ clientX: 500, clientY: 300 }, { clientX: 560, clientY: 330 });

  await waitFor(() =>
    expect(size()).toEqual({
      width: POPOVER_INITIAL_WIDTH + 60,
      height: POPOVER_INITIAL_HEIGHT + 30,
    }),
  );
  fireEvent.mouseUp(document);
});

test('widens the popover when the grip is dragged left in right-to-left layouts', async () => {
  // The grip sits on the bottom-left corner there, and the popover grows
  // away from its trigger towards the left.
  render(<Harness />, { direction: 'rtl' });

  drag({ clientX: 500, clientY: 300 }, { clientX: 440, clientY: 330 });

  await waitFor(() =>
    expect(size()).toEqual({
      width: POPOVER_INITIAL_WIDTH + 60,
      height: POPOVER_INITIAL_HEIGHT + 30,
    }),
  );
  fireEvent.mouseUp(document);
});

test('narrows the popover, down to its minimum, when dragged right in right-to-left layouts', async () => {
  render(<Harness />, { direction: 'rtl' });

  drag({ clientX: 500, clientY: 300 }, { clientX: 900, clientY: 300 });

  await waitFor(() => expect(size().width).toBe(100));
  fireEvent.mouseUp(document);
});

test('keeps its size when the grip is pressed without moving', () => {
  render(<Harness />, { direction: 'rtl' });

  fireEvent.mouseDown(screen.getByRole('button', { name: 'Resize' }), {
    clientX: 500,
    clientY: 300,
  });

  expect(size()).toEqual({
    width: POPOVER_INITIAL_WIDTH,
    height: POPOVER_INITIAL_HEIGHT,
  });
  fireEvent.mouseUp(document);
});
