import { ForbiddenState } from "@/components/states/ForbiddenState";
import { sanitizeRequestId } from "@/lib/forbidden";
import { setRequestLocaleFromParams } from "@/i18n/request-locale";

type ForbiddenPageProps = {
  params?: Promise<{ locale: string }>;
  searchParams?: Promise<{ from?: string; rid?: string; request_id?: string }>;
};

// Reads searchParams, so this page renders per request (not prerendered).
export default async function ForbiddenPage({
  params,
  searchParams,
}: ForbiddenPageProps) {
  await setRequestLocaleFromParams(params);
  const resolvedSearchParams = (await searchParams) ?? {};
  const requestId = sanitizeRequestId(
    resolvedSearchParams.rid ?? resolvedSearchParams.request_id ?? null,
  );

  return (
    <div
      data-public-theme="system"
      className="rudix-public bg-site-canvas text-site-ink flex min-h-screen items-center justify-center bg-[radial-gradient(60%_45%_at_50%_0%,var(--site-accent-soft),transparent)] px-6"
    >
      <main className="w-full max-w-xl">
        <ForbiddenState
          title="Forbidden"
          description="Your account does not currently have permission to view this resource."
          requestId={requestId}
          backHref="/dashboard"
          backLabel="Back to dashboard"
          eyebrow="Rudix Access Control"
          ariaLabel="Forbidden state"
          traceIdLabel="Trace ID:"
        />
      </main>
    </div>
  );
}
