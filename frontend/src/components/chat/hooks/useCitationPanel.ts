import { useMemo, useState } from "react";

import { useQuery, useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  buildCitationDocumentHref,
  citationDisplayTitle,
  getCitationScore,
  getCitationSourceHref,
  isExternalHref,
} from "@/components/chat/chat-citations";
import {
  normalizeScorePercent,
  triggerBlobDownload,
} from "@/components/chat/chat-format";
import type { ChatTurn } from "@/components/chat/chat-types";
import type { ChatCitationResponse } from "@/lib/api/chat";
import { downloadDocumentFile, getDocumentChunks } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";

export function useCitationPanel({
  selectedCitationTurn,
}: {
  selectedCitationTurn: ChatTurn | null;
}) {
  const tc = useTranslations("chat.page");
  const [previewCitationSet, setPreviewCitationSet] = useState<{
    citations: ChatCitationResponse[];
    initialIndex: number;
  } | null>(null);
  const [isKnowledgeHubOpen, setIsKnowledgeHubOpen] = useState(false);
  const [copiedCitationLinkKey, setCopiedCitationLinkKey] = useState<
    string | null
  >(null);

  const citationDownloadMutation = useMutation({
    mutationFn: (citation: ChatCitationResponse) =>
      downloadDocumentFile(citation.document_id),
    onSuccess: (blob, citation) => {
      triggerBlobDownload(
        blob,
        citation.filename?.trim() || `document-${citation.document_id}`,
      );
    },
  });

  const selectedCitationDocumentCount = useMemo(() => {
    if (!selectedCitationTurn) {
      return 0;
    }
    const uniqueDocumentIds = new Set(
      selectedCitationTurn.response.citations
        .map((citation) => citation.document_id)
        .filter((documentId): documentId is string => documentId.length > 0),
    );
    return uniqueDocumentIds.size;
  }, [selectedCitationTurn]);
  const previewCitationIndex = useMemo(() => {
    if (!previewCitationSet || previewCitationSet.citations.length === 0) {
      return -1;
    }
    return Math.min(
      Math.max(previewCitationSet.initialIndex, 0),
      previewCitationSet.citations.length - 1,
    );
  }, [previewCitationSet]);
  const activePreviewCitation =
    previewCitationSet && previewCitationIndex >= 0
      ? previewCitationSet.citations[previewCitationIndex]
      : null;
  const activePreviewCitationChunkQuery = useQuery({
    queryKey: queryKeys.citationChunk(
      activePreviewCitation?.document_id ?? "none",
      activePreviewCitation?.chunk_id ?? "none",
    ),
    // The chunk_id filter returns just the cited chunk (R07-06) instead of
    // scanning the first 200 chunks of the document for it.
    queryFn: () =>
      activePreviewCitation?.chunk_id
        ? getDocumentChunks(activePreviewCitation.document_id, {
            limit: 1,
            include_full_text: true,
            chunk_id: activePreviewCitation.chunk_id,
          })
        : Promise.reject(new Error("No citation id")),
    enabled: Boolean(activePreviewCitation?.chunk_id),
    retry: false,
  });
  const activePreviewCitationChunk =
    activePreviewCitationChunkQuery.data?.items.find(
      (item) => item.chunk_id === activePreviewCitation?.chunk_id,
    ) ?? null;
  const activePreviewCitationTitle = activePreviewCitation
    ? citationDisplayTitle(activePreviewCitation, tc("unknownDocument"))
    : null;
  const activePreviewCitationDocumentHref = activePreviewCitation
    ? buildCitationDocumentHref(activePreviewCitation)
    : null;
  const activePreviewCitationSourceHref = activePreviewCitation
    ? getCitationSourceHref(activePreviewCitation)
    : null;
  const isActivePreviewCitationSourceExternal =
    activePreviewCitationSourceHref !== null &&
    isExternalHref(activePreviewCitationSourceHref);
  const activePreviewCitationKey = activePreviewCitation
    ? `${activePreviewCitation.document_id}:${activePreviewCitation.chunk_id ?? ""}:${previewCitationIndex}`
    : null;
  const activePreviewCitationScore = activePreviewCitation
    ? getCitationScore(activePreviewCitation)
    : null;
  const activePreviewCitationScorePercent = normalizeScorePercent(
    activePreviewCitationScore,
  );
  const relatedPreviewCitations = useMemo(() => {
    if (!previewCitationSet || previewCitationIndex < 0) {
      return [];
    }
    return previewCitationSet.citations
      .map((citation, index) => ({ citation, index }))
      .filter(({ index }) => index !== previewCitationIndex);
  }, [previewCitationIndex, previewCitationSet]);

  return {
    previewCitationSet,
    setPreviewCitationSet,
    isKnowledgeHubOpen,
    setIsKnowledgeHubOpen,
    copiedCitationLinkKey,
    setCopiedCitationLinkKey,
    citationDownloadMutation,
    selectedCitationDocumentCount,
    previewCitationIndex,
    activePreviewCitation,
    activePreviewCitationChunkQuery,
    activePreviewCitationChunk,
    activePreviewCitationTitle,
    activePreviewCitationDocumentHref,
    activePreviewCitationSourceHref,
    isActivePreviewCitationSourceExternal,
    activePreviewCitationKey,
    activePreviewCitationScore,
    activePreviewCitationScorePercent,
    relatedPreviewCitations,
  };
}

export type CitationPanelController = ReturnType<typeof useCitationPanel>;
