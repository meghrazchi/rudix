"use client";

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";
import {
  createWebhook,
  deleteWebhook,
  listWebhookDeliveries,
  listWebhooks,
  rotateWebhookSecret,
  testWebhook,
  updateWebhook,
  WEBHOOK_EVENT_LABELS,
  WEBHOOK_EVENT_TYPES,
  type Webhook,
  type WebhookCreated,
  type WebhookDelivery,
} from "@/lib/api/webhooks";
import { getApiErrorMessage } from "@/lib/api/errors";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { queryKeys } from "@/lib/api/query";
import { usePermissions } from "@/lib/use-permissions";

const QUERY_WEBHOOKS = queryKeys.admin.webhooks;

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
      className="rounded bg-[#3525cd] px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-[#2b1fa8]"
    >
      {copied ? "Copied!" : "Copy secret"}
    </button>
  );
}

function CreatedSecretBanner({
  result,
  onClose,
}: {
  result: WebhookCreated;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="webhook-secret-title"
    >
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl">
        <h3
          id="webhook-secret-title"
          className="mb-1 text-base font-semibold text-[#2a2640]"
        >
          Signing secret — copy it now
        </h3>
        <p className="mb-4 text-sm text-[#68647b]">
          This is the only time the full secret is shown. Use it to verify
          webhook signatures on your receiver.
        </p>
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-[#d7d4e8] bg-[#f9f8ff] px-3 py-2">
          <code className="flex-1 font-mono text-sm break-all text-[#2a2640]">
            {result.raw_secret}
          </code>
          <CopyButton value={result.raw_secret} />
        </div>
        <div className="mb-4 text-sm text-[#68647b]">
          <span className="font-medium text-[#2a2640]">Prefix:</span>{" "}
          <code className="font-mono">{result.secret_prefix}…</code>
          <span className="ml-4 font-medium text-[#2a2640]">URL:</span>{" "}
          <span className="break-all">{result.url}</span>
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

function WebhookFormPanel({
  mode,
  existing,
  onClose,
  onSaved,
}: {
  mode: "create" | "edit";
  existing?: Webhook;
  onClose: () => void;
  onSaved: (result?: WebhookCreated) => void;
}) {
  const [name, setName] = useState(existing?.name ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [url, setUrl] = useState(existing?.url ?? "");
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(
    new Set(existing?.event_types ?? []),
  );
  const [status, setStatus] = useState<"active" | "disabled">(
    existing?.status ?? "active",
  );
  const [maxAttempts, setMaxAttempts] = useState(
    existing?.retry_policy.max_attempts ?? 5,
  );
  const [backoffSeconds, setBackoffSeconds] = useState(
    existing?.retry_policy.backoff_seconds ?? 60,
  );
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: () =>
      createWebhook({
        name: name.trim(),
        description: description.trim() || null,
        url: url.trim(),
        event_types: Array.from(selectedEvents),
        retry_policy: {
          max_attempts: maxAttempts,
          backoff_seconds: backoffSeconds,
        },
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: QUERY_WEBHOOKS });
      onSaved(result);
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const updateMutation = useMutation({
    mutationFn: () =>
      updateWebhook(existing!.id, {
        name: name.trim(),
        description: description.trim() || null,
        url: url.trim(),
        event_types: Array.from(selectedEvents),
        status,
        retry_policy: {
          max_attempts: maxAttempts,
          backoff_seconds: backoffSeconds,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_WEBHOOKS });
      onSaved();
    },
    onError: (err) => setError(getApiErrorMessage(err)),
  });

  const isPending = createMutation.isPending || updateMutation.isPending;

  function toggleEvent(type: string, checked: boolean) {
    setSelectedEvents((prev) => {
      const next = new Set(prev);
      if (checked) next.add(type);
      else next.delete(type);
      return next;
    });
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (mode === "create") createMutation.mutate();
    else updateMutation.mutate();
  }

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l border-[#d7d4e8] bg-white shadow-xl">
      <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
        <h2 className="text-lg font-semibold text-[#2a2640]">
          {mode === "create" ? "Create Webhook" : "Edit Webhook"}
        </h2>
        <button
          type="button"
          onClick={onClose}
          className="text-[#68647b] hover:text-[#2a2640]"
          aria-label="Close"
        >
          ✕
        </button>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-1 flex-col overflow-y-auto"
      >
        <div className="flex-1 space-y-5 px-6 py-5">
          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={256}
              required
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="e.g. Document events"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              maxLength={1024}
              className="w-full resize-none rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="Optional description"
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-[#2a2640]">
              Destination URL <span className="text-red-500">*</span>
            </label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              maxLength={2048}
              required
              className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              placeholder="https://your-server.example.com/webhook"
            />
          </div>

          <div>
            <p className="mb-2 text-sm font-medium text-[#2a2640]">
              Events to subscribe
            </p>
            <div className="space-y-2 rounded-lg bg-[#f9f8ff] p-3">
              {WEBHOOK_EVENT_TYPES.map((type) => (
                <label
                  key={type}
                  className="flex cursor-pointer items-center gap-2"
                >
                  <input
                    type="checkbox"
                    className="h-4 w-4 accent-[#3525cd]"
                    checked={selectedEvents.has(type)}
                    onChange={(e) => toggleEvent(type, e.target.checked)}
                  />
                  <span className="text-sm text-[#2a2640]">
                    {WEBHOOK_EVENT_LABELS[type]}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {mode === "edit" && (
            <div>
              <label className="mb-1 block text-sm font-medium text-[#2a2640]">
                Status
              </label>
              <select
                value={status}
                onChange={(e) =>
                  setStatus(e.target.value as "active" | "disabled")
                }
                className="w-full rounded-lg border border-[#d7d4e8] px-3 py-2 text-sm focus:border-[#3525cd] focus:outline-none"
              >
                <option value="active">Active</option>
                <option value="disabled">Disabled</option>
              </select>
            </div>
          )}

          <details className="rounded-lg border border-[#d7d4e8]">
            <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-[#2a2640]">
              Retry policy
            </summary>
            <div className="space-y-3 px-3 pt-1 pb-3">
              <div>
                <label className="mb-1 block text-xs text-[#68647b]">
                  Max attempts (1–10)
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={maxAttempts}
                  onChange={(e) => setMaxAttempts(Number(e.target.value))}
                  className="w-full rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-[#68647b]">
                  Backoff seconds (1–3600)
                </label>
                <input
                  type="number"
                  min={1}
                  max={3600}
                  value={backoffSeconds}
                  onChange={(e) => setBackoffSeconds(Number(e.target.value))}
                  className="w-full rounded-lg border border-[#d7d4e8] px-3 py-1.5 text-sm focus:border-[#3525cd] focus:outline-none"
                />
              </div>
            </div>
          </details>
        </div>

        {error && (
          <p className="mx-6 mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <div className="flex gap-3 border-t border-[#d7d4e8] px-6 py-4">
          <button
            type="submit"
            disabled={isPending || !name.trim() || !url.trim()}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8] disabled:opacity-50"
          >
            {isPending
              ? "Saving…"
              : mode === "create"
                ? "Create webhook"
                : "Save changes"}
          </button>
          <button
            type="button"
            onClick={onClose}
            disabled={isPending}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
          >
            Cancel
          </button>
        </div>
      </form>
    </aside>
  );
}

function DeliveryStatusBadge({
  status,
}: {
  status: WebhookDelivery["status"];
}) {
  if (status === "delivered") {
    return (
      <span className="rounded-full bg-[#e8f5e9] px-2 py-0.5 text-xs font-medium text-[#2e7d32]">
        Delivered
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">
        Failed
      </span>
    );
  }
  return (
    <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
      Pending
    </span>
  );
}

function DeliveryLogDrawer({
  webhook,
  onClose,
}: {
  webhook: Webhook;
  onClose: () => void;
}) {
  const deliveriesQuery = useQuery({
    queryKey: queryKeys.admin.webhookDeliveries(webhook.id),
    queryFn: () => listWebhookDeliveries(webhook.id),
  });

  const deliveries = deliveriesQuery.data?.items ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-end bg-black/30"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delivery-log-title"
    >
      <div className="flex h-full w-full max-w-lg flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-[#d7d4e8] px-6 py-4">
          <div>
            <h2
              id="delivery-log-title"
              className="text-base font-semibold text-[#2a2640]"
            >
              Delivery log — {webhook.name}
            </h2>
            <p className="text-xs text-[#68647b]">
              Last 50 deliveries, most recent first
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-[#68647b] hover:text-[#2a2640]"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-4">
          {deliveriesQuery.isLoading && (
            <p className="text-center text-sm text-[#68647b]">Loading…</p>
          )}
          {deliveriesQuery.isError && (
            <p className="text-center text-sm text-red-600">
              {getApiErrorMessage(deliveriesQuery.error)}
            </p>
          )}
          {!deliveriesQuery.isLoading && deliveries.length === 0 && (
            <p className="text-center text-sm text-[#68647b]">
              No deliveries yet.
            </p>
          )}
          {deliveries.map((d) => (
            <div
              key={d.id}
              className="mb-3 rounded-xl border border-[#e8e6f0] bg-[#fafafa] p-4"
            >
              <div className="mb-1 flex items-center gap-2">
                <DeliveryStatusBadge status={d.status} />
                <span className="text-xs font-medium text-[#4d4880]">
                  {d.event_type}
                </span>
                {d.http_status_code !== null && (
                  <span className="text-xs text-[#68647b]">
                    HTTP {d.http_status_code}
                  </span>
                )}
                <span className="ml-auto text-xs text-[#68647b]">
                  {new Date(d.created_at).toLocaleString()}
                </span>
              </div>
              {d.error_message && (
                <p className="mt-1 text-xs text-red-600">{d.error_message}</p>
              )}
              {d.response_body && (
                <details className="mt-2">
                  <summary className="cursor-pointer text-xs text-[#68647b]">
                    Response body
                  </summary>
                  <pre className="mt-1 overflow-x-auto rounded bg-[#f0eeff] p-2 text-xs text-[#2a2640]">
                    {d.response_body}
                  </pre>
                </details>
              )}
              <p className="mt-1 text-xs text-[#68647b]">
                Attempts: {d.attempt_count}
                {d.next_retry_at && (
                  <>
                    {" "}
                    · Next retry: {new Date(d.next_retry_at).toLocaleString()}
                  </>
                )}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function WebhookCard({
  webhook,
  canManage,
  onEdit,
  onDelete,
  onRotate,
  onTest,
  onViewLog,
}: {
  webhook: Webhook;
  canManage: boolean;
  onEdit: (w: Webhook) => void;
  onDelete: (w: Webhook) => void;
  onRotate: (w: Webhook) => void;
  onTest: (w: Webhook) => void;
  onViewLog: (w: Webhook) => void;
}) {
  const isDisabled = webhook.status === "disabled";

  return (
    <div
      className={`rounded-xl border p-5 shadow-sm ${
        isDisabled
          ? "border-[#e8e6f0] bg-[#fafafa] opacity-70"
          : "border-[#d7d4e8] bg-white"
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[#2a2640]">{webhook.name}</span>
            {isDisabled ? (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                Disabled
              </span>
            ) : (
              <span className="rounded-full bg-[#e8f5e9] px-2 py-0.5 text-xs font-medium text-[#2e7d32]">
                Active
              </span>
            )}
          </div>
          {webhook.description && (
            <p className="mt-0.5 text-sm text-[#68647b]">
              {webhook.description}
            </p>
          )}
        </div>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs text-[#68647b]">
        <span className="break-all">
          URL: <span className="font-mono text-[#2a2640]">{webhook.url}</span>
        </span>
        <span>
          Secret prefix:{" "}
          <code className="font-mono text-[#2a2640]">
            {webhook.secret_prefix}…
          </code>
        </span>
        <span>
          Retries: {webhook.retry_policy.max_attempts} ×{" "}
          {webhook.retry_policy.backoff_seconds}s
        </span>
      </div>

      {webhook.event_types.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {webhook.event_types.map((e) => (
            <span
              key={e}
              className="rounded bg-[#f5f3ff] px-2 py-0.5 text-xs text-[#4d4880]"
            >
              {e}
            </span>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => onViewLog(webhook)}
          className="text-sm font-medium text-[#3525cd] hover:underline"
        >
          Delivery log
        </button>
        {canManage && (
          <>
            <button
              type="button"
              onClick={() => onEdit(webhook)}
              className="text-sm font-medium text-[#3525cd] hover:underline"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => onRotate(webhook)}
              className="text-sm font-medium text-[#3525cd] hover:underline"
            >
              Rotate secret
            </button>
            {!isDisabled && (
              <button
                type="button"
                onClick={() => onTest(webhook)}
                className="text-sm font-medium text-[#3525cd] hover:underline"
              >
                Send test
              </button>
            )}
            <button
              type="button"
              onClick={() => onDelete(webhook)}
              className="text-sm font-medium text-red-600 hover:underline"
            >
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  );
}

type PanelState =
  | { kind: "idle" }
  | { kind: "create" }
  | { kind: "edit"; webhook: Webhook }
  | { kind: "created"; result: WebhookCreated };

export function AdminWebhooksPage() {
  const { hasPermission } = usePermissions();
  const canList = hasPermission("webhooks:list");
  const canManage =
    hasPermission("webhooks:create") && hasPermission("webhooks:delete");

  const [panel, setPanel] = useState<PanelState>({ kind: "idle" });
  const [deleteTarget, setDeleteTarget] = useState<Webhook | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [logTarget, setLogTarget] = useState<Webhook | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [secretResult, setSecretResult] = useState<WebhookCreated | null>(null);

  const queryClient = useQueryClient();

  const webhooksQuery = useQuery({
    queryKey: QUERY_WEBHOOKS,
    queryFn: listWebhooks,
    enabled: canList,
  });

  const deleteMutation = useMutation({
    mutationFn: (webhookId: string) => deleteWebhook(webhookId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: QUERY_WEBHOOKS });
      setDeleteTarget(null);
      setDeleteError(null);
    },
    onError: (err) => setDeleteError(getApiErrorMessage(err)),
  });

  const rotateMutation = useMutation({
    mutationFn: (webhookId: string) => rotateWebhookSecret(webhookId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: QUERY_WEBHOOKS });
      setSecretResult(result);
    },
    onError: (err) => setDeleteError(getApiErrorMessage(err)),
  });

  const testMutation = useMutation({
    mutationFn: (webhookId: string) => testWebhook(webhookId),
    onSuccess: (result) => {
      const delivery = result.items[0];
      if (delivery) {
        setTestResult(
          delivery.status === "delivered"
            ? `Test delivery succeeded (HTTP ${delivery.http_status_code ?? "—"})`
            : `Test delivery failed${delivery.error_message ? `: ${delivery.error_message}` : delivery.http_status_code ? ` (HTTP ${delivery.http_status_code})` : ""}`,
        );
      }
      queryClient.invalidateQueries({ queryKey: QUERY_WEBHOOKS });
    },
    onError: (err) => setTestResult(`Error: ${getApiErrorMessage(err)}`),
  });

  if (!canList) {
    return (
      <ForbiddenState
        title="Webhooks"
        description="You need the webhooks:list permission to access this page."
        backHref="/dashboard"
      />
    );
  }

  if (webhooksQuery.isLoading) return <LoadingState />;

  if (webhooksQuery.isError) {
    if (isForbiddenError(webhooksQuery.error)) {
      return (
        <ForbiddenState
          title="Webhooks"
          description="You do not have access to webhook management."
          requestId={extractRequestIdFromError(webhooksQuery.error)}
          backHref="/dashboard"
        />
      );
    }
    return <ErrorState message={getApiErrorMessage(webhooksQuery.error)} />;
  }

  const webhooks = webhooksQuery.data?.items ?? [];
  const active = webhooks.filter((w) => w.status === "active");
  const disabled = webhooks.filter((w) => w.status === "disabled");

  return (
    <div className="mx-auto max-w-4xl space-y-8 px-4 py-8">
      <div className="flex items-start justify-between">
        <div>
          <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
            Admin
          </p>
          <h1 className="text-2xl font-extrabold text-[#2a2640]">Webhooks</h1>
          <p className="mt-1 text-sm text-[#68647b]">
            Receive signed HTTP notifications when events happen in Rudix.
          </p>
        </div>
        {canManage && (
          <button
            type="button"
            onClick={() => setPanel({ kind: "create" })}
            className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#2b1fa8]"
          >
            + Add webhook
          </button>
        )}
      </div>

      {testResult && (
        <div
          className={`rounded-lg px-4 py-3 text-sm ${
            testResult.startsWith("Test delivery succeeded")
              ? "bg-[#e8f5e9] text-[#2e7d32]"
              : "bg-red-50 text-red-700"
          }`}
        >
          {testResult}
          <button
            type="button"
            onClick={() => setTestResult(null)}
            className="ml-3 font-medium underline"
          >
            Dismiss
          </button>
        </div>
      )}

      <section>
        <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
          Active webhooks
          <span className="ml-2 text-sm font-normal text-[#68647b]">
            ({active.length})
          </span>
        </h2>
        {active.length === 0 ? (
          <div className="rounded-xl border border-dashed border-[#d7d4e8] p-8 text-center text-sm text-[#68647b]">
            No active webhooks.
            {canManage && (
              <>
                {" "}
                <button
                  type="button"
                  onClick={() => setPanel({ kind: "create" })}
                  className="font-medium text-[#3525cd] hover:underline"
                >
                  Add one
                </button>{" "}
                to start receiving event notifications.
              </>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {active.map((w) => (
              <WebhookCard
                key={w.id}
                webhook={w}
                canManage={canManage}
                onEdit={(wh) => setPanel({ kind: "edit", webhook: wh })}
                onDelete={(wh) => {
                  setDeleteTarget(wh);
                  setDeleteError(null);
                }}
                onRotate={(wh) => rotateMutation.mutate(wh.id)}
                onTest={(wh) => testMutation.mutate(wh.id)}
                onViewLog={(wh) => setLogTarget(wh)}
              />
            ))}
          </div>
        )}
      </section>

      {disabled.length > 0 && (
        <section>
          <h2 className="mb-4 text-base font-semibold text-[#2a2640]">
            Disabled webhooks
            <span className="ml-2 text-sm font-normal text-[#68647b]">
              ({disabled.length})
            </span>
          </h2>
          <div className="space-y-3">
            {disabled.map((w) => (
              <WebhookCard
                key={w.id}
                webhook={w}
                canManage={canManage}
                onEdit={(wh) => setPanel({ kind: "edit", webhook: wh })}
                onDelete={(wh) => {
                  setDeleteTarget(wh);
                  setDeleteError(null);
                }}
                onRotate={(wh) => rotateMutation.mutate(wh.id)}
                onTest={() => {}}
                onViewLog={(wh) => setLogTarget(wh)}
              />
            ))}
          </div>
        </section>
      )}

      {/* Delete confirmation dialog */}
      {deleteTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-webhook-title"
        >
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h3
              id="delete-webhook-title"
              className="mb-2 text-base font-semibold text-[#2a2640]"
            >
              Delete &ldquo;{deleteTarget.name}&rdquo;?
            </h3>
            <p className="mb-4 text-sm text-[#68647b]">
              The webhook and its delivery history will be permanently removed.
              This cannot be undone.
            </p>
            {deleteError && (
              <p className="mb-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
                {deleteError}
              </p>
            )}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => deleteMutation.mutate(deleteTarget.id)}
                disabled={deleteMutation.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting…" : "Delete webhook"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setDeleteTarget(null);
                  setDeleteError(null);
                }}
                disabled={deleteMutation.isPending}
                className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Create / edit slide-over */}
      {panel.kind === "create" && (
        <WebhookFormPanel
          mode="create"
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={(result) => {
            setPanel({ kind: "idle" });
            if (result) setSecretResult(result);
          }}
        />
      )}

      {panel.kind === "edit" && (
        <WebhookFormPanel
          mode="edit"
          existing={panel.webhook}
          onClose={() => setPanel({ kind: "idle" })}
          onSaved={() => setPanel({ kind: "idle" })}
        />
      )}

      {/* New / rotated secret banner */}
      {secretResult && (
        <CreatedSecretBanner
          result={secretResult}
          onClose={() => setSecretResult(null)}
        />
      )}

      {/* Delivery log drawer */}
      {logTarget && (
        <DeliveryLogDrawer
          webhook={logTarget}
          onClose={() => setLogTarget(null)}
        />
      )}
    </div>
  );
}
