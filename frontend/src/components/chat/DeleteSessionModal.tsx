import { useTranslations } from "next-intl";

import type { ChatSessionController } from "@/components/chat/hooks/useChatSession";

export function DeleteSessionModal({
  session,
}: {
  session: ChatSessionController;
}) {
  const tc = useTranslations("chat.page");
  const {
    deleteSessionCandidate,
    deleteSessionOverlayRef,
    deleteSessionModalRef,
    handleDeleteCancel,
    handleDeleteConfirm,
    sessionDisplayTitleById,
    deleteSessionMutation,
  } = session;

  if (!deleteSessionCandidate) {
    return null;
  }

  return (
    <div
      ref={deleteSessionOverlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#171428]/50 p-4 backdrop-blur-[2px]"
      onClick={(event) => {
        if (event.target === deleteSessionOverlayRef.current) {
          handleDeleteCancel();
        }
      }}
    >
      <div
        ref={deleteSessionModalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="delete-session-modal-title"
        className="w-full max-w-md overflow-hidden rounded-[24px] border border-[#d7d4e8] bg-white shadow-[0_25px_70px_rgba(15,10,40,0.28)]"
      >
        <div className="flex items-start gap-3 border-b border-[#e4e1ee] px-5 py-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-rose-50 text-rose-600">
            <span
              className="material-symbols-outlined text-[20px]"
              aria-hidden="true"
            >
              delete
            </span>
          </span>
          <div className="min-w-0">
            <h2
              id="delete-session-modal-title"
              className="text-base font-semibold text-[#1b1b24]"
            >
              {tc("deleteConfirmTitle")}
            </h2>
            <p className="mt-1 truncate text-sm text-[#6a6780]">
              {sessionDisplayTitleById.get(deleteSessionCandidate.session_id) ??
                tc("untitledSession")}
            </p>
          </div>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm leading-relaxed text-[#4f4b63]">
            {tc("deleteSessionBody")}
          </p>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-[#e4e1ee] bg-[#faf9ff] px-5 py-4">
          <button
            type="button"
            onClick={handleDeleteCancel}
            className="rounded-xl border border-[#d7d4e8] bg-white px-4 py-2 text-sm font-semibold text-[#4f4b63] hover:bg-[#f5f2ff]"
          >
            {tc("cancel")}
          </button>
          <button
            type="button"
            onClick={() =>
              handleDeleteConfirm(deleteSessionCandidate.session_id)
            }
            disabled={deleteSessionMutation.isPending}
            className="rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {deleteSessionMutation.isPending ? tc("deleting") : tc("delete")}
          </button>
        </div>
      </div>
    </div>
  );
}
