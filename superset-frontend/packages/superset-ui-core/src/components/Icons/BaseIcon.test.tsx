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
import { render, screen } from '@superset-ui/core/spec';
import { Icons } from '.';

test('does not mirror a directional icon in a left-to-right layout', () => {
  render(<Icons.RightOutlined mirrorInRtl />);
  expect(screen.getByRole('img')).not.toHaveStyle({ transform: 'scaleX(-1)' });
});

test('mirrors an opted-in icon in a right-to-left layout', () => {
  render(<Icons.RightOutlined mirrorInRtl />, { direction: 'rtl' });
  expect(screen.getByRole('img')).toHaveStyle({ transform: 'scaleX(-1)' });
});

test('leaves icons that did not opt in untouched in a right-to-left layout', () => {
  render(<Icons.RightOutlined />, { direction: 'rtl' });
  expect(screen.getByRole('img')).not.toHaveStyle({ transform: 'scaleX(-1)' });
});

test('keeps the size and colour of a mirrored icon', () => {
  render(<Icons.RightOutlined mirrorInRtl iconColor="red" />, {
    direction: 'rtl',
  });
  expect(screen.getByRole('img')).toHaveStyle({
    color: 'rgb(255, 0, 0)',
    transform: 'scaleX(-1)',
  });
});

test('merges the mirror into a caller-provided style', () => {
  render(<Icons.RightOutlined mirrorInRtl style={{ opacity: 0.5 }} />, {
    direction: 'rtl',
  });
  expect(screen.getByRole('img')).toHaveStyle({
    opacity: '0.5',
    transform: 'scaleX(-1)',
  });
});

test('does not forward the mirrorInRtl prop to the DOM', () => {
  render(<Icons.RightOutlined mirrorInRtl />);
  expect(screen.getByRole('img')).not.toHaveAttribute('mirrorinrtl');
});
