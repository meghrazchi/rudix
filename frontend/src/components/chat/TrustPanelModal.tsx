"use client";

import type { ComponentProps } from "react";

import dynamic from "next/dynamic";

import { SkeletonBlock } from "@/components/states/SkeletonBlock";
import type { TrustPanelModalContent } from "@/components/chat/TrustPanelModalContent";

type TrustPanelModalProps = ComponentProps<typeof TrustPanelModalContent>;

/** "Explain answer" dialog; the implementation loads when first opened (R07-03). */
export const TrustPanelModal = dynamic<TrustPanelModalProps>(
  () =>
    import("@/components/chat/TrustPanelModalContent").then(
      (module) => module.TrustPanelModalContent,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#171428]/60 p-6 backdrop-blur-[2px] md:p-8">
        <div className="w-full max-w-5xl rounded-[28px] border border-[#d7d4e8] bg-[#fcf8ff] p-6">
          <SkeletonBlock rows={6} />
        </div>
      </div>
    ),
  },
);
