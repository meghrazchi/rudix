import { useRef, useState } from "react";

import { useOverlayFocus } from "@/lib/use-overlay-focus";

export function useChatOverlays() {
  const [isShareModalOpen, setIsShareModalOpen] = useState(false);
  const [answerShareMessageId, setAnswerShareMessageId] = useState<
    string | null
  >(null);
  const [copiedMessageId, setCopiedMessageId] = useState<string | null>(null);
  const [openTrustPanelMessageId, setOpenTrustPanelMessageId] = useState<
    string | null
  >(null);
  const trustPanelModalRef = useRef<HTMLDivElement>(null);
  const trustPanelOverlayRef = useRef<HTMLDivElement>(null);
  const [saveKnowledgeCardMessageId, setSaveKnowledgeCardMessageId] = useState<
    string | null
  >(null);

  useOverlayFocus({
    isOpen: openTrustPanelMessageId !== null,
    containerRef: trustPanelModalRef,
    onClose: () => setOpenTrustPanelMessageId(null),
  });

  return {
    isShareModalOpen,
    setIsShareModalOpen,
    answerShareMessageId,
    setAnswerShareMessageId,
    copiedMessageId,
    setCopiedMessageId,
    openTrustPanelMessageId,
    setOpenTrustPanelMessageId,
    trustPanelModalRef,
    trustPanelOverlayRef,
    saveKnowledgeCardMessageId,
    setSaveKnowledgeCardMessageId,
  };
}

export type ChatOverlaysController = ReturnType<typeof useChatOverlays>;
