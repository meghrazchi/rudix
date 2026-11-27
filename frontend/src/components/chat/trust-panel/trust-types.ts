import type { ChatCitationResponse } from "@/lib/api/chat";
import type { CitationTrustRecord } from "@/lib/api/trust_metadata";

export type TrustPanelCitation = ChatCitationResponse | CitationTrustRecord;
