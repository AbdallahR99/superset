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
import userEvent from '@testing-library/user-event';
import { ReactElement } from 'react';
import { render, RenderOptions } from '@testing-library/react';
import '@testing-library/jest-dom';
import { themeObject, type Direction } from '@apache-superset/core/theme';

// Define the wrapper component outside
const AllTheProviders = ({ children }: { children: React.ReactNode }) => (
  <themeObject.SupersetThemeProvider>
    {children}
  </themeObject.SupersetThemeProvider>
);

const providersWithDirection =
  (direction: Direction) =>
  ({ children }: { children: React.ReactNode }) => (
    <themeObject.SupersetThemeProvider direction={direction}>
      {children}
    </themeObject.SupersetThemeProvider>
  );

type Options = Omit<RenderOptions, 'wrapper'> & {
  /**
   * Text direction of the rendered tree. `rtl` mirrors styled components and
   * hands the direction to Ant Design, as the application does for a
   * right-to-left locale. The document itself is left untouched, so code
   * that reads `<html dir>` directly is not affected.
   */
  direction?: Direction;
};

// Follow the exact pattern from RTL docs
const customRender = (ui: ReactElement, options?: Options) => {
  const { direction, ...renderOptions } = options ?? {};
  return render(ui, {
    wrapper: direction ? providersWithDirection(direction) : AllTheProviders,
    ...renderOptions,
  });
};

export {
  createEvent,
  fireEvent,
  screen,
  waitFor,
  cleanup,
  within,
  act,
} from '@testing-library/react';
export { customRender as render, userEvent };
