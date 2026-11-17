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
import getDropPositionOriginal, {
  DROP_TOP,
  DROP_RIGHT,
  DROP_BOTTOM,
  DROP_LEFT,
  DROP_FORBIDDEN,
} from 'src/dashboard/util/getDropPosition';

import {
  CHART_TYPE,
  COLUMN_TYPE,
  DASHBOARD_GRID_TYPE,
  DASHBOARD_ROOT_TYPE,
  HEADER_TYPE,
  ROW_TYPE,
  TAB_TYPE,
  TABS_TYPE,
} from 'src/dashboard/util/componentTypes';
import reorderItem from 'src/dashboard/util/dnd-reorder';

// Cast to accept partial mock data in tests
const getDropPosition = getDropPositionOriginal as (
  ...args: any[]
) => string | null;

// eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks
describe('getDropPosition', () => {
  // helper to easily configure test
  function getMocks({
    parentType,
    componentType,
    draggingType,
    depth = 1,
    hasChildren = false,
    orientation = 'row',
    clientOffset = { x: 0, y: 0 },
    boundingClientRect = {
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
    },
    isDraggingOverShallow = true,
  }: {
    parentType: string;
    componentType: string;
    draggingType: string;
    depth?: number;
    hasChildren?: boolean;
    orientation?: string;
    clientOffset?: { x?: number; y?: number };
    boundingClientRect?: Partial<DOMRect>;
    isDraggingOverShallow?: boolean;
  }) {
    const monitorMock = {
      getItem: () => ({
        id: 'id',
        type: draggingType,
      }),
      getClientOffset: () => clientOffset,
    };

    const ComponentMock = {
      props: {
        depth,
        parentComponent: {
          type: parentType,
        },
        component: {
          type: componentType,
          children: hasChildren ? [''] : [],
        },
        orientation,
        isDraggingOverShallow,
      },
      ref: {
        getBoundingClientRect: () => boundingClientRect,
      },
    };

    return [monitorMock, ComponentMock];
  }

  // eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks
  describe('invalid child + invalid sibling', () => {
    test('should return DROP_FORBIDDEN', () => {
      const result = getDropPosition(
        // TAB is an invalid child + sibling of GRID > ROW
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: TAB_TYPE,
        }),
      );
      expect(result).toBe(DROP_FORBIDDEN);
    });
  });

  // eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks
  describe('valid child + invalid sibling', () => {
    test('should return DROP_LEFT if component has NO children, and orientation is "row"', () => {
      // HEADER is a valid child + invalid sibling of ROOT > GRID
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_ROOT_TYPE,
          componentType: DASHBOARD_GRID_TYPE,
          draggingType: HEADER_TYPE,
        }),
      );
      expect(result).toBe(DROP_LEFT);
    });

    test('should return DROP_RIGHT if component HAS children, and orientation is "row"', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_ROOT_TYPE,
          componentType: DASHBOARD_GRID_TYPE,
          draggingType: HEADER_TYPE,
          hasChildren: true,
        }),
      );
      expect(result).toBe(DROP_RIGHT);
    });

    test('should return DROP_TOP if component has NO children, and orientation is "column"', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_ROOT_TYPE,
          componentType: DASHBOARD_GRID_TYPE,
          draggingType: HEADER_TYPE,
          orientation: 'column',
        }),
      );
      expect(result).toBe(DROP_TOP);
    });

    test('should return DROP_BOTTOM if component HAS children, and orientation is "column"', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_ROOT_TYPE,
          componentType: DASHBOARD_GRID_TYPE,
          draggingType: HEADER_TYPE,
          orientation: 'column',
          hasChildren: true,
        }),
      );
      expect(result).toBe(DROP_BOTTOM);
    });
  });

  // eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks
  describe('invalid child + valid sibling', () => {
    test('should return DROP_TOP if orientation="row" and clientOffset is closer to component top than bottom', () => {
      const result = getDropPosition(
        // HEADER is an invalid child but valid sibling of GRID > ROW
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: HEADER_TYPE,
          clientOffset: { y: 10 },
          boundingClientRect: {
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(result).toBe(DROP_TOP);
    });

    test('should return DROP_BOTTOM if orientation="row" and clientOffset is closer to component bottom than top', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: HEADER_TYPE,
          clientOffset: { y: 55 },
          boundingClientRect: {
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(result).toBe(DROP_BOTTOM);
    });

    test('should return DROP_LEFT if orientation="column" and clientOffset is closer to component left than right', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: HEADER_TYPE,
          orientation: 'column',
          clientOffset: { x: 45 },
          boundingClientRect: {
            left: 0,
            right: 100,
          },
        }),
      );
      expect(result).toBe(DROP_LEFT);
    });

    test('should return DROP_RIGHT if orientation="column" and clientOffset is closer to component right than left', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: HEADER_TYPE,
          orientation: 'column',
          clientOffset: { x: 55 },
          boundingClientRect: {
            left: 0,
            right: 100,
          },
        }),
      );
      expect(result).toBe(DROP_RIGHT);
    });
  });

  // eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks
  describe('child + valid sibling (row orientation)', () => {
    test('should return DROP_LEFT if component has NO children, and clientOffset is NOT near top/bottom sibling boundary', () => {
      const result = getDropPosition(
        // CHART is a valid child + sibling of GRID > ROW
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          clientOffset: { x: 10, y: 50 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(result).toBe(DROP_LEFT);
    });

    test('should return DROP_RIGHT if component HAS children, and clientOffset is NOT near top/bottom sibling boundary', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          hasChildren: true,
          clientOffset: { x: 10, y: 50 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(result).toBe(DROP_RIGHT);
    });

    test('should return DROP_TOP regardless of component children if clientOffset IS near top sibling boundary', () => {
      const noChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          clientOffset: { x: 10, y: 2 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      const withChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          hasChildren: true,
          clientOffset: { x: 10, y: 2 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(noChildren).toBe(DROP_TOP);
      expect(withChildren).toBe(DROP_TOP);
    });

    test('should return DROP_BOTTOM regardless of component children if clientOffset IS near bottom sibling boundary', () => {
      const noChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          clientOffset: { x: 10, y: 95 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      const withChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          hasChildren: true,
          clientOffset: { x: 10, y: 95 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(noChildren).toBe(DROP_BOTTOM);
      expect(withChildren).toBe(DROP_BOTTOM);
    });
  });

  // eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks
  describe('child + valid sibling (column orientation)', () => {
    test('should return DROP_TOP if component has NO children, and clientOffset is NOT near left/right sibling boundary', () => {
      const result = getDropPosition(
        // CHART is a valid child + sibling of GRID > ROW
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          orientation: 'column',
          clientOffset: { x: 50, y: 0 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(result).toBe(DROP_TOP);
    });

    test('should return DROP_BOTTOM if component HAS children, and clientOffset is NOT near left/right sibling boundary', () => {
      const result = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          orientation: 'column',
          hasChildren: true,
          clientOffset: { x: 50, y: 0 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(result).toBe(DROP_BOTTOM);
    });

    test('should return DROP_LEFT regardless of component children if clientOffset IS near left sibling boundary', () => {
      const noChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          orientation: 'column',
          clientOffset: { x: 10, y: 2 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      const withChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          orientation: 'column',
          hasChildren: true,
          clientOffset: { x: 10, y: 2 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(noChildren).toBe(DROP_LEFT);
      expect(withChildren).toBe(DROP_LEFT);
    });

    test('should return DROP_RIGHT regardless of component children if clientOffset IS near right sibling boundary', () => {
      const noChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          orientation: 'column',
          clientOffset: { x: 90, y: 95 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      const withChildren = getDropPosition(
        ...getMocks({
          parentType: DASHBOARD_GRID_TYPE,
          componentType: ROW_TYPE,
          draggingType: CHART_TYPE,
          orientation: 'column',
          hasChildren: true,
          clientOffset: { x: 90, y: 95 },
          boundingClientRect: {
            left: 0,
            right: 100,
            top: 0,
            bottom: 100,
          },
        }),
      );
      expect(noChildren).toBe(DROP_RIGHT);
      expect(withChildren).toBe(DROP_RIGHT);
    });
  });
});

// The self-nesting guard needs ids and a parents chain, which getMocks above
// intentionally omits, so these build their own minimal mocks.
const selfNestingMocks = ({
  componentId,
  componentParents = [],
  parentComponentId,
  parentComponentParents = [],
}: {
  componentId: string;
  componentParents?: string[];
  parentComponentId?: string;
  parentComponentParents?: string[];
}) => [
  {
    getItem: () => ({ id: 'COLUMN-dragged', type: COLUMN_TYPE }),
    getClientOffset: () => ({ x: 0, y: 0 }),
  },
  {
    props: {
      depth: 2,
      component: {
        id: componentId,
        type: ROW_TYPE,
        children: [],
        parents: componentParents,
      },
      parentComponent: parentComponentId
        ? {
            id: parentComponentId,
            type: TAB_TYPE,
            children: [],
            parents: parentComponentParents,
          }
        : undefined,
      orientation: 'column',
      isDraggingOverShallow: true,
    },
    ref: {
      getBoundingClientRect: () => ({
        top: 0,
        right: 100,
        bottom: 100,
        left: 0,
      }),
    },
  },
];

test('returns DROP_FORBIDDEN when dropping a component into its own descendant', () => {
  expect(
    getDropPosition(
      ...selfNestingMocks({
        componentId: 'ROW-nested-in-dragged',
        componentParents: ['ROOT_ID', 'GRID_ID', 'COLUMN-dragged'],
      }),
    ),
  ).toBe(DROP_FORBIDDEN);
});

test('returns DROP_FORBIDDEN when dropping a component as a sibling inside itself', () => {
  expect(
    getDropPosition(
      ...selfNestingMocks({
        componentId: 'ROW-nested-in-dragged-sibling',
        componentParents: ['ROOT_ID', 'GRID_ID', 'COLUMN-dragged'],
        parentComponentId: 'COLUMN-dragged',
      }),
    ),
  ).toBe(DROP_FORBIDDEN);
});

test('allows a drop on an unrelated component', () => {
  expect(
    getDropPosition(
      ...selfNestingMocks({
        componentId: 'ROW-unrelated',
        componentParents: ['ROOT_ID', 'GRID_ID'],
      }),
    ),
  ).not.toBe(DROP_FORBIDDEN);
});

// A tab dragged over a sibling tab: the only drop whose left/right result is
// consumed (by reorderItem and by the tab drop indicators).
const tabOverTabMocks = (clientX: number) => [
  {
    getItem: () => ({ id: 'TAB-dragged', type: TAB_TYPE }),
    getClientOffset: () => ({ x: clientX, y: 10 }),
  },
  {
    props: {
      depth: 1,
      component: { id: 'TAB-target', type: TAB_TYPE, children: [] },
      parentComponent: { id: 'TABS-parent', type: TABS_TYPE, children: [] },
      orientation: 'column',
      isDraggingOverShallow: true,
    },
    ref: {
      getBoundingClientRect: () => ({
        top: 0,
        right: 200,
        bottom: 40,
        left: 100,
      }),
    },
  },
];

const tabsEntities = () => ({
  'TABS-parent': {
    id: 'TABS-parent',
    type: TABS_TYPE,
    children: ['TAB-a', 'TAB-target', 'TAB-dragged'],
  },
});

afterEach(() => {
  document.documentElement.removeAttribute('dir');
});

test('left-to-right: the physical left half of a tab is the "before" side', () => {
  expect(getDropPosition(...tabOverTabMocks(110))).toBe(DROP_LEFT);
  expect(getDropPosition(...tabOverTabMocks(190))).toBe(DROP_RIGHT);
});

test('right-to-left: the physical left half of a tab is the "after" side', () => {
  document.documentElement.setAttribute('dir', 'rtl');
  expect(getDropPosition(...tabOverTabMocks(110))).toBe(DROP_RIGHT);
  expect(getDropPosition(...tabOverTabMocks(190))).toBe(DROP_LEFT);
});

test('right-to-left: dropping on the visual left of a tab inserts after it', () => {
  // Tabs render right-to-left, so the visual left neighbour of a tab is the
  // next child in the persisted (reading-order) list.
  document.documentElement.setAttribute('dir', 'rtl');
  const result = reorderItem({
    entitiesMap: tabsEntities(),
    source: { id: 'TABS-parent', type: TABS_TYPE, index: 2 },
    destination: { id: 'TABS-parent', type: TABS_TYPE, index: 1 },
    position: getDropPosition(...tabOverTabMocks(110)),
  });
  // already the next child of the target: nothing moves
  expect(result['TABS-parent'].children).toEqual([
    'TAB-a',
    'TAB-target',
    'TAB-dragged',
  ]);
});

test('right-to-left: dropping on the visual right of a tab inserts before it', () => {
  document.documentElement.setAttribute('dir', 'rtl');
  const result = reorderItem({
    entitiesMap: tabsEntities(),
    source: { id: 'TABS-parent', type: TABS_TYPE, index: 2 },
    destination: { id: 'TABS-parent', type: TABS_TYPE, index: 1 },
    position: getDropPosition(...tabOverTabMocks(190)),
  });
  expect(result['TABS-parent'].children).toEqual([
    'TAB-a',
    'TAB-dragged',
    'TAB-target',
  ]);
});

test('right-to-left leaves the append/prepend and top/bottom results alone', () => {
  document.documentElement.setAttribute('dir', 'rtl');
  // valid child + invalid sibling: logical prepend/append, no pointer involved
  const dropOnGrid = (hasChildren: boolean) =>
    getDropPosition(
      {
        getItem: () => ({ id: 'id', type: HEADER_TYPE }),
        getClientOffset: () => ({ x: 0, y: 0 }),
      },
      {
        props: {
          depth: 1,
          parentComponent: { type: DASHBOARD_ROOT_TYPE },
          component: {
            type: DASHBOARD_GRID_TYPE,
            children: hasChildren ? [''] : [],
          },
          orientation: 'row',
          isDraggingOverShallow: true,
        },
        ref: { getBoundingClientRect: () => ({}) },
      },
    );
  expect(dropOnGrid(false)).toBe(DROP_LEFT);
  expect(dropOnGrid(true)).toBe(DROP_RIGHT);

  // vertical siblings do not depend on direction
  const dropOnRow = (clientY: number) =>
    getDropPosition(
      {
        getItem: () => ({ id: 'id', type: HEADER_TYPE }),
        getClientOffset: () => ({ x: 0, y: clientY }),
      },
      {
        props: {
          depth: 1,
          parentComponent: { type: DASHBOARD_GRID_TYPE },
          component: { type: ROW_TYPE, children: [] },
          orientation: 'row',
          isDraggingOverShallow: true,
        },
        ref: { getBoundingClientRect: () => ({ top: 0, bottom: 100 }) },
      },
    );
  expect(dropOnRow(10)).toBe(DROP_TOP);
  expect(dropOnRow(60)).toBe(DROP_BOTTOM);
});
