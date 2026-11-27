import { useEffect, useRef, useState } from "react";

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { CONTEXT_MODAL_PAGE_SIZE } from "@/components/chat/chat-types";
import { listDocuments } from "@/lib/api/documents";
import { queryKeys } from "@/lib/api/query";

export function useContextModal() {
  const contextModalRef = useRef<HTMLDivElement | null>(null);
  const [contextSearchQuery, setContextSearchQuery] = useState("");
  const [contextPage, setContextPage] = useState(1);
  const [isContextModalOpen, setIsContextModalOpen] = useState(false);
  const contextModalOffset = (contextPage - 1) * CONTEXT_MODAL_PAGE_SIZE;
  const contextModalQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: CONTEXT_MODAL_PAGE_SIZE,
      offset: contextModalOffset,
      filename_query: contextSearchQuery.trim() || undefined,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: CONTEXT_MODAL_PAGE_SIZE,
        offset: contextModalOffset,
        filename_query: contextSearchQuery.trim() || undefined,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
    placeholderData: keepPreviousData,
  });
  const contextModalTotal = contextModalQuery.data?.total ?? 0;
  const contextPageCount = Math.max(
    1,
    Math.ceil(contextModalTotal / CONTEXT_MODAL_PAGE_SIZE),
  );
  const boundedContextPage = Math.min(contextPage, contextPageCount);
  const contextPageStartIndex =
    contextModalTotal === 0 ? 0 : contextModalOffset + 1;
  const contextPageEndIndex = Math.min(
    contextModalOffset + CONTEXT_MODAL_PAGE_SIZE,
    contextModalTotal,
  );

  useEffect(() => {
    if (!isContextModalOpen) {
      return;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      setIsContextModalOpen(false);
      setContextSearchQuery("");
      setContextPage(1);
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [isContextModalOpen]);

  return {
    contextModalRef,
    contextSearchQuery,
    setContextSearchQuery,
    setContextPage,
    isContextModalOpen,
    setIsContextModalOpen,
    contextModalQuery,
    contextModalTotal,
    contextPageCount,
    boundedContextPage,
    contextPageStartIndex,
    contextPageEndIndex,
  };
}

export type ContextModalController = ReturnType<typeof useContextModal>;
