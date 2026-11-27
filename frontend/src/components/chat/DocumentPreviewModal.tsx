"use client";

import type { ComponentProps } from "react";

import dynamic from "next/dynamic";

import { SkeletonBlock } from "@/components/states/SkeletonBlock";
import type { CitationPreviewDrawer as CitationPreviewDrawerContent } from "@/components/chat/DocumentPreviewModalContent";

type CitationPreviewDrawerProps = ComponentProps<
  typeof CitationPreviewDrawerContent
>;

// The implementation (about 1,200 lines) loads on first open (R07-03).
export const CitationPreviewDrawer = dynamic<CitationPreviewDrawerProps>(
  () =>
    import("@/components/chat/DocumentPreviewModalContent").then(
      (module) => module.CitationPreviewDrawer,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="fixed inset-0 z-[60] bg-[#1f1a3f]/50">
        <div className="flex h-full justify-end">
          <aside className="h-full w-full bg-white p-5 sm:max-w-[48rem]">
            <SkeletonBlock rows={6} />
          </aside>
        </div>
      </div>
    ),
  },
);

export const DocumentPreviewModal = CitationPreviewDrawer;
