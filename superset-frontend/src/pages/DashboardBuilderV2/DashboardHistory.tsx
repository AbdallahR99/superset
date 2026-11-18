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
import { t } from '@apache-superset/core/translation';
import { Button, Flex, Modal, Typography } from '@superset-ui/core/components';
import {
  describeRecord,
  formatAuthor,
  formatVersionDateTime,
  groupHeadline,
} from 'src/features/versionHistory/display';
import { useVersionActivity } from 'src/features/versionHistory/useVersionActivity';

/** Show committed changes for the saved dashboard without leaving the builder. */
function HistoryDialog({ uuid, onHide }: { uuid: string; onHide: () => void }) {
  const activity = useVersionActivity('dashboard', uuid, 'self');
  return (
    <Modal
      show
      title={t('Version history')}
      name={t('Version history')}
      onHide={onHide}
      footer={<Button onClick={onHide}>{t('Close')}</Button>}
    >
      <Flex vertical gap="small">
        {activity.timeline.map(entry =>
          entry.type === 'group' ? (
            <details key={entry.transactionId}>
              <summary>
                {groupHeadline(entry)} · {formatVersionDateTime(entry.issuedAt)}{' '}
                · {formatAuthor(entry.changedBy)}
              </summary>
              <ul>
                {entry.records.map(record => (
                  <li
                    key={JSON.stringify([
                      record.kind,
                      record.operation,
                      record.path,
                    ])}
                  >
                    {record.summary || describeRecord(record)}
                  </li>
                ))}
              </ul>
            </details>
          ) : null,
        )}
        {activity.error && (
          <div role="alert">
            {activity.error}{' '}
            <Button onClick={activity.refresh}>{t('Retry')}</Button>
          </div>
        )}
        {activity.isLoading && <span role="status">{t('Loading…')}</span>}
        {!activity.isLoading &&
          !activity.error &&
          !activity.timeline.length && (
            <Typography.Text>{t('No saved versions yet.')}</Typography.Text>
          )}
        {activity.hasMore && (
          <Button onClick={activity.loadMore} disabled={activity.isLoading}>
            {t('Load more')}
          </Button>
        )}
        {activity.truncated && (
          <Typography.Text>
            {t('Older changes may be unavailable.')}
          </Typography.Text>
        )}
      </Flex>
    </Modal>
  );
}

/** Fetch history only when the author opens the dialog. */
export default function DashboardHistory({ uuid }: { uuid?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        buttonStyle="secondary"
        buttonSize="small"
        data-test="header-history"
        disabled={!uuid}
        onClick={() => setOpen(true)}
      >
        {t('History')}
      </Button>
      {open && uuid && (
        <HistoryDialog uuid={uuid} onHide={() => setOpen(false)} />
      )}
    </>
  );
}
