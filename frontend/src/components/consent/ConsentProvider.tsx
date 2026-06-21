"use client";

import Script from "next/script";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  CONSENT_POLICY_VERSION,
  type ConsentDecisions,
  type ConsentRecord,
  createDefaultConsentDecisions,
  readConsentRecord,
  writeConsentRecord,
} from "@/lib/consent";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

type ConsentContextValue = {
  isLoaded: boolean;
  hasResponded: boolean;
  decisions: ConsentDecisions;
  preferencesOpen: boolean;
  acceptAll: () => void;
  rejectNonEssential: () => void;
  updateDecisions: (partial: Partial<ConsentDecisions>) => void;
  openPreferences: () => void;
  closePreferences: () => void;
};

const ConsentContext = createContext<ConsentContextValue | null>(null);

export function useConsentContext(): ConsentContextValue {
  const ctx = useContext(ConsentContext);
  if (!ctx) {
    throw new Error("useConsentContext must be used within ConsentProvider");
  }
  return ctx;
}

function getGaId(): string | null {
  const id = process.env.NEXT_PUBLIC_GA_ID;
  return id && id.trim().length > 0 ? id.trim() : null;
}

function getMatomoConfig(): { url: string; siteId: string } | null {
  const config = getFrontendRuntimeConfig().analytics;
  if (!config.matomoUrl || !config.matomoSiteId) {
    return null;
  }
  return { url: config.matomoUrl, siteId: config.matomoSiteId };
}

type ConsentProviderProps = {
  children: ReactNode;
};

export function ConsentProvider({ children }: ConsentProviderProps) {
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasResponded, setHasResponded] = useState(false);
  const [decisions, setDecisions] = useState<ConsentDecisions>(
    createDefaultConsentDecisions(),
  );
  const [preferencesOpen, setPreferencesOpen] = useState(false);

  useEffect(() => {
    const record = readConsentRecord();
    queueMicrotask(() => {
      if (record && record.policyVersion === CONSENT_POLICY_VERSION) {
        setHasResponded(true);
        setDecisions(record.decisions);
      }
      setIsLoaded(true);
    });
  }, []);

  const persist = useCallback((d: ConsentDecisions) => {
    const record: ConsentRecord = {
      policyVersion: CONSENT_POLICY_VERSION,
      timestamp: Date.now(),
      decisions: d,
    };
    writeConsentRecord(record);
    setDecisions(d);
    setHasResponded(true);
  }, []);

  const acceptAll = useCallback(() => {
    persist({ functional: true, analytics: true });
    setPreferencesOpen(false);
  }, [persist]);

  const rejectNonEssential = useCallback(() => {
    persist({ functional: false, analytics: false });
    setPreferencesOpen(false);
  }, [persist]);

  const updateDecisions = useCallback(
    (partial: Partial<ConsentDecisions>) => {
      persist({ ...decisions, ...partial });
      setPreferencesOpen(false);
    },
    [decisions, persist],
  );

  const openPreferences = useCallback(() => setPreferencesOpen(true), []);
  const closePreferences = useCallback(() => setPreferencesOpen(false), []);

  const gaId = getGaId();
  const runtimeConfig = getFrontendRuntimeConfig();
  const matomo = getMatomoConfig();
  const loadAnalytics =
    isLoaded &&
    decisions.analytics &&
    gaId !== null &&
    runtimeConfig.features.analyticsEnabled;
  const loadMatomo =
    isLoaded &&
    decisions.analytics &&
    matomo !== null &&
    runtimeConfig.features.analyticsEnabled;

  return (
    <ConsentContext.Provider
      value={{
        isLoaded,
        hasResponded,
        decisions,
        preferencesOpen,
        acceptAll,
        rejectNonEssential,
        updateDecisions,
        openPreferences,
        closePreferences,
      }}
    >
      {loadAnalytics && gaId && (
        <>
          <Script
            src={`https://www.googletagmanager.com/gtag/js?id=${gaId}`}
            strategy="afterInteractive"
          />
          <Script id="rudix-ga-init" strategy="afterInteractive">
            {`window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${gaId}');`}
          </Script>
        </>
      )}
      {loadMatomo && matomo ? (
        <>
          <Script id="rudix-matomo-init" strategy="afterInteractive">
            {`window._paq=window._paq||[];_paq.push(['trackPageView']);_paq.push(['enableLinkTracking']);(function(){var u='${matomo.url.replace(/\/$/, "")}/';_paq.push(['setTrackerUrl',u+'matomo.php']);_paq.push(['setSiteId','${matomo.siteId}']);var d=document,g=d.createElement('script'),s=d.getElementsByTagName('script')[0];g.async=true;g.src=u+'matomo.js';s.parentNode.insertBefore(g,s);})();`}
          </Script>
        </>
      ) : null}
      {children}
    </ConsentContext.Provider>
  );
}
