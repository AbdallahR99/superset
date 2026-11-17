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
import { useEffect, useState } from 'react';
import type { ReactElement } from 'react';
import { useSelector } from 'react-redux';
import { t } from '@apache-superset/core/translation';
import { css, styled } from '@apache-superset/core/theme';
import { FeatureFlag, isFeatureEnabled } from '@superset-ui/core';
import { extendedDayjs } from '@superset-ui/core/utils/dates';
import {
  Button,
  Divider,
  Input,
  PublishedLabel,
  Typography,
} from '@superset-ui/core/components';
import MetadataBar, {
  MetadataType,
} from '@superset-ui/core/components/MetadataBar';
import { Icons } from '@superset-ui/core/components/Icons';
import type { BootstrapUser } from 'src/types/bootstrapTypes';
import { provider, useDashboardRevision } from 'src/core/dashboard/store';
import { useDashboardSession } from 'src/core/dashboard/session';
import ConflictDialog from './ConflictDialog';
import EmbedDashboardModal from './EmbedDashboardModal';
import Inert from './InertControl';
import { useSaveDashboard } from './useSaveDashboard';

/**
 * Who is making this dashboard, and when it was last written down.
 *
 * The two facts a dashboard carries about itself rather than about its
 * contents, drawn with the same `MetadataBar` the saved dashboard header
 * uses — so a dashboard being built and one being read state them in the
 * same shape, with the same icons, in the same place.
 *
 * A dashboard being created is being created by whoever is looking at it,
 * so the author is read from the signed-in user rather than invented. When
 * it was last written is stated only once there is a row behind the page
 * that says so: until the first save there is no modified time to humanize,
 * and "a day ago" on a dashboard nothing has ever written would be the only
 * thing on this bar stating a fact that is not one.
 */
/**
 * The signed-in person's name.
 *
 * Assembled here rather than through `getUserName`, which reads the
 * `first_name`/`last_name` an API hands back for an owner. The session user
 * is the same person in a different shape — `firstName`/`lastName` off the
 * bootstrap — and passing one to the other returns an empty string rather
 * than failing, which is how this first went out reading "Not available"
 * over a perfectly well-known name.
 */
const nameOf = (user: BootstrapUser): string =>
  [user?.firstName, user?.lastName].filter(Boolean).join(' ') ||
  user?.username ||
  '';

/** When the row was last written, in words; `undefined` when it cannot be read as a time. */
const humanize = (changedOn: string | undefined): string | undefined => {
  if (!changedOn) return undefined;
  const when = extendedDayjs(changedOn);
  return when.isValid() ? when.fromNow() : undefined;
};

const Metadata = ({
  saved,
  changedOn,
}: {
  /** Whether there is a saved row behind the page at all. */
  saved: boolean;
  changedOn: string | undefined;
}): ReactElement => {
  const user = useSelector<{ user?: BootstrapUser }, BootstrapUser>(
    state => state.user,
  );
  const author = nameOf(user) || t('Not available');
  const unsaved = saved
    ? (humanize(changedOn) ?? t('Saved'))
    : t('Not saved yet');

  return (
    <span data-test="header-metadata">
      <MetadataBar
        tooltipPlacement="bottom"
        items={[
          {
            type: MetadataType.Editor,
            createdBy: author,
            editors: t('None'),
            createdOn: unsaved,
          },
          {
            type: MetadataType.LastModified,
            value: unsaved,
            modifiedBy: author,
          },
        ]}
      />
    </span>
  );
};

/**
 * The name, drawn as a name rather than as a field.
 *
 * A bordered box on a bar of small controls read as one more control, and the
 * one thing on the bar that says what you are looking at was the hardest thing
 * on it to find. Borderless at the heading weight, it reads as the title it
 * is; the surface arriving under the pointer and on focus is what still says
 * it can be typed into, which is the same trade the editable titles elsewhere
 * in the app make.
 */
const TitleInput = styled(Input)`
  ${({ theme }) => css`
    max-width: ${theme.sizeUnit * 60}px;
    height: ${theme.controlHeightSM}px;
    padding-inline: ${theme.sizeUnit}px;
    font-size: ${theme.fontSizeLG}px;
    font-weight: ${theme.fontWeightStrong};
    color: ${theme.colorText};
    background-color: transparent;
    transition: background-color ${theme.motionDurationMid};

    &:hover,
    &:focus {
      background-color: ${theme.colorFillQuaternary};
    }

    &::placeholder {
      font-weight: ${theme.fontWeightNormal};
      color: ${theme.colorTextTertiary};
    }
  `}
`;

/**
 * The dashboard's name, edited where it is read.
 *
 * It is stored on the root node rather than in this component, because a name
 * is something the dashboard has and not something this screen remembers: put
 * in page state it would be invisible to the assistant, unreachable by the
 * client tools, and gone on the next navigation. The root canvas is the only
 * node a dashboard-level fact can belong to, so that is where it lives.
 *
 * A title is also a `markdown` widget an author can place at the top of the
 * canvas, and that stays true — this is a different thing with a different
 * job. That one is content, laid out and arranged like any other widget; this
 * one is what the dashboard is called.
 *
 * The draft commits on blur rather than on every keystroke: a name being
 * typed is not a name, and one commit per character would be one revision
 * tick per character for everything subscribed to the store.
 */
const Title = ({ nodeId, title }: { nodeId: string; title: string }) => {
  const [draft, setDraft] = useState(title);
  // What was accepted replaces the draft, because the draft was a view of it:
  // a rename the assistant makes while this is on screen has to show.
  useEffect(() => setDraft(title), [title]);

  return (
    <TitleInput
      size="small"
      variant="borderless"
      value={draft}
      aria-label={t('Dashboard title')}
      placeholder={t('Untitled dashboard')}
      data-test="header-title"
      onChange={event => setDraft(event.target.value)}
      onBlur={() => {
        const next = draft.trim();
        // An empty name is not a rename. Restoring the draft rather than
        // writing the blank is what keeps a stray select-all-and-delete from
        // silently leaving the dashboard nameless.
        if (next === '') {
          setDraft(title);
        } else if (next !== title) {
          provider.updateProps(nodeId, { title: next });
        }
      }}
    />
  );
};

/**
 * The bar itself.
 *
 * Inset horizontally the way the rest of the app insets a page header, so the
 * left edge of the bar and the left edge of the work below it are one line
 * rather than two a few pixels apart. The rule beneath is `colorSplit` — what
 * this app draws a separator with — rather than the heavier border it shares
 * with the boxes that hold things.
 */
const Bar = styled.header`
  ${({ theme }) => css`
    display: flex;
    align-items: center;
    gap: ${theme.sizeUnit * 2}px;
    flex: 0 0 auto;
    padding: ${theme.sizeUnit * 2}px ${theme.sizeUnit * 4}px;
    border-bottom: 1px solid ${theme.colorSplit};
    background-color: ${theme.colorBgContainer};
  `}
`;

/** What an author does to the whole dashboard, at the end they read last. */
const Actions = styled.span`
  ${({ theme }) => css`
    display: flex;
    align-items: center;
    gap: ${theme.sizeUnit * 2}px;
    margin-left: auto;
  `}
`;

/**
 * The dashboard's header: what this dashboard is, and what can be done to it.
 *
 * Two kinds of thing share the bar. On the left is the dashboard as the
 * product would know it — where to start from, where it has been, what it is
 * called, whether it is published, and whose it is. On the right is what an
 * author does to the whole of it: step back through what they did, or write
 * it down.
 *
 * How the canvas is arranged is not among them. It reads like chrome and is
 * not: it is a property of the root node, sitting in the same `layout` the
 * columns and the gap sit in, and asking for it here put one third of that
 * one decision on the other side of the screen from the rest. It is asked in
 * the root's own properties now, where a canvas is selected and arranged in
 * one place.
 */
export default function DashboardHeader(): ReactElement {
  useDashboardRevision();
  const root = provider.getRoot();
  // Which dashboard this is, whether it is loaded, and whether a save is
  // running are the session's to say (`src/core/dashboard/session`). Nothing
  // about them is kept here, so this bar cannot disagree with the tree about
  // which dashboard a save would write to.
  const session = useDashboardSession();
  const save = useSaveDashboard();
  const [showEmbed, setShowEmbed] = useState(false);
  const ready = session.status === 'ready';
  // Embedding hands data to another site through guest tokens; where the
  // deployment has not turned that on there is nothing to offer, and an
  // action that could only lead to a refusal is left off the bar.
  const canEmbed = isFeatureEnabled(FeatureFlag.EmbeddedSuperset);

  return (
    <Bar data-test="dashboard-header">
      {/* Where this dashboard came from: a starting point to build on, asked
          before the work rather than during it, which is why it leads the
          bar. History used to sit beside it on that reasoning and has gone to
          the other end — it is read against saving, not against starting. */}
      <Inert label={t('Templates')} test="header-templates" reads>
        {t('Templates')}
      </Inert>
      <Title
        nodeId={root.id}
        title={typeof root.props?.title === 'string' ? root.props.title : ''}
      />
      <Inert label={t('Favorite')} test="header-favorite" buttonStyle="link">
        <Icons.StarOutlined iconSize="m" />
      </Inert>
      {/* Nothing here can publish, so the chip states the only status this
          page can honestly claim. */}
      <span data-test="header-published">
        <PublishedLabel isPublished={false} />
      </span>
      {/* Beside the status rather than opposite it: whether a dashboard is a
          draft, whose it is, and when it was last written are one answer to
          one question — what state is this in — and they are read together. */}
      <Metadata
        saved={session.dashboardId !== undefined}
        changedOn={session.changedOn}
      />
      {/* Said only while it is true, so its absence means the server has
          what is on screen. */}
      {session.dirty && (
        <Typography.Text type="secondary" data-test="header-unsaved">
          {t('Unsaved changes')}
        </Typography.Text>
      )}

      <Actions>
        {/* Icons, not words, because these two are reached by muscle memory
            far more often than they are read. The name stays on them for
            anyone not reading with their eyes. */}
        <Inert label={t('Undo')} test="header-undo">
          <Icons.UndoOutlined iconSize="s" />
        </Inert>
        <Inert label={t('Redo')} test="header-redo">
          <Icons.RedoOutlined iconSize="s" />
        </Inert>
        {/* Stepping back through the work and writing it down are two
            different acts on the bar's one crowded end, and at an even gap
            the four of them read as one run of controls. The rule is what
            says where one pair stops and the other starts. */}
        <Divider type="vertical" />
        {canEmbed && (
          <Button
            buttonStyle="secondary"
            buttonSize="small"
            disabled={!ready}
            onClick={() => setShowEmbed(true)}
            data-test="header-embed"
          >
            {t('Embed')}
          </Button>
        )}
        {/* Saving commits a version; History is the versions already
            committed. One concern, read in one place — so the record sits
            immediately before the button that produces what it lists, rather
            than at the far side of the bar from it. */}
        <Inert label={t('History')} test="header-history" reads>
          {t('History')}
        </Inert>
        <Button
          buttonStyle="primary"
          buttonSize="small"
          // A tree that is still loading, or that failed to load, is not the
          // dashboard the route names, and saving it would write a blank
          // over the one that is.
          disabled={!ready}
          loading={session.saving}
          onClick={save}
          data-test="header-save"
        >
          {t('Save')}
        </Button>
        {canEmbed && (
          <EmbedDashboardModal
            show={showEmbed}
            onHide={() => setShowEmbed(false)}
          />
        )}
        <ConflictDialog />
      </Actions>
    </Bar>
  );
}
