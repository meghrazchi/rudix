import { ForbiddenState } from "@/components/states/ForbiddenState";
import { sanitizeRequestId } from "@/lib/forbidden";

type ForbiddenPageProps = {
  searchParams?: Promise<{ from?: string; rid?: string; request_id?: string }>;
};

export default async function ForbiddenPage({ searchParams }: ForbiddenPageProps) {
  const resolvedSearchParams = (await searchParams) ?? {};
  const requestId = sanitizeRequestId(
    resolvedSearchParams.rid ?? resolvedSearchParams.request_id ?? null,
  );

  return (
    <div
      className="flex min-h-screen items-center justify-center bg-[#f5f4ff] px-6"
      style={{ fontFamily: "Inter, system-ui, sans-serif" }}
    >
      <main className="w-full max-w-xl">
        <ForbiddenState
          title="Forbidden"
          description="Your account does not currently have permission to view this resource."
          requestId={requestId}
          backHref="/dashboard"
          backLabel="Back to dashboard"
        />
      </main>
    </div>
  );
}
