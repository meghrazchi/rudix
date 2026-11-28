"use client";

import { type ServiceAccountTokenCreated } from "@/lib/api/service-accounts";
import { CopyButton } from "@/components/admin/service-accounts/svcShared";

export function CreatedTokenBanner({
  result,
  onClose,
}: {
  result: ServiceAccountTokenCreated;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="created-token-title"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
        <h3
          id="created-token-title"
          className="mb-1 text-base font-semibold text-[#2a2640]"
        >
          Token created — copy it now
        </h3>
        <p className="mb-4 text-sm text-[#68647b]">
          This is the only time the full token is shown. Store it somewhere
          safe.
        </p>
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-[#d7d4e8] bg-[#f9f8ff] px-3 py-2">
          <code className="flex-1 font-mono text-sm break-all text-[#2a2640]">
            {result.raw_token}
          </code>
          <CopyButton value={result.raw_token} />
        </div>
        <div className="mb-4 text-sm text-[#68647b]">
          <span className="font-medium text-[#2a2640]">Prefix:</span>{" "}
          <code className="font-mono">{result.token_prefix}</code>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
        >
          Done
        </button>
      </div>
    </div>
  );
}
