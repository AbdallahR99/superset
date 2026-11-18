/*
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

import { CopilotPanel, type CopilotHost } from "@nxtbi/copilot";
import "@nxtbi/copilot/styles.css";
import { lazy, Suspense, useState } from "react";
import { createRoot } from "react-dom/client";
import "./site.css";

const CopilotKitActivities = lazy(() =>
  import("@nxtbi/copilot/copilotkit").then((module) => ({
    default: module.CopilotKitActivities,
  })),
);

function Workspace() {
  const [locale, setLocale] = useState<"en" | "ar">("en");
  const isArabic = locale === "ar";
  const direction = isArabic ? "rtl" : "ltr";

  const host: CopilotHost = {
    locale,
    direction,
    context: () => ({ page: "standalone analytics workspace" }),
    run: (input, signal) =>
      fetch("/api/run", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "text/event-stream",
        },
        body: JSON.stringify(input),
        signal,
      }),
  };

  return (
    <main className="workspace" dir={direction} lang={locale}>
      <header className="workspace__header">
        <div>
          <h1>{isArabic ? "مساحة المساعد" : "Copilot workspace"}</h1>
          <p>
            {isArabic
              ? "استكشف واجهات تفاعلية من وصفك."
              : "Describe an interactive view and refine it as you go."}
          </p>
        </div>
        <button
          className="workspace__locale"
          type="button"
          onClick={() => setLocale(isArabic ? "en" : "ar")}
          lang={isArabic ? "en" : "ar"}
        >
          {isArabic ? "English" : "العربية"}
        </button>
      </header>
      <div className="workspace__assistant">
        <CopilotPanel
          host={host}
          renderActivities={(operations, onAction) =>
            operations.length ? (
              <Suspense fallback={null}>
                <CopilotKitActivities
                  direction={direction}
                  locale={locale}
                  runUrl={new URL("/api/run", window.location.origin).href}
                  operations={operations}
                  onAction={onAction}
                />
              </Suspense>
            ) : null
          }
        />
      </div>
    </main>
  );
}

const element = document.getElementById("root");
if (!element) throw new Error("Missing workspace root");
createRoot(element).render(<Workspace />);
