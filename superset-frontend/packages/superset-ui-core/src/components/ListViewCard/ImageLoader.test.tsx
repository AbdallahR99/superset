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
import fetchMock from 'fetch-mock';

import { act, render, screen } from '@superset-ui/core/spec';
import { ImageLoader, type BackgroundPosition } from './ImageLoader';

global.URL.createObjectURL = jest.fn(() => '/local_url');
global.URL.revokeObjectURL = jest.fn();
const blob = new Blob([], { type: 'image/png' });

beforeAll(() => {
  fetchMock.mockGlobal();
});

afterAll(() => {
  fetchMock.hardReset();
});

fetchMock.get(
  'glob:*/thumbnail',
  { body: blob, headers: { 'Content-Type': 'image/png' } },
  { name: 'thumbnail' },
);

describe('ImageLoader', () => {
  const defaultProps = {
    src: '/thumbnail',
    fallback: '/fallback',
    position: 'top' as BackgroundPosition,
  };

  const setup = (extraProps = {}) => {
    const props = { ...defaultProps, ...extraProps };
    return render(<ImageLoader {...props} />);
  };

  afterEach(() => fetchMock.clearHistory());

  test('is a valid element', async () => {
    setup();
    expect(await screen.findByTestId('image-loader')).toBeVisible();
  });

  test('fetches loads the image in the background', async () => {
    setup();
    expect(screen.getByTestId('image-loader')).toHaveAttribute(
      'src',
      '/fallback',
    );
    expect(fetchMock.callHistory.calls(/thumbnail/)).toHaveLength(1);
    expect(global.URL.createObjectURL).toHaveBeenCalled();
    expect(await screen.findByTestId('image-loader')).toHaveAttribute(
      'src',
      '/local_url',
    );
  });

  test('displays fallback image when response is not an image', async () => {
    fetchMock.once('glob:*/thumbnail2', {}, { name: 'thumbnail2' });

    setup({ src: 'glob:*/thumbnail2' });
    expect(screen.getByTestId('image-loader')).toHaveAttribute(
      'src',
      '/fallback',
    );
    expect(fetchMock.callHistory.calls(/thumbnail2/)).toHaveLength(1);
    expect(await screen.findByTestId('image-loader')).toHaveAttribute(
      'src',
      '/fallback',
    );
  });
});

test('retries a queued thumbnail and releases its image when removed', async () => {
  jest.useFakeTimers();
  const fetch = jest
    .spyOn(global, 'fetch')
    .mockResolvedValueOnce(new Response(null, { status: 202 }))
    .mockResolvedValueOnce(new Response(null, { status: 404 }))
    .mockResolvedValueOnce({
      ok: true,
      status: 200,
      blob: async () => blob,
    } as Response);
  try {
    const { unmount } = render(
      <ImageLoader src="/queued" fallback="/layout" position="top" />,
    );
    await act(async () => {});
    expect(screen.getByTestId('image-loader')).toHaveAttribute(
      'src',
      '/layout',
    );
    await act(async () => {
      jest.advanceTimersByTime(3000);
    });
    await act(async () => {
      jest.advanceTimersByTime(6000);
    });
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(screen.getByTestId('image-loader')).toHaveAttribute(
      'src',
      '/local_url',
    );
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('/local_url');
  } finally {
    fetch.mockRestore();
    jest.useRealTimers();
  }
});
