import { useTranslations } from "next-intl";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { OnboardingCtaBanner } from "@/components/onboarding/OnboardingCtaBanner";
import { replaceSessionParamInUrl } from "@/components/chat/chat-session-utils";
import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";
import { getApiErrorMessage } from "@/lib/api/errors";

export function ChatSidebar({ session }: { session: ChatSessionController }) {
  const tc = useTranslations("chat.page");
  const {
    resetForNewChat,
    sessionSearchQuery,
    setSessionSearchQuery,
    sessionsQuery,
    sessions,
    activeSessionId,
    sessionDisplayTitleById,
    openSessionMenuId,
    editingSessionId,
    editSessionInputRef,
    editingSessionTitle,
    setEditingSessionTitle,
    handleRenameSave,
    handleRenameCancel,
    updateSessionMutation,
    setActiveSessionId,
    setSubmitRequestId,
    setPendingQuestion,
    sessionMenuRef,
    setOpenSessionMenuId,
    handleRenameRequest,
    handleDeleteRequest,
    totalSessions,
    debouncedSearchQuery,
  } = session;

  return (
    <aside className="rudix-chat-scrollbar hidden min-h-0 overflow-y-auto border-r border-[#e4e1ee] bg-[#fcf8ff] p-4 xl:block">
      <section className="rounded-3xl border border-[#e4e1ee] bg-white p-4 shadow-sm">
        <button
          type="button"
          onClick={resetForNewChat}
          className="mb-3 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-[#3525cd]/15 transition-all hover:-translate-y-0.5 hover:bg-[#2b1fa8]"
        >
          <span
            className="material-symbols-outlined text-[18px]"
            aria-hidden="true"
          >
            add
          </span>
          {tc("newChat")}
        </button>
        <div className="mb-3">
          <div className="relative">
            <span
              className="material-symbols-outlined pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-[18px] text-[#6a6780]"
              aria-hidden="true"
            >
              search
            </span>
            <input
              type="text"
              value={sessionSearchQuery}
              onChange={(e) => setSessionSearchQuery(e.target.value)}
              placeholder={tc("searchPlaceholder")}
              aria-label={tc("searchPlaceholder")}
              className="h-9 w-full rounded-xl border border-[#d6d1ea] bg-[#f7f5ff] pr-3 pl-8 text-xs text-[#2f2a46] ring-[#3525cd]/20 outline-none focus:ring"
            />
          </div>
        </div>
        <h2 className="mb-3 text-[10px] font-bold tracking-widest text-[#777587] uppercase">
          {tc("sessionsTitle")}
        </h2>
        {sessionsQuery.isLoading ? (
          <LoadingState compact title={tc("loadingSessions")} />
        ) : sessionsQuery.isError ? (
          <ErrorState
            compact
            error={sessionsQuery.error}
            description={getApiErrorMessage(sessionsQuery.error)}
            onRetry={() => {
              void sessionsQuery.refetch();
            }}
          />
        ) : sessions.length ? (
          <>
            <ul className="space-y-2">
              {sessions.map((session) => {
                const isActive = session.session_id === activeSessionId;
                const displayTitle =
                  sessionDisplayTitleById.get(session.session_id) ??
                  tc("untitledSession");
                const isSessionMenuOpen =
                  openSessionMenuId === session.session_id;

                return (
                  <li key={session.session_id}>
                    <div
                      className={`group relative cursor-pointer rounded-2xl border transition ${
                        isActive
                          ? "border-[#c3c0ff] bg-[#e2dfff]"
                          : "border-[#e4e1ee] bg-white hover:bg-[#f5f2ff]"
                      }`}
                    >
                      {editingSessionId === session.session_id ? (
                        <div className="flex items-center gap-2 px-3 py-2 pr-2 text-sm">
                          <input
                            ref={editSessionInputRef}
                            type="text"
                            value={editingSessionTitle}
                            onChange={(event) =>
                              setEditingSessionTitle(event.target.value)
                            }
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                handleRenameSave(session.session_id);
                              }
                              if (event.key === "Escape") {
                                event.preventDefault();
                                handleRenameCancel();
                              }
                            }}
                            aria-label={tc("sessionTitleLabel")}
                            className="h-9 min-w-0 flex-1 rounded-xl border border-[#cfc9e6] bg-white px-3 text-sm text-[#2f2a46] ring-[#3525cd]/20 outline-none focus:ring"
                          />
                          <button
                            type="button"
                            aria-label={tc("cancelRename")}
                            onClick={handleRenameCancel}
                            className="flex h-7 w-7 items-center justify-center rounded-lg border border-[#d7d4e8] bg-white text-[#6a6780] transition hover:bg-[#f5f2ff] hover:text-[#3525cd]"
                          >
                            <span
                              className="material-symbols-outlined text-[2px]"
                              aria-hidden="true"
                            >
                              close
                            </span>
                          </button>
                          <button
                            type="button"
                            aria-label={tc("saveRename")}
                            onClick={() => handleRenameSave(session.session_id)}
                            disabled={updateSessionMutation.isPending}
                            className="flex h-7 w-7 items-center justify-center rounded-lg border border-[#d2cee6] bg-[#3525cd] text-white transition hover:bg-[#2c1fb1] disabled:cursor-not-allowed disabled:opacity-60"
                          >
                            {updateSessionMutation.isPending ? (
                              <span
                                className="material-symbols-outlined text-[2px]"
                                aria-hidden="true"
                              >
                                progress_activity
                              </span>
                            ) : (
                              <span
                                className="material-symbols-outlined text-[2px]"
                                aria-hidden="true"
                              >
                                check
                              </span>
                            )}
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          onClick={() => {
                            setActiveSessionId(session.session_id);
                            setSubmitRequestId(null);
                            setPendingQuestion(null);
                            replaceSessionParamInUrl(session.session_id);
                          }}
                          className="w-full cursor-pointer px-3 py-2 pe-10 text-start text-sm"
                        >
                          <p
                            className={`truncate font-semibold ${isActive ? "text-[#2f2a46]" : "text-[#4f4b63]"}`}
                          >
                            {displayTitle}
                          </p>
                        </button>
                      )}
                      {editingSessionId === session.session_id ? null : (
                        <div
                          ref={isSessionMenuOpen ? sessionMenuRef : null}
                          className="absolute end-1 top-1 flex items-start gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100"
                          onMouseDown={(e) => e.stopPropagation()}
                        >
                          <button
                            type="button"
                            aria-label={tc("sessionActions")}
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenSessionMenuId((current) =>
                                current === session.session_id
                                  ? null
                                  : session.session_id,
                              );
                            }}
                            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-lg text-[#6a6780] hover:bg-white hover:text-[#3525cd]"
                          >
                            <span
                              className="material-symbols-outlined text-[18px]"
                              aria-hidden="true"
                            >
                              more_vert
                            </span>
                          </button>
                          {isSessionMenuOpen ? (
                            <div className="absolute end-0 top-8 z-20 w-44 overflow-hidden rounded-2xl border border-[#d7d4e8] bg-white shadow-lg">
                              <button
                                type="button"
                                role="menuitem"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  handleRenameRequest(
                                    session.session_id,
                                    session.title ?? null,
                                  );
                                }}
                                className="flex w-full items-center gap-2 px-3 py-2.5 text-start text-sm text-[#3e376f] hover:bg-[#f5f2ff]"
                              >
                                <span
                                  className="material-symbols-outlined text-[16px]"
                                  aria-hidden="true"
                                >
                                  edit
                                </span>
                                {tc("renameSession")}
                              </button>
                              <button
                                type="button"
                                role="menuitem"
                                className="flex w-full items-center gap-2 px-3 py-2.5 text-start text-sm text-rose-700 hover:bg-rose-50"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setOpenSessionMenuId(null);
                                  handleDeleteRequest(session.session_id);
                                }}
                              >
                                <span
                                  className="material-symbols-outlined text-[16px]"
                                  aria-hidden="true"
                                >
                                  delete
                                </span>
                                {tc("deleteSession")}
                              </button>
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
            {sessionsQuery.hasNextPage ? (
              <button
                type="button"
                onClick={() => {
                  void sessionsQuery.fetchNextPage();
                }}
                disabled={sessionsQuery.isFetchingNextPage}
                className="mt-3 w-full rounded-xl border border-[#cbc5e6] px-3 py-2 text-xs font-semibold text-[#3e376f] hover:bg-[#f5f3ff] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {sessionsQuery.isFetchingNextPage
                  ? tc("loadingMore")
                  : tc("loadMore", {
                      loaded: sessions.length,
                      total: totalSessions,
                    })}
              </button>
            ) : null}
          </>
        ) : (
          <>
            <EmptyState
              compact
              title={
                debouncedSearchQuery
                  ? tc("noSessionsSearch", {
                      query: debouncedSearchQuery,
                    })
                  : tc("noSessionsYet")
              }
            />
            {!debouncedSearchQuery ? (
              <div className="mt-3 px-1">
                <OnboardingCtaBanner
                  title={tc("onboardingTitle")}
                  description={tc("onboardingDescription")}
                  actionLabel={tc("onboardingAction")}
                  actionHref="/documents"
                />
              </div>
            ) : null}
          </>
        )}
      </section>
    </aside>
  );
}
