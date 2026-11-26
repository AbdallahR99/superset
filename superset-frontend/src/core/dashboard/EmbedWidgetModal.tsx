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
import { useEffect, useRef, useState, type ReactElement } from 'react';
import { SupersetClient } from '@superset-ui/core';
import { t } from '@apache-superset/core/translation';
import { Alert } from '@apache-superset/core/components';
import { Button, Flex, Modal, Typography } from '@superset-ui/core/components';
import { describeFetchError } from '@apache-superset/widgets/chartData';
import { isExtensionWidgetType } from '@apache-superset/widgets/embed/extensionLoader';
import type { SavedWidget } from '@apache-superset/core/widgets';
import { useToasts } from 'src/components/MessageToasts/withToasts';
import { useDashboardStore } from './store';
import { widgetLabel } from './widgetLabel';

/** Where the saved widget's uuid is kept on the node, so re-embedding updates it. */
export const EMBED_WIDGET_ID_PROP = 'embedWidgetId';

function datasetIdOf(props: Record<string, unknown>): number | undefined {
  const binding = props.dataBinding as { datasetId?: unknown } | undefined;
  const id = binding?.datasetId ?? props.datasetId;
  return typeof id === 'number' && Number.isSafeInteger(id) && id > 0
    ? id
    : undefined;
}

export default function EmbedWidgetModal({
  nodeId,
  show,
  onHide,
}: {
  nodeId: string;
  show: boolean;
  onHide: () => void;
}): ReactElement | null {
  const store = useDashboardStore();
  const { addDangerToast, addSuccessToast } = useToasts();
  const node = store.getNode(nodeId);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();
  const savingRef = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  if (!node) return null;

  const { [EMBED_WIDGET_ID_PROP]: storedId, ...props } = node.props ?? {};
  const widgetId = typeof storedId === 'string' ? storedId : undefined;
  const binding = props.dataBinding as { semanticViewId?: unknown } | undefined;
  const usesSemanticView = typeof binding?.semanticViewId === 'string';
  const datasetId = usesSemanticView ? undefined : datasetIdOf(props);

  const save = async () => {
    // A ref rather than the `saving` state: two clicks in one tick both see
    // the state as it was rendered, and the second would create a second
    // saved widget for the same node.
    if (savingRef.current) return;
    savingRef.current = true;
    // The tree the widget was saved from. Its id is written back after the
    // request, and by then the tree may be another dashboard's, or a
    // reloaded copy of this one, in which a node of the same id is not the
    // widget that was saved.
    const generation = store.getDocumentGeneration();
    setSaving(true);
    setSaveError(undefined);
    try {
      const title = widgetLabel(node.type, props) || undefined;
      const { json } = widgetId
        ? await SupersetClient.put({
            endpoint: `/api/v1/widget/${widgetId}`,
            jsonPayload: { props, title },
          })
        : await SupersetClient.post({
            endpoint: '/api/v1/widget/',
            jsonPayload: { widget_type: node.type, props, title },
          });
      const saved = json.result as SavedWidget;
      if (
        store.getDocumentGeneration() === generation &&
        store.getNode(nodeId) !== undefined
      ) {
        store.updateProps(nodeId, { [EMBED_WIDGET_ID_PROP]: saved.uuid });
      }
      addSuccessToast(t('Widget saved for embedding'));
    } catch (error) {
      const message = await describeFetchError(error);
      // A refusal (403: not allowed to author this query; 422: the widget's
      // properties are invalid) is about this widget, so it is said here,
      // beside it, and stays until the next attempt.
      if (mountedRef.current) setSaveError(message);
      addDangerToast(message);
    } finally {
      savingRef.current = false;
      if (mountedRef.current) setSaving(false);
    }
  };

  const savedGuestSnippet = usesSemanticView
    ? ''
    : `\n\n// guest token\n{ resources: [{ type: "widget", id: "${widgetId}" }], rls: [] }`;
  const savedSnippet = widgetId
    ? `<Widget id="${widgetId}" />${savedGuestSnippet}`
    : '';
  const guestTokenRequest =
    datasetId === undefined
      ? undefined
      : JSON.stringify(
          {
            resources: [{ type: 'dataset', id: String(datasetId) }],
            datasets: [datasetId],
            rls: [{ dataset: datasetId, clause: '1 = 0' }],
          },
          null,
          2,
        );
  const guestTokenSnippet = guestTokenRequest
    ? `\n\n// ${t('Guest token request (server-side)')}\n// ${t('Replace 1 = 0 with the row filter for the authenticated viewer.')}\n${guestTokenRequest}`
    : '';
  const inlineSnippet = `<Widget\n  type="${node.type}"\n  props={${JSON.stringify(props, null, 2)}}\n/>${guestTokenSnippet}`;

  return (
    <Modal
      show={show}
      onHide={onHide}
      title={t('Embed widget')}
      name={t('Embed widget')}
      footer={
        <Flex justify="flex-end" gap="small">
          <Button buttonStyle="secondary" onClick={onHide}>
            {t('Close')}
          </Button>
          <Button buttonStyle="primary" loading={saving} onClick={save}>
            {widgetId ? t('Update saved widget') : t('Save widget')}
          </Button>
        </Flex>
      }
    >
      <Flex vertical gap="middle">
        {saveError !== undefined && (
          <Alert
            type="error"
            showIcon
            closable={false}
            data-test="embed-widget-save-error"
            description={saveError}
          >
            {t('This widget could not be saved for embedding')}
          </Alert>
        )}
        <Typography.Text>
          {t(
            'Render this widget in any React app with @apache-superset/widgets, inside a SupersetProvider.',
          )}
        </Typography.Text>
        {usesSemanticView && (
          <Typography.Text type="secondary">
            {t('Viewers sign in to Superset to see this semantic widget.')}
          </Typography.Text>
        )}
        {isExtensionWidgetType(node.type) && (
          <Typography.Text type="secondary">
            {t(
              'This widget comes from an extension. The host page loads that extension from Superset as it renders; with guest tokens the deployment also needs EMBEDDED_EXTENSION_ASSETS_PUBLIC.',
            )}
          </Typography.Text>
        )}
        <Typography.Text strong>{t('By saved id')}</Typography.Text>
        {widgetId ? (
          <Typography.Paragraph copyable={{ text: savedSnippet }}>
            <pre data-test="embed-widget-saved-snippet">{savedSnippet}</pre>
          </Typography.Paragraph>
        ) : (
          <Typography.Text type="secondary">
            {t(
              'Save the widget to get an id. The server then runs the saved definition and the host cannot change it.',
            )}
          </Typography.Text>
        )}
        <Typography.Text strong>{t('Inline')}</Typography.Text>
        <Typography.Paragraph copyable={{ text: inlineSnippet }}>
          <pre data-test="embed-widget-inline-snippet">{inlineSnippet}</pre>
        </Typography.Paragraph>
      </Flex>
    </Modal>
  );
}
