"use client";

import dynamic from "next/dynamic";

import { SkeletonBlock } from "@/components/states/SkeletonBlock";

/** Loads recharts on demand; the placeholder has the chart's height. */
export const HorizontalBarChart = dynamic(
  () =>
    import("@/components/admin/AdminBarCharts").then(
      (module) => module.HorizontalBarChart,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="h-52 w-full">
        <SkeletonBlock rows={6} className="h-full" />
      </div>
    ),
  },
);
