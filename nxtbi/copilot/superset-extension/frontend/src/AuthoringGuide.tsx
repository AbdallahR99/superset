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
import { useId, useSyncExternalStore } from 'react';
import type { CSSProperties } from 'react';
import { chat, menus, navigation, theme, views } from '@apache-superset/core';
import './authoring-guide.css';

const GUIDE_ID = 'nxtbi.ai-copilot.authoring';
const COPILOT_ID = 'nxtbi.ai-copilot';

const labels = {
  en: {
    title: 'Build a dashboard',
    data: 'Choose data',
    dataHelp: 'Start with a dataset you can access.',
    copilotDataHelp:
      'In Copilot, select Use existing data to choose a dataset and draft a dashboard. If you have upload permission, you can start with a CSV.',
    datasets: 'Browse datasets',
    copilot: 'Open Copilot',
    chart: 'Build a chart',
    chartHelp:
      'In Explore, choose a dataset and chart type. Add a saved metric, group by a column if needed, and run the chart with the filters you want.',
    openExplore: 'Create a chart',
    review: 'Review and publish',
    reviewHelp:
      'Save your chart to a dashboard. In Classic or V2, check the values and try the dashboard filters before publishing and sharing.',
    copilotReviewHelp:
      'Save your chart to a dashboard or select Review and save on a Copilot draft. In Classic or V2, check the values and try the dashboard filters before publishing and sharing.',
    dashboards: 'Open dashboards',
  },
  ar: {
    title: 'إنشاء لوحة معلومات',
    data: 'اختيار البيانات',
    dataHelp: 'ابدأ بمجموعة بيانات يمكنك الوصول إليها.',
    copilotDataHelp:
      'في المساعد، اختر «استخدام البيانات الموجودة» لتحديد مجموعة بيانات وإنشاء مسودة لوحة معلومات. إذا كان لديك إذن الرفع، يمكنك البدء بملف CSV.',
    datasets: 'تصفّح مجموعات البيانات',
    copilot: 'فتح المساعد',
    chart: 'إنشاء مخطط',
    chartHelp:
      'في صفحة الاستكشاف، اختر مجموعة البيانات ونوع المخطط. أضف مقياسًا محفوظًا، وحدّد عمودًا للتجميع عند الحاجة، ثم شغّل المخطط باستخدام عوامل التصفية المطلوبة.',
    openExplore: 'إنشاء مخطط',
    review: 'المراجعة والنشر',
    reviewHelp:
      'احفظ المخطط في لوحة معلومات. في اللوحة الكلاسيكية أو الإصدار الثاني، تحقّق من القيم وجرّب عوامل تصفية اللوحة قبل النشر والمشاركة.',
    copilotReviewHelp:
      'احفظ المخطط في لوحة معلومات أو اختر «مراجعة وحفظ» في مسودة المساعد. في اللوحة الكلاسيكية أو الإصدار الثاني، تحقّق من القيم وجرّب عوامل تصفية اللوحة قبل النشر والمشاركة.',
    dashboards: 'فتح لوحات المعلومات',
  },
};

function guideLanguage(): 'en' | 'ar' {
  return /^ar(?:$|[-_])/i.test(document.documentElement.lang) ? 'ar' : 'en';
}

function hasCopilot(): boolean {
  return chat.getChat()?.id === COPILOT_ID;
}

function subscribeToChat(callback: () => void): () => void {
  const registered = chat.onDidRegisterChat(callback);
  const unregistered = chat.onDidUnregisterChat(callback);
  return () => {
    registered.dispose();
    unregistered.dispose();
  };
}

function AuthoringLink({ path, label }: { path: string; label: string }) {
  const base = navigation.getApplicationRoot().replace(/\/$/, '');
  return (
    <a
      href={`${base}${path}`}
      onClick={event => {
        if (
          event.button ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        )
          return;
        event.preventDefault();
        navigation.navigateTo(path);
      }}
    >
      {label}
    </a>
  );
}

function AuthoringGuide() {
  const titleId = useId();
  const lang = guideLanguage();
  const text = labels[lang];
  const copilot = useSyncExternalStore(subscribeToChat, hasCopilot);
  const tokens = theme.useTheme();
  const colors: CSSProperties & Record<`--nxtbi-guide-${string}`, string> = {
    '--nxtbi-guide-surface': tokens.colorBgContainer,
    '--nxtbi-guide-border': tokens.colorBorderSecondary,
    '--nxtbi-guide-text': tokens.colorText,
    '--nxtbi-guide-secondary': tokens.colorTextSecondary,
    '--nxtbi-guide-link': tokens.colorLink,
    '--nxtbi-guide-focus': tokens.colorPrimary,
    '--nxtbi-guide-action': tokens.colorPrimaryBg,
  };

  return (
    <section
      className="nxtbi-authoring-guide"
      aria-labelledby={titleId}
      lang={lang}
      dir={theme.useDirection()}
      style={colors}
    >
      <h1 id={titleId}>{text.title}</h1>
      <ol className="nxtbi-authoring-guide__steps" role="list">
        <li>
          <h2>{text.data}</h2>
          <p>{copilot ? text.copilotDataHelp : text.dataHelp}</p>
          <div className="nxtbi-authoring-guide__actions">
            <AuthoringLink path="/tablemodelview/list/" label={text.datasets} />
            {copilot && (
              <button type="button" onClick={() => hasCopilot() && chat.open()}>
                {text.copilot}
              </button>
            )}
          </div>
        </li>
        <li>
          <h2>{text.chart}</h2>
          <p>{text.chartHelp}</p>
          <div className="nxtbi-authoring-guide__actions">
            <AuthoringLink path="/chart/add" label={text.openExplore} />
          </div>
        </li>
        <li>
          <h2>{text.review}</h2>
          <p>{copilot ? text.copilotReviewHelp : text.reviewHelp}</p>
          <div className="nxtbi-authoring-guide__actions">
            <AuthoringLink path="/dashboard/list/" label={text.dashboards} />
          </div>
        </li>
      </ol>
    </section>
  );
}

/** Contribute the author-only guide to the Superset page host and navbar. */
export function registerAuthoringGuide(): void {
  views.registerView(
    { id: GUIDE_ID, name: labels[guideLanguage()].title },
    views.PAGE_LOCATION,
    AuthoringGuide,
    { classPermissionName: 'Dashboard', methodPermissionName: 'write' },
  );
  menus.registerMenuItem({ page: GUIDE_ID }, menus.NAVBAR_LOCATION, 'primary');
}
