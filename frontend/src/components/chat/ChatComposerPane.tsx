import type { Dispatch, SetStateAction } from "react";

import { useTranslations } from "next-intl";

import { ChatComposer } from "@/components/chat/ChatComposer";
import {
  AGENTIC_CHAT_ENABLED,
  CHAT_WEBSOCKET_ENABLED,
  MAX_TOP_K,
  MIN_TOP_K,
} from "@/components/chat/chat-types";
import type { ChatScopeController } from "@/components/chat/hooks/useChatScope";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import type { ChatSettingsController } from "@/components/chat/hooks/useChatSettings";
import type { ChatSubmitController } from "@/components/chat/hooks/useChatSubmit";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError } from "@/lib/forbidden";

/** Composer error states plus the composer itself. */
export function ChatComposerPane({
  question,
  setQuestion,
  scope,
  settings,
  session,
  submit,
}: {
  question: string;
  setQuestion: Dispatch<SetStateAction<string>>;
  scope: ChatScopeController;
  settings: ChatSettingsController;
  session: ChatSessionController;
  submit: ChatSubmitController;
}) {
  const tc = useTranslations("chat.page");
  const { submitRequestId } = session;
  const {
    stream,
    composerForbidden,
    composerError,
    composerWsErrorKey,
    isComposerDisabled,
    composerSubmitButtonLabel,
    submitQuestion,
  } = submit;
  const {
    composerCollections,
    hasConnectorScopeSelection,
    hasAvailableDocuments,
    collectionsListQuery,
    connectorConnectionsQuery,
    documentPickerQuery,
    composerConnectorConnections,
    composerIndexedDocuments,
    totalIndexedDocuments,
    requiresUploadedDocuments,
    scopeMode,
    scopeWarning,
    selectedCollectionIds,
    selectedConnectorConnectionIds,
    selectedProviderSourceIds,
    selectedDocumentIds,
    documentSearchQuery,
    setDocumentSearchQuery,
    toggleCollection,
    toggleConnectorConnection,
    toggleDocument,
    toggleProviderSource,
    applyScopeMode,
  } = scope;
  const {
    agenticMode,
    answerLanguage,
    rerank,
    topK,
    setAgenticMode,
    setAnswerLanguage,
    setRerank,
    setTopK,
  } = settings;

  return (
    <>
      {composerForbidden ? (
        <div className="border-t border-[#e2dff1] px-4 py-3">
          <ForbiddenState
            compact
            title={tc("queryForbiddenTitle")}
            description={tc("queryForbiddenDesc")}
            requestId={extractRequestIdFromError(composerError)}
          />
        </div>
      ) : null}

      {composerError && !composerForbidden ? (
        <div className="border-t border-[#e2dff1] px-4 py-3">
          <ErrorState
            title={tc("queryErrorTitle")}
            error={composerError}
            description={
              composerWsErrorKey
                ? tc(`wsErrors.${composerWsErrorKey}`)
                : getApiErrorMessage(composerError)
            }
            requestId={submitRequestId}
          />
        </div>
      ) : null}

      <ChatComposer
        agenticChatEnabled={AGENTIC_CHAT_ENABLED}
        agenticMode={agenticMode}
        answerLanguage={answerLanguage}
        collections={composerCollections}
        disabled={isComposerDisabled}
        hasConnectorScopeSelection={hasConnectorScopeSelection}
        hasAvailableDocuments={hasAvailableDocuments}
        isCollectionsLoading={collectionsListQuery.isLoading}
        isConnectorsLoading={connectorConnectionsQuery.isLoading}
        isDocumentsLoading={documentPickerQuery.isLoading}
        connectorConnections={composerConnectorConnections}
        indexedDocuments={composerIndexedDocuments}
        totalIndexedDocuments={totalIndexedDocuments}
        isGenerating={CHAT_WEBSOCKET_ENABLED && stream.isPending}
        maxTopK={MAX_TOP_K}
        minTopK={MIN_TOP_K}
        onStop={() => stream.cancel()}
        onSubmit={submitQuestion}
        onToggleCollection={toggleCollection}
        onToggleConnectorConnection={toggleConnectorConnection}
        onToggleDocument={toggleDocument}
        onToggleProviderSource={toggleProviderSource}
        question={question}
        requiresUploadedDocuments={requiresUploadedDocuments}
        rerank={rerank}
        scopeMode={scopeMode}
        scopeWarning={scopeWarning}
        selectedCollectionIds={selectedCollectionIds}
        selectedConnectorConnectionIds={selectedConnectorConnectionIds}
        selectedProviderSourceIds={selectedProviderSourceIds}
        selectedDocumentIds={selectedDocumentIds}
        documentSearchQuery={documentSearchQuery}
        setAgenticMode={setAgenticMode}
        setAnswerLanguage={setAnswerLanguage}
        setQuestion={setQuestion}
        setRerank={setRerank}
        setScopeMode={applyScopeMode}
        setDocumentSearchQuery={setDocumentSearchQuery}
        setTopK={setTopK}
        submitButtonLabel={composerSubmitButtonLabel}
        topK={topK}
      />
    </>
  );
}
