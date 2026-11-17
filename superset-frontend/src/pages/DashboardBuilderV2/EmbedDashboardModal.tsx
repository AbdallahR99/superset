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
import { useState } from 'react';
import type { ReactElement } from 'react';
import { t } from '@apache-superset/core/translation';
import { Button, Flex, Modal, Typography } from '@superset-ui/core/components';
import { isContainerType } from 'src/core/dashboard/DashboardProvider';
import EmbedWidgetModal, {
  EMBED_WIDGET_ID_PROP,
} from 'src/core/dashboard/EmbedWidgetModal';
import { isWidgetViewRegistered } from 'src/core/dashboard/resolveWidgetView';
import { provider, useDashboardRevision } from 'src/core/dashboard/store';
import { widgetLabel } from 'src/core/dashboard/widgetLabel';

/** One widget on the dashboard that a host page could render. */
export interface EmbeddableWidget {
  nodeId: string;
  label: string;
  /** The saved widget's uuid, once the widget has been saved for embedding. */
  savedId: string | undefined;
}

/**
 * The widgets on the dashboard a host page can render, in reading order.
 *
 * Containers are left out: they arrange the nodes inside them and have
 * nothing of their own for the server to run. So is anything no renderer is
 * registered for, which the server could not run either.
 */
export function listEmbeddableWidgets(): EmbeddableWidget[] {
  const rootId = provider.getRoot().id;
  return provider
    .getSubtreeIds(rootId)
    .filter(id => id !== rootId)
    .flatMap(nodeId => {
      const node = provider.getNode(nodeId);
      if (
        !node ||
        isContainerType(node.type) ||
        !isWidgetViewRegistered(node.type)
      ) {
        return [];
      }
      const savedId = node.props?.[EMBED_WIDGET_ID_PROP];
      return [
        {
          nodeId,
          label: widgetLabel(node.type, node.props) || node.type,
          savedId:
            typeof savedId === 'string' && savedId !== '' ? savedId : undefined,
        },
      ];
    });
}

/**
 * What a host application pastes to render the saved widgets, and the guest
 * token payload that lets it: each widget is named as a `widget` resource,
 * and a token that does not name a widget cannot read it.
 */
export function buildEmbedSnippet(
  supersetDomain: string,
  widgetIds: readonly string[],
): string {
  const widgets = widgetIds.map(id => `  <Widget id="${id}" />`).join('\n');
  const resources = widgetIds
    .map(id => `    { type: "widget", id: "${id}" },`)
    .join('\n');
  return [
    `import { SupersetProvider, Widget } from '@apache-superset/widgets';`,
    '',
    '<SupersetProvider',
    `  supersetDomain="${supersetDomain}"`,
    '  fetchGuestToken={fetchGuestToken}',
    '>',
    widgets,
    '</SupersetProvider>',
    '',
    '// guest token payload, requested by your backend',
    '{',
    '  resources: [',
    resources,
    '  ],',
    '  rls: [],',
    '}',
  ].join('\n');
}

/**
 * How a Dashboard v2 is embedded: widget by widget.
 *
 * There is no embedded page for a v2 dashboard to be framed from. What a
 * host application embeds is the dashboard's widgets, rendered in its own
 * React tree by `@apache-superset/widgets` inside a `SupersetProvider`, each
 * one saved in Superset and named by id. So this lists the widgets, says
 * which already have an id, offers to save the ones that do not, and gives
 * the snippet for those that do.
 *
 * It replaces the classic dashboard's embed dialog here, which configures
 * the framed page of a classic dashboard and has nothing to configure for
 * one of these.
 */
export default function EmbedDashboardModal({
  show,
  onHide,
}: {
  show: boolean;
  onHide: () => void;
}): ReactElement {
  useDashboardRevision();
  const [savingNodeId, setSavingNodeId] = useState<string | undefined>();
  const widgets = show ? listEmbeddableWidgets() : [];
  const savedIds = widgets.flatMap(widget =>
    widget.savedId === undefined ? [] : [widget.savedId],
  );
  const snippet =
    savedIds.length > 0
      ? buildEmbedSnippet(window.location.origin, savedIds)
      : '';

  return (
    <>
      <Modal
        show={show && savingNodeId === undefined}
        onHide={onHide}
        title={t('Embed this dashboard')}
        name={t('Embed this dashboard')}
        footer={
          <Flex justify="flex-end">
            <Button buttonStyle="secondary" onClick={onHide}>
              {t('Close')}
            </Button>
          </Flex>
        }
      >
        <Flex vertical gap="middle" data-test="embed-dashboard">
          <Typography.Text>
            {t(
              'A dashboard is embedded widget by widget: your application renders each saved widget with @apache-superset/widgets, inside a SupersetProvider.',
            )}
          </Typography.Text>
          {widgets.length === 0 ? (
            <Typography.Text type="secondary" data-test="embed-dashboard-empty">
              {t('There are no widgets on this dashboard to embed yet.')}
            </Typography.Text>
          ) : (
            <Flex vertical gap="small">
              {widgets.map(widget => (
                <Flex
                  key={widget.nodeId}
                  align="center"
                  justify="space-between"
                  gap="small"
                  data-test={`embed-dashboard-widget-${widget.nodeId}`}
                >
                  <Typography.Text ellipsis style={{ minWidth: 0 }}>
                    {widget.label}
                  </Typography.Text>
                  {widget.savedId === undefined ? (
                    <Button
                      buttonSize="small"
                      buttonStyle="secondary"
                      data-test={`embed-dashboard-save-${widget.nodeId}`}
                      onClick={() => setSavingNodeId(widget.nodeId)}
                    >
                      {t('Save for embedding')}
                    </Button>
                  ) : (
                    <Typography.Text code copyable>
                      {widget.savedId}
                    </Typography.Text>
                  )}
                </Flex>
              ))}
            </Flex>
          )}
          {snippet !== '' && (
            <>
              <Typography.Text type="secondary">
                {t(
                  'A saved widget is a copy taken when it was saved. After editing a widget here, update its saved copy from the widget menu, and save the dashboard so it remembers the ids.',
                )}
              </Typography.Text>
              <Typography.Paragraph copyable={{ text: snippet }}>
                <pre data-test="embed-dashboard-snippet">{snippet}</pre>
              </Typography.Paragraph>
            </>
          )}
        </Flex>
      </Modal>
      {savingNodeId !== undefined && (
        <EmbedWidgetModal
          nodeId={savingNodeId}
          show
          onHide={() => setSavingNodeId(undefined)}
        />
      )}
    </>
  );
}
