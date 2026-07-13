import { Suspense } from "react";
import { ReportsShell } from "@/components/reports/ReportsShell";
import { LoadingState } from "@/components/states/LoadingState";

export default function ReportsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <Suspense fallback={<LoadingState title="Loading reports" />}>
      <ReportsShell>{children}</ReportsShell>
    </Suspense>
  );
}
