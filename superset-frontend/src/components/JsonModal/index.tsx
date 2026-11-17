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

import { FC, useMemo } from 'react';
import { JSONTree } from 'react-json-tree';
import { LtrIsolate, styled } from '@apache-superset/core/theme';
import { useJsonTreeTheme } from 'src/hooks/useJsonTreeTheme';
import { Button, ModalTrigger } from '@superset-ui/core/components';
import { CopyToClipboard } from '../CopyToClipboard';
import { convertBigIntStrToNumber } from './utils';
import type { JsonModalProps } from './types';

/**
 * Preserve line breaks for multiline cell content (e.g. stack traces)
 * while keeping the change scoped to this component only.
 */
const PreWrap = styled.span`
  white-space: pre-wrap;
`;

function renderBigIntStrToNumber(value: string | number) {
  return <>{convertBigIntStrToNumber(value)}</>;
}

export const JsonModal: FC<JsonModalProps> = ({
  modalTitle,
  jsonObject,
  jsonValue,
  wrapContent = true,
}) => {
  const jsonTreeTheme = useJsonTreeTheme();

  const content = useMemo(
    () =>
      typeof jsonValue === 'object' ? JSON.stringify(jsonValue) : jsonValue,
    [jsonValue],
  );

  return (
    <ModalTrigger
      modalBody={
        // JSON is left-to-right, and the tree indents with physical inline
        // styles.
        <LtrIsolate>
          <JSONTree
            data={jsonObject}
            theme={jsonTreeTheme}
            valueRenderer={renderBigIntStrToNumber}
          />
        </LtrIsolate>
      }
      modalFooter={
        <Button>
          <CopyToClipboard shouldShowText={false} text={content} />
        </Button>
      }
      modalTitle={modalTitle}
      triggerNode={
        wrapContent ? <PreWrap dir="ltr">{content}</PreWrap> : content
      }
    />
  );
};

export type { JsonModalProps };
