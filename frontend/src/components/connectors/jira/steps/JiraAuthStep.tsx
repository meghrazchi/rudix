"use client";

import { useState } from "react";
import type { WizardStepProps } from "@/components/connectors/wizard/types";
import type { JiraWizardState } from "../JiraWizard.types";

type Status = "idle" | "authorizing" | "authorized";

export function JiraAuthStep({ state, onChange, onNext }: WizardStepProps<JiraWizardState>) {
  const [status, setStatus] = useState<Status>(
    state.authorized ? "authorized" : "idle",
  );

  function handleConnect() {
    if (!state.siteUrl.trim()) return;
    setStatus("authorizing");

    // In production this would initiate OAuth via POST /connectors/oauth/connect
    // and redirect to Atlassian. Here we simulate the callback completing.
    setTimeout(() => {
      setStatus("authorized");
      onChange({ authorized: true });
      setTimeout(onNext, 600);
    }, 1500);
  }

  const siteUrl = state.siteUrl;
  const cleanHost = siteUrl.replace(/^https?:\/\//, "").replace(/\.atlassian\.net.*$/, "");

  return (
    <div>
      <h2 className="text-2xl font-semibold tracking-tight text-[#1b1b24] mb-1">
        Authorize Connection
      </h2>
      <p className="text-base text-[#464555] mb-8">
        Enter your Jira Cloud site URL to begin the secure OAuth 2.0
        authentication flow.
      </p>

      <div className="space-y-6 max-w-lg">
        <div>
          <label
            htmlFor="jira-site-slug"
            className="block text-sm font-semibold text-[#1b1b24] mb-2"
          >
            Jira Site URL
          </label>
          <div className="flex rounded-lg border border-[#c7c4d8] overflow-hidden focus-within:border-[#3525cd] focus-within:ring-2 focus-within:ring-[#3525cd]/20 transition-all">
            <input
              id="jira-site-slug"
              type="text"
              placeholder="your-company"
              value={cleanHost}
              onChange={(e) =>
                onChange({
                  siteUrl: `https://${e.target.value}.atlassian.net`,
                  authorized: false,
                })
              }
              disabled={status !== "idle"}
              className="flex-1 px-4 py-3 bg-white outline-none text-sm text-[#1b1b24] placeholder:text-[#777587] disabled:opacity-60"
            />
            <span className="px-4 py-3 bg-[#f5f2ff] text-[#464555] text-sm font-mono border-l border-[#c7c4d8] select-none">
              .atlassian.net
            </span>
          </div>
          <p className="mt-1.5 text-xs text-[#464555]">
            Example: <span className="font-mono">acme-inc.atlassian.net</span>
          </p>
        </div>

        <button
          type="button"
          onClick={handleConnect}
          disabled={!cleanHost.trim() || status === "authorizing" || status === "authorized"}
          className={`w-full py-4 rounded-lg font-bold flex items-center justify-center gap-2 transition-all active:scale-[0.98] disabled:cursor-not-allowed ${
            status === "authorized"
              ? "bg-emerald-600 text-white"
              : "bg-[#3525cd] text-white hover:opacity-90 disabled:opacity-50"
          }`}
        >
          {status === "idle" && (
            <>
              <span className="material-symbols-outlined text-[20px]">key</span>
              Connect Jira Account
            </>
          )}
          {status === "authorizing" && (
            <>
              <span className="material-symbols-outlined text-[20px] animate-spin">sync</span>
              Authorizing…
            </>
          )}
          {status === "authorized" && (
            <>
              <span className="material-symbols-outlined text-[20px]">check_circle</span>
              Authorized
            </>
          )}
        </button>

        <div className="flex items-start gap-2 p-4 bg-amber-50 border border-amber-200 rounded-lg text-amber-800">
          <span className="material-symbols-outlined text-[20px] shrink-0 mt-0.5">info</span>
          <p className="text-xs leading-relaxed">
            We use restricted-scope API tokens. Rudix will never have access to
            your personal account password or billing information.
          </p>
        </div>
      </div>
    </div>
  );
}
