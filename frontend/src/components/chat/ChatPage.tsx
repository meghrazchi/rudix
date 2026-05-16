"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ForbiddenState } from "@/components/states/ForbiddenState";
import {
  listChatSessionMessages,
  listChatSessions,
  queryChat,
  type ChatCitationResponse,
  type ChatSessionMessageResponse,
  type ChatQueryRequest,
  type ChatQueryResponse,
} from "@/lib/api/chat";
import { listDocuments, type DocumentListItemResponse } from "@/lib/api/documents";
import { getApiErrorMessage } from "@/lib/api/errors";
import { invalidateAfterMutation, queryKeys } from "@/lib/api/query";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";

const DRAFT_SESSION_KEY = "__draft__";

function parsePositiveIntegerEnv(value: string | undefined, fallback: number): number {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

const MAX_INDEXED_DOCS = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_MAX_INDEXED_DOCS, 200);
const SESSION_LIST_LIMIT = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_SESSION_LIST_LIMIT, 50);
const MIN_TOP_K = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_MIN, 1);
const MAX_TOP_K = parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_MAX, 20);
const DEFAULT_TOP_K = Math.min(
  Math.max(parsePositiveIntegerEnv(process.env.NEXT_PUBLIC_CHAT_TOP_K_DEFAULT, 5), MIN_TOP_K),
  MAX_TOP_K,
);

type ChatTurn = {
  question: string;
  response: {
    message_id: string;
    answer: string;
    confidence_score: number;
    confidence_category: "low" | "medium" | "high";
    citations: ChatCitationResponse[];
    created_at: string;
  };
};

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "N/A";
  }
  return value.toFixed(3);
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "N/A";
  }
  return `${(value * 100).toFixed(1)}%`;
}

function confidenceBadgeClass(confidence: ChatQueryResponse["confidence_category"]): string {
  if (confidence === "high") {
    return "rounded-full bg-emerald-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-emerald-800";
  }
  if (confidence === "medium") {
    return "rounded-full bg-amber-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-amber-800";
  }
  return "rounded-full bg-rose-100 px-2 py-1 text-xs font-bold uppercase tracking-wide text-rose-800";
}

function activeThreadKey(sessionId: string | null): string {
  return sessionId ?? DRAFT_SESSION_KEY;
}

function toTurnResponseFromQuery(response: ChatQueryResponse): ChatTurn["response"] {
  return {
    message_id: response.message_id,
    answer: response.answer,
    confidence_score: response.confidence_score,
    confidence_category: response.confidence_category,
    citations: response.citations,
    created_at: response.created_at,
  };
}

function toTurnResponseFromHistoryMessage(message: ChatSessionMessageResponse): ChatTurn["response"] {
  return {
    message_id: message.message_id,
    answer: message.content,
    confidence_score: typeof message.confidence_score === "number" ? message.confidence_score : 0,
    confidence_category: message.confidence_category ?? "low",
    citations: message.citations,
    created_at: message.created_at,
  };
}

function buildTurnsFromSessionMessages(messages: ChatSessionMessageResponse[]): ChatTurn[] {
  const turns: ChatTurn[] = [];
  let lastUserQuestion: string | null = null;

  for (const message of messages) {
    if (message.role === "user") {
      lastUserQuestion = message.content;
      continue;
    }
    if (message.role !== "assistant") {
      continue;
    }

    turns.push({
      question: lastUserQuestion ?? "Question unavailable.",
      response: toTurnResponseFromHistoryMessage(message),
    });
    lastUserQuestion = null;
  }

  return turns;
}

function CitationPanel({ citations }: { citations: ChatCitationResponse[] }) {
  if (citations.length === 0) {
    return (
      <p className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] px-3 py-2 text-xs text-[#68647b]">
        No citations were returned for this answer.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {citations.map((citation) => (
        <li
          key={`${citation.document_id}:${citation.chunk_id}`}
          className="rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3"
        >
          <p className="text-xs font-semibold text-[#3f3b58]">
            {citation.filename ?? "Unknown document"}
            {citation.page_number ? ` • page ${citation.page_number}` : ""}
          </p>
          <p className="mt-1 text-xs text-[#5f5a74]">
            Similarity: {formatScore(citation.similarity_score)}
            {" • "}
            Rerank: {formatScore(citation.rerank_score)}
            {" • "}
            Score: {formatScore(citation.score)}
          </p>
          <p className="mt-2 text-sm text-[#2f2a46]">{citation.text_snippet ?? "Snippet unavailable."}</p>
        </li>
      ))}
    </ul>
  );
}

export function ChatPage() {
  const queryClient = useQueryClient();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const [topK, setTopK] = useState(DEFAULT_TOP_K);
  const [rerank, setRerank] = useState(true);
  const [threadsBySession, setThreadsBySession] = useState<Record<string, ChatTurn[]>>({});
  const [pendingQuestion, setPendingQuestion] = useState<string | null>(null);
  const [submitRequestId, setSubmitRequestId] = useState<string | null>(null);

  const sessionsQuery = useQuery({
    queryKey: queryKeys.chat.sessions,
    queryFn: () =>
      listChatSessions({
        limit: SESSION_LIST_LIMIT,
        offset: 0,
      }),
  });

  const shouldLoadActiveSessionHistory =
    activeSessionId !== null && (threadsBySession[activeThreadKey(activeSessionId)] ?? []).length === 0;

  const sessionMessagesQuery = useQuery({
    queryKey: queryKeys.chat.sessionMessages(activeSessionId ?? ""),
    queryFn: () =>
      listChatSessionMessages(activeSessionId ?? "", {
        limit: 500,
        offset: 0,
      }),
    enabled: shouldLoadActiveSessionHistory,
  });

  useEffect(() => {
    if (!activeSessionId || !sessionMessagesQuery.data) {
      return;
    }

    const threadKey = activeThreadKey(activeSessionId);
    const hydratedTurns = buildTurnsFromSessionMessages(sessionMessagesQuery.data.items);
    setThreadsBySession((previous) => {
      const existing = previous[threadKey];
      if (existing && existing.length > 0) {
        return previous;
      }
      return {
        ...previous,
        [threadKey]: hydratedTurns,
      };
    });
  }, [activeSessionId, sessionMessagesQuery.data]);

  const indexedDocumentsQuery = useQuery({
    queryKey: queryKeys.documents.list({
      status: "indexed",
      limit: MAX_INDEXED_DOCS,
      offset: 0,
      sort_by: "updated_at",
      sort_order: "desc",
    }),
    queryFn: () =>
      listDocuments({
        status: "indexed",
        limit: MAX_INDEXED_DOCS,
        offset: 0,
        sort_by: "updated_at",
        sort_order: "desc",
      }),
  });

  const indexedDocuments = useMemo(
    () => indexedDocumentsQuery.data?.items.filter((item) => item.status === "indexed") ?? [],
    [indexedDocumentsQuery.data?.items],
  );

  const indexedDocumentIdSet = useMemo(
    () => new Set(indexedDocuments.map((item) => item.document_id)),
    [indexedDocuments],
  );

  const filteredSelectedDocumentIds = useMemo(
    () => selectedDocumentIds.filter((documentId) => indexedDocumentIdSet.has(documentId)),
    [selectedDocumentIds, indexedDocumentIdSet],
  );

  const activeSession = sessionsQuery.data?.items.find((item) => item.session_id === activeSessionId) ?? null;
  const thread = threadsBySession[activeThreadKey(activeSessionId)] ?? [];

  const queryMutation = useMutation({
    mutationFn: (payload: ChatQueryRequest) => queryChat(payload),
    onSuccess: async (response, payload) => {
      const nextSessionId = response.chat_session_id;
      const previousThreadKey = activeThreadKey(payload.chat_session_id ?? null);
      const nextTurn: ChatTurn = {
        question: payload.question,
        response: toTurnResponseFromQuery(response),
      };

      setThreadsBySession((previous) => {
        const sourceThread = previous[previousThreadKey] ?? [];
        const merged = [...sourceThread, nextTurn];
        const next = { ...previous, [nextSessionId]: merged };
        if (previousThreadKey !== nextSessionId) {
          delete next[previousThreadKey];
        }
        return next;
      });

      setActiveSessionId(nextSessionId);
      setSubmitRequestId(null);
      setPendingQuestion(null);
      await invalidateAfterMutation(queryClient, "chat.query");
    },
    onError: (error) => {
      setSubmitRequestId(extractRequestIdFromError(error));
      setPendingQuestion(null);
    },
  });

  const listForbidden = isForbiddenError(indexedDocumentsQuery.error) || isForbiddenError(sessionsQuery.error);
  const queryForbidden = isForbiddenError(queryMutation.error);

  function toggleDocument(documentId: string) {
    setSelectedDocumentIds((previous) => {
      const validPrevious = previous.filter((value) => indexedDocumentIdSet.has(value));
      if (validPrevious.includes(documentId)) {
        return validPrevious.filter((value) => value !== documentId);
      }
      return [...validPrevious, documentId];
    });
  }

  function resetForNewChat() {
    setActiveSessionId(null);
    setQuestion("");
    setPendingQuestion(null);
    setSubmitRequestId(null);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || queryMutation.isPending) {
      return;
    }

    setSubmitRequestId(null);
    setPendingQuestion(trimmedQuestion);
    setQuestion("");

    queryMutation.mutate({
      question: trimmedQuestion,
      chat_session_id: activeSessionId,
      document_ids:
        filteredSelectedDocumentIds.length > 0
          ? filteredSelectedDocumentIds
          : undefined,
      top_k: topK,
      rerank,
    });
  }

  if (listForbidden) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Chat access is restricted"
          description="Your role does not have permission to query documents in this organization."
          requestId={extractRequestIdFromError(indexedDocumentsQuery.error ?? sessionsQuery.error)}
          compact={false}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="mb-1 text-xs font-bold uppercase tracking-[0.18em] text-[#5d58a8]">Rudix Chat</p>
            <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">Document-grounded Q&A</h1>
            <p className="max-w-3xl text-sm text-[#68647b]">
              Ask questions against indexed documents with configurable retrieval and rerank settings.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/documents"
              className="rounded-lg border border-[#d2cee6] px-3 py-2 text-sm font-semibold text-[#3525cd] hover:bg-[#f5f3ff]"
            >
              Upload documents
            </Link>
            <button
              type="button"
              onClick={resetForNewChat}
              className="rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
            >
              New chat
            </button>
          </div>
        </div>
      </header>

      <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
        <aside className="space-y-4">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Sessions</h2>
            {sessionsQuery.isLoading ? (
              <p className="text-sm text-[#68647b]">Loading sessions...</p>
            ) : sessionsQuery.isError ? (
              <p className="text-sm text-rose-700">{getApiErrorMessage(sessionsQuery.error)}</p>
            ) : sessionsQuery.data?.items.length ? (
              <ul className="space-y-2">
                {sessionsQuery.data.items.map((session) => (
                  <li key={session.session_id}>
                    <button
                      type="button"
                      onClick={() => setActiveSessionId(session.session_id)}
                      className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                        session.session_id === activeSessionId
                          ? "border-[#3525cd] bg-[#f4f2ff] text-[#2f2a46]"
                          : "border-[#e4e1f2] bg-white text-[#4f4b63] hover:bg-[#faf9ff]"
                      }`}
                    >
                      <p className="font-semibold">{session.title ?? "Untitled session"}</p>
                      <p className="mt-1 text-xs">
                        {session.message_count} messages • updated {formatDate(session.updated_at)}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-[#68647b]">No sessions yet. Ask your first question to start one.</p>
            )}
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Retrieval settings</h2>
            <label className="mb-3 grid gap-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
              Top K
              <input
                type="number"
                min={MIN_TOP_K}
                max={MAX_TOP_K}
                value={topK}
                onChange={(event) => {
                  const parsed = Number.parseInt(event.target.value, 10);
                  if (!Number.isFinite(parsed)) {
                    return;
                  }
                  setTopK(Math.min(MAX_TOP_K, Math.max(MIN_TOP_K, parsed)));
                }}
                className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
              />
            </label>

            <label className="flex items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46]">
              <input
                type="checkbox"
                checked={rerank}
                onChange={(event) => setRerank(event.target.checked)}
                className="mt-0.5"
              />
              <span>
                Enable rerank
                <span className="mt-1 block text-xs text-[#6a6780]">
                  Improves answer quality with an additional ranking pass.
                </span>
              </span>
            </label>
          </section>

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Document selector</h2>
            {indexedDocumentsQuery.isLoading ? (
              <p className="text-sm text-[#68647b]">Loading indexed documents...</p>
            ) : indexedDocumentsQuery.isError ? (
              <p className="text-sm text-rose-700">{getApiErrorMessage(indexedDocumentsQuery.error)}</p>
            ) : indexedDocuments.length === 0 ? (
              <p className="text-sm text-[#68647b]">
                No indexed documents available. Upload and index documents first.
              </p>
            ) : (
              <ul className="max-h-72 space-y-2 overflow-auto pr-1">
                {indexedDocuments.map((document) => (
                  <DocumentSelectorItem
                    key={document.document_id}
                    document={document}
                    checked={filteredSelectedDocumentIds.includes(document.document_id)}
                    onToggle={() => toggleDocument(document.document_id)}
                  />
                ))}
              </ul>
            )}
          </section>
        </aside>

        <section className="space-y-4">
          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Ask a question</h2>
            <form onSubmit={handleSubmit} className="space-y-3">
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                rows={4}
                placeholder="Ask a question about your selected documents..."
                className="w-full rounded-lg border border-[#d2cee6] px-3 py-2 text-sm text-[#2f2a46] outline-none ring-[#3525cd]/20 focus:ring"
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs text-[#6a6780]">
                  {filteredSelectedDocumentIds.length > 0
                    ? `${filteredSelectedDocumentIds.length} document(s) selected`
                    : "All indexed accessible documents are in scope"}
                </p>
                <button
                  type="submit"
                  disabled={queryMutation.isPending || question.trim().length === 0}
                  className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {queryMutation.isPending ? "Generating answer..." : "Ask"}
                </button>
              </div>
            </form>
          </section>

          {queryForbidden ? (
            <ForbiddenState
              compact
              title="Query is not allowed"
              description="You do not have permission to query the selected documents in this organization."
              requestId={extractRequestIdFromError(queryMutation.error)}
            />
          ) : null}

          {queryMutation.isError && !queryForbidden ? (
            <section className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
              <p className="font-semibold">Unable to complete the query.</p>
              <p className="mt-1">{getApiErrorMessage(queryMutation.error)}</p>
              {submitRequestId ? (
                <p className="mt-1 text-xs">Trace ID: {submitRequestId}</p>
              ) : null}
            </section>
          ) : null}

          <section className="rounded-2xl border border-[#d7d4e8] bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-[#5f5a74]">Conversation</h2>
            {sessionMessagesQuery.isLoading && activeSession && thread.length === 0 && activeSession.message_count > 0 ? (
              <p className="text-sm text-[#68647b]">Loading session history...</p>
            ) : null}

            {sessionMessagesQuery.isError && activeSession && thread.length === 0 && activeSession.message_count > 0 ? (
              <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800">
                Unable to load prior messages: {getApiErrorMessage(sessionMessagesQuery.error)}
              </p>
            ) : null}

            {thread.length === 0 && !pendingQuestion && !sessionMessagesQuery.isLoading ? (
              <p className="text-sm text-[#68647b]">
                No messages yet. Submit a question to start the conversation.
              </p>
            ) : (
              <ul className="space-y-4">
                {thread.map((turn) => (
                  <li key={turn.response.message_id} className="space-y-2">
                    <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Question</p>
                      <p className="text-sm text-[#2f2a46]">{turn.question}</p>
                    </article>

                    <article className="rounded-xl border border-[#d7d4e8] bg-white p-3">
                      <div className="mb-2 flex flex-wrap items-center gap-2">
                        <p className="text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Answer</p>
                        <span className={confidenceBadgeClass(turn.response.confidence_category)}>
                          Confidence {formatPercent(turn.response.confidence_score)}
                        </span>
                        <span className="text-xs text-[#6a6780]">{formatDate(turn.response.created_at)}</span>
                      </div>

                      {turn.response.confidence_category === "low" ? (
                        <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                          Low confidence warning: validate this answer against the cited source text.
                        </p>
                      ) : null}

                      <p className="text-sm whitespace-pre-wrap text-[#2f2a46]">{turn.response.answer}</p>

                      <div className="mt-3">
                        <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">
                          Citations
                        </h3>
                        <CitationPanel citations={turn.response.citations} />
                      </div>
                    </article>
                  </li>
                ))}
                {pendingQuestion ? (
                  <li className="space-y-2">
                    <article className="rounded-xl border border-[#e4e1f2] bg-[#faf9ff] p-3">
                      <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#6a6780]">Question</p>
                      <p className="text-sm text-[#2f2a46]">{pendingQuestion}</p>
                    </article>
                    <article className="rounded-xl border border-[#d7d4e8] bg-white p-3">
                      <p className="text-sm text-[#68647b]">Generating answer...</p>
                    </article>
                  </li>
                ) : null}
              </ul>
            )}
          </section>
        </section>
      </div>
    </section>
  );
}

function DocumentSelectorItem({
  document,
  checked,
  onToggle,
}: {
  document: DocumentListItemResponse;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <li>
      <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-[#e4e1f2] bg-[#faf9ff] p-3 text-sm text-[#2f2a46]">
        <input type="checkbox" checked={checked} onChange={onToggle} className="mt-0.5" />
        <span>
          <span className="block font-semibold">{document.filename}</span>
          <span className="mt-1 block text-xs text-[#6a6780]">
            {document.chunk_count} chunks • updated {formatDate(document.updated_at)}
          </span>
        </span>
      </label>
    </li>
  );
}
