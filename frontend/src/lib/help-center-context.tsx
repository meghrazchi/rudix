"use client";

import { createContext, useContext } from "react";

export type HelpTopic =
  | "upload-documents"
  | "chat-ask"
  | "multilingual"
  | "verify-citations"
  | "manage-collections"
  | "run-evaluations"
  | "rag-pipeline"
  | "manage-connectors"
  | "agent-workspace"
  | "manage-users"
  | "billing"
  | "security";

type HelpCenterContextValue = {
  openHelpCenter: (topic?: HelpTopic) => void;
  openKeyboardShortcuts: () => void;
};

export const HelpCenterContext = createContext<HelpCenterContextValue | null>(
  null,
);

export function useHelpCenter(): HelpCenterContextValue {
  const ctx = useContext(HelpCenterContext);
  if (!ctx) {
    return {
      openHelpCenter: () => {},
      openKeyboardShortcuts: () => {},
    };
  }
  return ctx;
}
