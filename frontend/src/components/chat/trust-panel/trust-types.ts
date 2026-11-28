import type { ChatCitationResponse } from "@/lib/api/chat";
import type { CitationTrustRecord } from "@/lib/api/trust_metadata";

export type TrustPanelCitation = ChatCitationResponse | CitationTrustRecord;

/** Translator for the `chat.trustPanel` namespace, passed to pure helpers. */
export type TrustT = (
  key: string,
  values?: Record<string, string | number>,
) => string;
