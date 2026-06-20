import { AbTestPanel } from "@/components/evaluations/ab-test-panel";

export default function AbTestsPage() {
  return (
    <div className="mx-auto max-w-7xl p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">A/B Testing</h1>
        <p className="mt-1 text-sm text-gray-500">
          Compare prompt versions, retrieval profiles, and model settings on
          fixed evaluation datasets. Approve the best-performing variant to
          promote it as the org default.
        </p>
      </div>
      <AbTestPanel />
    </div>
  );
}
