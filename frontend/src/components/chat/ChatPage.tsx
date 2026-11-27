"use client";

import { useState } from "react";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";

import { AnswerShareModal } from "@/components/chat/AnswerShareModal";
import { ChatComposerPane } from "@/components/chat/ChatComposerPane";
import { ChatFeedbackModals } from "@/components/chat/ChatFeedbackModals";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatSidebar } from "@/components/chat/ChatSidebar";
import { ChatThread } from "@/components/chat/ChatThread";
import { DeleteSessionModal } from "@/components/chat/DeleteSessionModal";
import { EvidenceAside } from "@/components/chat/EvidenceAside";
import { ScopeControls } from "@/components/chat/ScopeControls";
import { ShareModal } from "@/components/chat/ShareModal";
import { TrustPanelModal } from "@/components/chat/TrustPanelModal";
import { isAdminLikeRole } from "@/components/chat/chat-session-utils";
import { useAgentRunTimeline } from "@/components/chat/hooks/useAgentRunTimeline";
import { useChatFeedback } from "@/components/chat/hooks/useChatFeedback";
import { useChatOverlays } from "@/components/chat/hooks/useChatOverlays";
import { useChatScope } from "@/components/chat/hooks/useChatScope";
import { useChatSession } from "@/components/chat/hooks/useChatSession";
import { useChatSettings } from "@/components/chat/hooks/useChatSettings";
import { useChatSubmit } from "@/components/chat/hooks/useChatSubmit";
import { useCitationPanel } from "@/components/chat/hooks/useCitationPanel";
import { useContextModal } from "@/components/chat/hooks/useContextModal";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { CreateVerifiedAnswerModal } from "@/components/verified-answers/CreateVerifiedAnswerModal";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { loadSettingsPreferences } from "@/lib/settings-preferences";
import { useAuthSession } from "@/lib/use-auth-session";

export { toTurnResponseFromHistoryMessage } from "@/components/chat/chat-turns";

export function ChatPage() {
  const tc = useTranslations("chat.page");
  const searchParams = useSearchParams();
  const { state } = useAuthSession();
  const [question, setQuestion] = useState("");
  const activeOrgId = state.session?.organizationId ?? null;

  const settings = useChatSettings({
    organizationId: activeOrgId,
    userId: state.session?.userId ?? null,
  });
  const feedback = useChatFeedback();
  const overlays = useChatOverlays();
  const contextModal = useContextModal();
  const scope = useChatScope({
    persistedSettings: settings.persistedSettings,
    documentIdFromQuery: searchParams.get("document_id"),
    collectionIdFromQuery: searchParams.get("collection_id"),
    connectorIdFromQuery: searchParams.get("connection_id"),
    activeOrgId,
  });
  const session = useChatSession({
    searchParams,
    chatFeedbackEnabled: feedback.chatFeedbackEnabled,
    setFeedbackByMessageId: feedback.setFeedbackByMessageId,
    setQuestion,
  });
  const settingsPreferencesQuery = useQuery({
    queryKey: ["settings", "preferences", "chat"],
    queryFn: loadSettingsPreferences,
    retry: false,
  });
  const panel = useCitationPanel({
    selectedCitationTurn: session.selectedCitationTurn,
  });
  const agentRun = useAgentRunTimeline({
    selectedCitationTurn: session.selectedCitationTurn,
  });
  const submit = useChatSubmit({
    question,
    setQuestion,
    scope,
    settings,
    session,
  });

  const { thread, activeSessionId, activeSessionDisplayTitle } = session;
  const role = state.session?.role ?? null;
  const canDecideApprovals = isAdminLikeRole(role);
  const showDebugDetails =
    isAdminLikeRole(role) ||
    Boolean(settingsPreferencesQuery.data?.developerMode);
  const openTrustPanelTurn =
    thread.find(
      (turn) => turn.response.message_id === overlays.openTrustPanelMessageId,
    ) ?? null;

  const listForbidden =
    isForbiddenError(scope.indexedDocumentsQuery.error) ||
    isForbiddenError(session.sessionsQuery.error);

  if (listForbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title={tc("accessRestrictedTitle")}
          description={tc("accessRestrictedDesc")}
          requestId={extractRequestIdFromError(
            scope.indexedDocumentsQuery.error ?? session.sessionsQuery.error,
          )}
          compact={false}
        />
      </section>
    );
  }

  return (
    <>
      <section className="flex h-full min-h-0 flex-col overflow-hidden bg-[#fcf8ff] text-[#1b1b24]">
        <div
          className={`grid min-h-0 flex-1 overflow-hidden xl:grid-rows-[1fr] ${panel.isKnowledgeHubOpen || panel.previewCitationSet !== null ? "xl:grid-cols-[280px_minmax(0,1fr)_420px]" : "xl:grid-cols-[280px_minmax(0,1fr)]"}`}
        >
          <ChatSidebar session={session} />

          <section className="flex min-h-0 flex-col overflow-hidden bg-white shadow-sm">
            <div className="flex min-h-0 flex-1 flex-col">
              <ChatHeader session={session} overlays={overlays} />
              <ChatThread
                session={session}
                panel={panel}
                feedback={feedback}
                overlays={overlays}
                submit={submit}
                selectedCollectionIds={scope.selectedCollectionIds}
              />
              <ChatComposerPane
                question={question}
                setQuestion={setQuestion}
                scope={scope}
                settings={settings}
                session={session}
                submit={submit}
              />
            </div>
          </section>

          <EvidenceAside
            panel={panel}
            agentRun={agentRun}
            selectedCitationTurn={session.selectedCitationTurn}
            canDecideApprovals={canDecideApprovals}
            showDebugDetails={showDebugDetails}
          />
        </div>
      </section>

      <ScopeControls scope={scope} contextModal={contextModal} />

      {overlays.isShareModalOpen && activeSessionId ? (
        <ShareModal
          sessionId={activeSessionId}
          sessionTitle={activeSessionDisplayTitle}
          onClose={() => overlays.setIsShareModalOpen(false)}
        />
      ) : null}

      {overlays.answerShareMessageId ? (
        <AnswerShareModal
          messageId={overlays.answerShareMessageId}
          onClose={() => overlays.setAnswerShareMessageId(null)}
        />
      ) : null}

      {openTrustPanelTurn ? (
        <TrustPanelModal
          openTrustPanelTurn={openTrustPanelTurn}
          showDebugDetails={showDebugDetails}
          session={session}
          panel={panel}
          feedback={feedback}
          overlays={overlays}
        />
      ) : null}

      <DeleteSessionModal session={session} />

      <ChatFeedbackModals feedback={feedback} thread={thread} />

      {overlays.saveKnowledgeCardMessageId ? (
        <CreateVerifiedAnswerModal
          mode={{
            kind: "from-message",
            messageId: overlays.saveKnowledgeCardMessageId,
          }}
          onClose={() => overlays.setSaveKnowledgeCardMessageId(null)}
          invalidateKey={["verified-answers"]}
        />
      ) : null}
    </>
  );
}
