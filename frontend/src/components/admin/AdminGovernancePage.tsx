"use client";

import { useMemo, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  DEFAULT_PROVIDER_SECURITY,
  getGovernancePolicy,
  type GovernancePolicyResponse,
  type GovernancePolicyState,
  type ExternalMcpServerPolicy,
  type ProviderSecurityPolicy,
  updateGovernancePolicy,
} from "@/lib/api/admin-governance";
import { ProviderSecuritySection } from "@/components/admin/governance/ProviderSecuritySection";
import { getApiErrorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/query";
import { canViewAdminUsage } from "@/lib/dashboard";
import { extractRequestIdFromError, isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { ForbiddenState } from "@/components/states/ForbiddenState";
import { LoadingState } from "@/components/states/LoadingState";

type NewServerFormState = {
  server_id: string;
  base_url: string;
  auth_type: ExternalMcpServerPolicy["auth_type"];
  auth_header_name: string;
  auth_secret_ref: string;
  allow_tools: string;
  read_only_tools: string;
  side_effect_tools: string;
  required_roles: string;
  enabled: boolean;
  expose_on_mcp_surface: boolean;
  approval_required_for_side_effect: boolean;
};

const DEFAULT_NEW_SERVER: NewServerFormState = {
  server_id: "",
  base_url: "",
  auth_type: "none",
  auth_header_name: "",
  auth_secret_ref: "",
  allow_tools: "",
  read_only_tools: "",
  side_effect_tools: "",
  required_roles: "owner,admin",
  enabled: true,
  expose_on_mcp_surface: false,
  approval_required_for_side_effect: true,
};

function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function formatCommaList(values: string[]): string {
  return values.join(", ");
}

function parseInteger(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return parsed;
}

function parseDecimal(value: string): number | null {
  if (!value.trim()) {
    return null;
  }
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return parsed;
}

function clonePolicy(policy: GovernancePolicyState): GovernancePolicyState {
  return {
    ...policy,
    allowed_tool_names: [...policy.allowed_tool_names],
    budgets: { ...policy.budgets },
    external_mcp_servers: policy.external_mcp_servers.map((server) => ({
      ...server,
      allow_tools: [...server.allow_tools],
      read_only_tools: [...server.read_only_tools],
      side_effect_tools: [...server.side_effect_tools],
      required_roles: [...server.required_roles],
    })),
    provider_security: {
      ...(policy.provider_security ?? DEFAULT_PROVIDER_SECURITY),
      allowed_provider_profiles: [
        ...(policy.provider_security?.allowed_provider_profiles ?? []),
      ],
    },
  };
}

function resolveInitialPolicy(
  currentDraft: GovernancePolicyState | null,
  response: GovernancePolicyResponse | undefined,
): GovernancePolicyState | null {
  if (currentDraft) {
    return currentDraft;
  }
  if (!response) {
    return null;
  }
  return clonePolicy(response.policy);
}

function resolveToolDanger(
  toolName: string,
  toolCatalog: GovernancePolicyResponse["tool_catalog"],
): boolean {
  const tool = toolCatalog.find((item) => item.name === toolName);
  return tool?.effect_policy === "side_effect";
}

export function AdminGovernancePage() {
  const { state } = useAuthSession();
  const queryClient = useQueryClient();
  const role = state.session?.role;
  const isAdminUser = canViewAdminUsage(role);
  const [draftPolicy, setDraftPolicy] = useState<GovernancePolicyState | null>(
    null,
  );
  const [sideEffectAck, setSideEffectAck] = useState(false);
  const [cloudFallbackAck, setCloudFallbackAck] = useState(false);
  const [newServer, setNewServer] =
    useState<NewServerFormState>(DEFAULT_NEW_SERVER);

  const governanceQuery = useQuery({
    queryKey: queryKeys.admin.governance,
    queryFn: () => getGovernancePolicy(),
    enabled: isAdminUser,
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      const policy = resolveInitialPolicy(draftPolicy, governanceQuery.data);
      if (!policy) {
        throw new Error("Governance policy is not loaded.");
      }
      return updateGovernancePolicy({
        ...policy,
        side_effect_warning_acknowledged: sideEffectAck,
        provider_security: policy.provider_security ?? DEFAULT_PROVIDER_SECURITY,
        cloud_fallback_warning_acknowledged: cloudFallbackAck,
      });
    },
    onSuccess: (response) => {
      setDraftPolicy(clonePolicy(response.policy));
      setSideEffectAck(false);
      setCloudFallbackAck(false);
      queryClient.setQueryData(
        queryKeys.admin.governance,
        (previous: GovernancePolicyResponse | undefined) => {
          if (!previous) {
            return {
              organization_id: response.organization_id,
              policy: response.policy,
              warnings: response.warnings,
              mcp_status: {
                feature_enable_mcp: false,
                mcp_transport: "streamable_http",
                mcp_http_path: "/mcp",
                mcp_http_host: "0.0.0.0",
                mcp_http_port: 8010,
                mcp_auth_required: true,
                mcp_rate_limit_enabled: true,
                feature_enable_external_mcp_connectors: false,
                configured_global_external_servers: 0,
              },
              tool_catalog: [],
              policy_updated_at: response.updated_at,
              policy_updated_by_user_id: response.updated_by_user_id,
            } satisfies GovernancePolicyResponse;
          }
          return {
            ...previous,
            policy: response.policy,
            warnings: response.warnings,
            policy_updated_at: response.updated_at,
            policy_updated_by_user_id: response.updated_by_user_id,
          };
        },
      );
    },
  });

  const forbiddenError =
    governanceQuery.isError &&
    isForbiddenError(governanceQuery.error) &&
    governanceQuery.error;

  const policy = resolveInitialPolicy(draftPolicy, governanceQuery.data);
  const tools = useMemo(
    () => governanceQuery.data?.tool_catalog ?? [],
    [governanceQuery.data?.tool_catalog],
  );
  const warnings = governanceQuery.data?.warnings ?? [];

  const selectedSideEffectTools = useMemo(() => {
    if (!policy) {
      return [];
    }
    return policy.allowed_tool_names.filter((name) =>
      resolveToolDanger(name, tools),
    );
  }, [policy, tools]);

  if (!isAdminUser) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Admin governance restricted"
          description="Only owner and admin roles can manage agent and MCP policy."
          compact={false}
        />
      </section>
    );
  }

  if (forbiddenError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ForbiddenState
          title="Governance settings unavailable"
          description="Your role no longer has access to governance settings."
          requestId={extractRequestIdFromError(forbiddenError)}
        />
      </section>
    );
  }

  if (governanceQuery.isLoading || !policy) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <LoadingState
          title="Loading governance settings"
          description="Preparing organization policy configuration."
          compact={false}
        />
      </section>
    );
  }

  if (governanceQuery.isError) {
    return (
      <section className="px-4 py-5 lg:px-8 lg:py-8">
        <ErrorState
          title="Unable to load governance settings"
          description={getApiErrorMessage(governanceQuery.error)}
          compact={false}
          requestId={extractRequestIdFromError(governanceQuery.error)}
          onRetry={() => governanceQuery.refetch()}
        />
      </section>
    );
  }

  const mcpStatus = governanceQuery.data?.mcp_status;
  const mutationError = saveMutation.error
    ? getApiErrorMessage(saveMutation.error)
    : null;

  return (
    <section className="space-y-6 px-4 py-5 lg:px-8 lg:py-8">
      <header className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs font-bold tracking-[0.18em] text-[#5d58a8] uppercase">
          Rudix Admin
        </p>
        <h1 className="mb-2 text-2xl font-extrabold text-[#2a2640] lg:text-3xl">
          Agent and MCP governance
        </h1>
        <p className="max-w-3xl text-sm text-[#68647b]">
          Control organization-level agent mode, MCP exposure, tool allowlists,
          and execution budgets.
        </p>
      </header>

      {warnings.length > 0 ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4">
          <h2 className="text-sm font-bold text-amber-900">
            Governance warnings
          </h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-800">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {mutationError ? (
        <ErrorState
          title="Unable to save governance policy"
          description={mutationError}
          compact={false}
        />
      ) : null}

      <section className="grid gap-4 lg:grid-cols-2">
        <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">Policy toggles</h2>
          <div className="mt-3 space-y-3">
            <label className="flex items-center justify-between rounded-lg border border-[#e1dff0] p-3">
              <span className="text-sm font-medium text-[#3d3953]">
                Enable agentic mode
              </span>
              <input
                type="checkbox"
                checked={policy.agentic_mode_enabled}
                onChange={(event) =>
                  setDraftPolicy({
                    ...policy,
                    agentic_mode_enabled: event.target.checked,
                  })
                }
              />
            </label>
            <label className="flex items-center justify-between rounded-lg border border-[#e1dff0] p-3">
              <span className="text-sm font-medium text-[#3d3953]">
                Allow MCP exposure for this organization
              </span>
              <input
                type="checkbox"
                checked={policy.mcp_exposure_enabled}
                onChange={(event) =>
                  setDraftPolicy({
                    ...policy,
                    mcp_exposure_enabled: event.target.checked,
                  })
                }
              />
            </label>
            <label className="flex items-center justify-between rounded-lg border border-[#e1dff0] p-3">
              <span className="text-sm font-medium text-[#3d3953]">
                Allow side-effect tools
              </span>
              <input
                type="checkbox"
                checked={policy.allow_side_effect_tools}
                onChange={(event) =>
                  setDraftPolicy({
                    ...policy,
                    allow_side_effect_tools: event.target.checked,
                  })
                }
              />
            </label>
            {selectedSideEffectTools.length > 0 ? (
              <label className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
                <input
                  type="checkbox"
                  checked={sideEffectAck}
                  onChange={(event) => setSideEffectAck(event.target.checked)}
                />
                <span>
                  I acknowledge side-effect tools can modify data and should be
                  protected by approvals.
                </span>
              </label>
            ) : null}
          </div>
        </article>

        <article className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
          <h2 className="text-lg font-bold text-[#2a2640]">MCP endpoint</h2>
          {mcpStatus ? (
            <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-sm">
              <dt className="font-medium text-[#6a6780]">MCP feature flag</dt>
              <dd className="font-semibold text-[#2a2640]">
                {mcpStatus.feature_enable_mcp ? "Enabled" : "Disabled"}
              </dd>
              <dt className="font-medium text-[#6a6780]">Transport</dt>
              <dd className="font-semibold text-[#2a2640]">
                {mcpStatus.mcp_transport}
              </dd>
              <dt className="font-medium text-[#6a6780]">Endpoint</dt>
              <dd className="font-semibold text-[#2a2640]">
                {mcpStatus.mcp_http_host}:{mcpStatus.mcp_http_port}
                {mcpStatus.mcp_http_path}
              </dd>
              <dt className="font-medium text-[#6a6780]">Auth required</dt>
              <dd className="font-semibold text-[#2a2640]">
                {mcpStatus.mcp_auth_required ? "Yes" : "No"}
              </dd>
              <dt className="font-medium text-[#6a6780]">Rate limit</dt>
              <dd className="font-semibold text-[#2a2640]">
                {mcpStatus.mcp_rate_limit_enabled ? "Enabled" : "Disabled"}
              </dd>
              <dt className="font-medium text-[#6a6780]">
                External connectors
              </dt>
              <dd className="font-semibold text-[#2a2640]">
                {mcpStatus.feature_enable_external_mcp_connectors
                  ? `Enabled (${mcpStatus.configured_global_external_servers} global)`
                  : "Disabled"}
              </dd>
            </dl>
          ) : (
            <EmptyState
              title="MCP status unavailable"
              description="No MCP status payload was returned by the backend."
              compact
            />
          )}
        </article>
      </section>

      <ProviderSecuritySection
        policy={policy.provider_security ?? DEFAULT_PROVIDER_SECURITY}
        cloudFallbackAck={cloudFallbackAck}
        onPolicyChange={(next: ProviderSecurityPolicy) =>
          setDraftPolicy({ ...policy, provider_security: next })
        }
        onCloudFallbackAckChange={setCloudFallbackAck}
      />

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">Tool allowlist</h2>
        <p className="mt-1 text-sm text-[#68647b]">
          Only selected tools are available to the organization agent runtime.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {tools.map((tool) => {
            const selected = policy.allowed_tool_names.includes(tool.name);
            const isSideEffect = tool.effect_policy === "side_effect";
            return (
              <label
                key={tool.name}
                className="flex items-start gap-2 rounded-lg border border-[#e1dff0] p-3"
              >
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={(event) => {
                    const next = event.target.checked
                      ? [...policy.allowed_tool_names, tool.name]
                      : policy.allowed_tool_names.filter(
                          (name) => name !== tool.name,
                        );
                    setDraftPolicy({
                      ...policy,
                      allowed_tool_names: [...new Set(next)],
                    });
                  }}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-[#2a2640]">
                    {tool.name}
                  </span>
                  <span className="block text-xs text-[#6a6780]">
                    {tool.capability}
                  </span>
                  <span
                    className={`mt-1 inline-flex rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      isSideEffect
                        ? "bg-rose-100 text-rose-800"
                        : "bg-emerald-100 text-emerald-800"
                    }`}
                  >
                    {tool.effect_policy}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <h2 className="text-lg font-bold text-[#2a2640]">Budgets</h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <BudgetInput
            label="Max steps"
            value={String(policy.budgets.max_steps)}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_steps: parseInteger(value) ?? policy.budgets.max_steps,
                },
              })
            }
          />
          <BudgetInput
            label="Max tool calls / run"
            value={String(policy.budgets.max_tool_calls_per_run)}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_tool_calls_per_run:
                    parseInteger(value) ??
                    policy.budgets.max_tool_calls_per_run,
                },
              })
            }
          />
          <BudgetInput
            label="Max tool timeout (ms)"
            value={String(policy.budgets.max_tool_timeout_ms)}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_tool_timeout_ms:
                    parseInteger(value) ?? policy.budgets.max_tool_timeout_ms,
                },
              })
            }
          />
          <BudgetInput
            label="Max input bytes"
            value={String(policy.budgets.max_tool_input_bytes)}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_tool_input_bytes:
                    parseInteger(value) ?? policy.budgets.max_tool_input_bytes,
                },
              })
            }
          />
          <BudgetInput
            label="Max output bytes"
            value={String(policy.budgets.max_tool_output_bytes)}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_tool_output_bytes:
                    parseInteger(value) ?? policy.budgets.max_tool_output_bytes,
                },
              })
            }
          />
          <BudgetInput
            label="Max retry attempts"
            value={String(policy.budgets.max_tool_retry_attempts)}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_tool_retry_attempts:
                    parseInteger(value) ??
                    policy.budgets.max_tool_retry_attempts,
                },
              })
            }
          />
          <BudgetInput
            label="Max total tokens (optional)"
            value={String(policy.budgets.max_total_tokens ?? "")}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_total_tokens: parseInteger(value),
                },
              })
            }
          />
          <BudgetInput
            label="Max total cost USD (optional)"
            value={String(policy.budgets.max_total_cost_usd ?? "")}
            onChange={(value) =>
              setDraftPolicy({
                ...policy,
                budgets: {
                  ...policy.budgets,
                  max_total_cost_usd: parseDecimal(value),
                },
              })
            }
          />
        </div>
      </section>

      <section className="rounded-2xl border border-[#d7d4e8] bg-white p-5 shadow-sm">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-lg font-bold text-[#2a2640]">
            External MCP servers
          </h2>
          <span className="text-sm font-semibold text-[#6a6780]">
            {policy.external_mcp_servers.length} configured
          </span>
        </div>
        {policy.external_mcp_servers.length > 0 ? (
          <div className="mt-3 grid gap-3">
            {policy.external_mcp_servers.map((server) => (
              <article
                key={server.server_id}
                className="rounded-lg border border-[#e1dff0] p-3"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-[#2a2640]">
                      {server.server_id}
                    </p>
                    <p className="text-xs text-[#6a6780]">{server.base_url}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() =>
                      setDraftPolicy({
                        ...policy,
                        external_mcp_servers:
                          policy.external_mcp_servers.filter(
                            (item) => item.server_id !== server.server_id,
                          ),
                      })
                    }
                    className="rounded-md border border-rose-200 px-2 py-1 text-xs font-semibold text-rose-700 hover:bg-rose-50"
                  >
                    Remove
                  </button>
                </div>
                <p className="mt-2 text-xs text-[#6a6780]">
                  auth={server.auth_type} secret_ref=
                  {server.auth_secret_ref ?? "n/a"} allow_tools=
                  {formatCommaList(server.allow_tools)}
                </p>
              </article>
            ))}
          </div>
        ) : (
          <EmptyState
            title="No external MCP servers"
            description="Add an approved server configuration for this organization."
            compact
          />
        )}

        <div className="mt-4 rounded-lg border border-dashed border-[#d2cee6] p-3">
          <h3 className="text-sm font-bold text-[#3d3953]">
            Add external server
          </h3>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <input
              value={newServer.server_id}
              onChange={(event) =>
                setNewServer((previous) => ({
                  ...previous,
                  server_id: event.target.value,
                }))
              }
              placeholder="server_id"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
            />
            <input
              value={newServer.base_url}
              onChange={(event) =>
                setNewServer((previous) => ({
                  ...previous,
                  base_url: event.target.value,
                }))
              }
              placeholder="https://server.example.com/mcp"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
            />
            <select
              value={newServer.auth_type}
              onChange={(event) =>
                setNewServer((previous) => ({
                  ...previous,
                  auth_type: event.target
                    .value as ExternalMcpServerPolicy["auth_type"],
                }))
              }
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
            >
              <option value="none">auth: none</option>
              <option value="bearer">auth: bearer</option>
              <option value="header">auth: header</option>
            </select>
            <input
              value={newServer.auth_secret_ref}
              onChange={(event) =>
                setNewServer((previous) => ({
                  ...previous,
                  auth_secret_ref: event.target.value,
                }))
              }
              placeholder="secret ref"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
            />
            <input
              value={newServer.auth_header_name}
              onChange={(event) =>
                setNewServer((previous) => ({
                  ...previous,
                  auth_header_name: event.target.value,
                }))
              }
              placeholder="auth header name (optional)"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
            />
            <input
              value={newServer.allow_tools}
              onChange={(event) =>
                setNewServer((previous) => ({
                  ...previous,
                  allow_tools: event.target.value,
                }))
              }
              placeholder="allow tools (comma list)"
              className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm"
            />
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-xs text-[#6a6780]">
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={newServer.enabled}
                onChange={(event) =>
                  setNewServer((previous) => ({
                    ...previous,
                    enabled: event.target.checked,
                  }))
                }
              />
              Enabled
            </label>
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={newServer.expose_on_mcp_surface}
                onChange={(event) =>
                  setNewServer((previous) => ({
                    ...previous,
                    expose_on_mcp_surface: event.target.checked,
                  }))
                }
              />
              Expose on MCP surface
            </label>
            <label className="inline-flex items-center gap-1">
              <input
                type="checkbox"
                checked={newServer.approval_required_for_side_effect}
                onChange={(event) =>
                  setNewServer((previous) => ({
                    ...previous,
                    approval_required_for_side_effect: event.target.checked,
                  }))
                }
              />
              Require approvals for side effects
            </label>
          </div>
          <button
            type="button"
            onClick={() => {
              if (!newServer.server_id.trim() || !newServer.base_url.trim()) {
                return;
              }
              const nextServer: ExternalMcpServerPolicy = {
                server_id: newServer.server_id.trim(),
                enabled: newServer.enabled,
                transport: "streamable_http",
                base_url: newServer.base_url.trim(),
                auth_type: newServer.auth_type,
                auth_header_name: newServer.auth_header_name.trim() || null,
                auth_secret_ref: newServer.auth_secret_ref.trim() || null,
                allow_tools: parseCommaList(newServer.allow_tools),
                read_only_tools: parseCommaList(newServer.read_only_tools),
                side_effect_tools: parseCommaList(newServer.side_effect_tools),
                required_roles: parseCommaList(newServer.required_roles),
                expose_on_mcp_surface: newServer.expose_on_mcp_surface,
                approval_required_for_side_effect:
                  newServer.approval_required_for_side_effect,
              };
              setDraftPolicy({
                ...policy,
                external_mcp_servers: [
                  ...policy.external_mcp_servers.filter(
                    (item) => item.server_id !== nextServer.server_id,
                  ),
                  nextServer,
                ],
              });
              setNewServer(DEFAULT_NEW_SERVER);
            }}
            className="mt-3 rounded-lg bg-[#3525cd] px-3 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8]"
          >
            Add server
          </button>
        </div>
      </section>

      <div className="flex justify-end gap-3">
        <button
          type="button"
          onClick={() => setDraftPolicy(clonePolicy(policy))}
          className="rounded-lg border border-[#d2cee6] px-4 py-2 text-sm font-semibold text-[#3f3b58] hover:bg-[#f8f6ff]"
        >
          Reset
        </button>
        <button
          type="button"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="rounded-lg bg-[#3525cd] px-4 py-2 text-sm font-semibold text-white hover:bg-[#2b1fa8] disabled:opacity-60"
        >
          {saveMutation.isPending ? "Saving..." : "Save governance policy"}
        </button>
      </div>
    </section>
  );
}

function BudgetInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold tracking-wide text-[#6a6780] uppercase">
      {label}
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 rounded-lg border border-[#d2cee6] px-2 text-sm font-medium text-[#2a2640]"
      />
    </label>
  );
}
