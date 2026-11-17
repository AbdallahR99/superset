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
import type { ReactElement } from 'react';
import { t } from '@apache-superset/core/translation';
import { Button, Flex, Modal, Typography } from '@superset-ui/core/components';
import {
  dashboardSession,
  useDashboardSession,
} from 'src/core/dashboard/session';
import { useSaveOutcome } from './useSaveDashboard';

/**
 * The server holds a copy of this dashboard that the one on screen was not
 * based on, and only the author can say which of the two should survive.
 *
 * Drawn from the session's own record of the conflict rather than opened by
 * whichever control ran into it, so it appears the same whether the save
 * came from the header or from the prompt that interrupts leaving.
 *
 * Three ways out and no default among them that loses work without saying
 * so. Closing the dialog is the third: it keeps the edits on screen and
 * resolves nothing, so the next save is refused the same way and asks
 * again.
 */
export default function ConflictDialog(): ReactElement {
  const { conflict, saving } = useDashboardSession();
  // Reported from here, so this stays mounted while it is closed: choosing
  // to overwrite clears the conflict at once, and the answer to that save
  // still has to be told to the author when it arrives.
  const report = useSaveOutcome();

  const keepEditing = () => dashboardSession.dismissConflict();

  return (
    <Modal
      show={conflict !== undefined}
      // Nothing of a resolved conflict is left in the page once it closes.
      destroyOnHidden
      onHide={keepEditing}
      title={t('This dashboard was changed elsewhere')}
      name={t('This dashboard was changed elsewhere')}
      footer={
        <Flex justify="flex-end" gap="small" wrap>
          <Button
            buttonStyle="secondary"
            data-test="conflict-keep-editing"
            disabled={saving}
            onClick={keepEditing}
          >
            {t('Keep editing')}
          </Button>
          <Button
            buttonStyle="secondary"
            data-test="conflict-reload"
            disabled={saving}
            onClick={() => dashboardSession.reloadTheirs()}
          >
            {t('Discard my changes and reload')}
          </Button>
          <Button
            buttonStyle="danger"
            data-test="conflict-overwrite"
            loading={saving}
            onClick={async () => report(await dashboardSession.overwrite())}
          >
            {t('Overwrite with my version')}
          </Button>
        </Flex>
      }
    >
      <Flex vertical gap="middle" data-test="conflict-dialog">
        <Typography.Text>
          {conflict?.source === 'load'
            ? t(
                'Changes were made here before this dashboard had finished loading, so the saved version was not loaded over them.',
              )
            : t(
                'Someone saved this dashboard after you opened it. Your changes have not been saved.',
              )}
        </Typography.Text>
        <Typography.Text type="secondary">
          {t(
            'Reloading replaces what is on screen with the saved version. Overwriting replaces the saved version with what is on screen. Keep editing to decide later; saving will ask again.',
          )}
        </Typography.Text>
      </Flex>
    </Modal>
  );
}
