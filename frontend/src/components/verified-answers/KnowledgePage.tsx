"use client";

import { useState } from "react";
import { usePermissions } from "@/lib/use-permissions";
import { KnowledgeCardList } from "@/components/verified-answers/KnowledgeCardList";
import { CreateVerifiedAnswerModal } from "@/components/verified-answers/CreateVerifiedAnswerModal";

export function KnowledgePage() {
  const { hasAnyPermission } = usePermissions();
  const [showCreate, setShowCreate] = useState(false);

  const canCreate = hasAnyPermission(
    "knowledge_card:create",
    "knowledge_card:manage",
  );

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            Knowledge base
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Verified answers curated by your team — always surfaced above
            generated results when relevant.
          </p>
        </div>
        {canCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            + New card
          </button>
        )}
      </div>

      <KnowledgeCardList defaultStatus="published" showStatusFilter={false} />

      {showCreate && (
        <CreateVerifiedAnswerModal
          mode={{ kind: "manual" }}
          onClose={() => setShowCreate(false)}
          invalidateKey={["verified-answers"]}
        />
      )}
    </div>
  );
}
