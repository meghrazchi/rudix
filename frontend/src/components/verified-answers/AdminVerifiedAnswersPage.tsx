"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { KnowledgeCardList } from "@/components/verified-answers/KnowledgeCardList";
import { CreateVerifiedAnswerModal } from "@/components/verified-answers/CreateVerifiedAnswerModal";
import { VerifiedAnswerBadge } from "@/components/verified-answers/VerifiedAnswerBadge";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { listVerifiedAnswers } from "@/lib/api/verified-answers";
import { usePermissions } from "@/lib/use-permissions";

const PENDING_KEY = ["verified-answers", { status: "pending_review" }];
const DEPRECATED_KEY = ["verified-answers", { status: "deprecated" }];

type Tab = "pending" | "all" | "stale" | "deprecated";

export function AdminVerifiedAnswersPage() {
  const { hasPermission } = usePermissions();
  const [activeTab, setActiveTab] = useState<Tab>("pending");
  const [showCreate, setShowCreate] = useState(false);

  const { data: pendingData } = useQuery({
    queryKey: PENDING_KEY,
    queryFn: () =>
      listVerifiedAnswers({ status: "pending_review", limit: 100 }),
  });

  const { data: deprecatedData } = useQuery({
    queryKey: DEPRECATED_KEY,
    queryFn: () => listVerifiedAnswers({ status: "deprecated", limit: 100 }),
  });

  if (!hasPermission("knowledge_card:manage")) {
    return <ForbiddenState />;
  }

  const pendingCount = pendingData?.total ?? 0;
  const deprecatedCount = deprecatedData?.total ?? 0;

  const tabs: { id: Tab; label: string; count?: number }[] = [
    { id: "pending", label: "Needs review", count: pendingCount },
    { id: "all", label: "All cards" },
    { id: "stale", label: "Stale / expiring" },
    {
      id: "deprecated",
      label: "Deprecated",
      count: deprecatedCount > 0 ? deprecatedCount : undefined,
    },
  ];

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            Knowledge cards
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage verified answers that are surfaced above generated results.
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          + New card
        </button>
      </div>

      <div className="mb-6 border-b border-gray-200">
        <nav className="-mb-px flex gap-6" role="tablist">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-1.5 border-b-2 pb-3 text-sm font-medium transition-colors ${
                activeTab === tab.id
                  ? "border-indigo-600 text-indigo-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
              {tab.count !== undefined && tab.count > 0 && (
                <span className="rounded-full bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === "pending" && (
        <KnowledgeCardList
          defaultStatus="pending_review"
          showStatusFilter={false}
        />
      )}
      {activeTab === "all" && <KnowledgeCardList showStatusFilter />}
      {activeTab === "stale" && <StaleCardsPanel />}
      {activeTab === "deprecated" && (
        <KnowledgeCardList
          defaultStatus="deprecated"
          showStatusFilter={false}
        />
      )}

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

function StaleCardsPanel() {
  const { data, isLoading } = useQuery({
    queryKey: ["verified-answers", "published-all"],
    queryFn: () => listVerifiedAnswers({ status: "published", limit: 200 }),
  });

  const staleItems = data?.items.filter((a) => a.is_stale) ?? [];

  if (isLoading) {
    return <p className="text-sm text-gray-400">Loading…</p>;
  }

  if (staleItems.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-gray-300 py-16 text-center text-sm text-gray-400">
        No stale or expiring knowledge cards
      </div>
    );
  }

  return (
    <div>
      <p className="mb-4 text-sm text-amber-700">
        {staleItems.length} verified card
        {staleItems.length !== 1 ? "s are" : " is"} past their review or expiry
        date.
      </p>
      <div className="space-y-4">
        {staleItems.map((answer) => (
          <div
            key={answer.answer_id}
            className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 p-4"
          >
            <div>
              <div className="flex items-center gap-2">
                <VerifiedAnswerBadge status={answer.status} isStale />
                <span className="text-sm font-medium text-gray-800">
                  {answer.title}
                </span>
              </div>
              <p className="mt-0.5 text-xs text-gray-500">
                {answer.expiry_date && (
                  <span>Expires: {answer.expiry_date} · </span>
                )}
                {answer.review_date && (
                  <span>Review due: {answer.review_date}</span>
                )}
              </p>
            </div>
            <Link
              href={`/admin/verified-answers/${answer.answer_id}`}
              className="text-xs font-medium text-indigo-600 hover:underline"
            >
              Review →
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
