import { apiRequest } from "@/lib/api/request";
import { getFrontendRuntimeConfig } from "@/lib/runtime-config";

function trimToNull(value: string | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : null;
}

// ── Capabilities ──────────────────────────────────────────────────────────────

export type BillingCapabilities = {
  planEnabled: boolean;
  usageEnabled: boolean;
  quotasEnabled: boolean;
  invoicesEnabled: boolean;
  billingContactEnabled: boolean;
  updateBillingContactEnabled: boolean;
};

function getBillingEndpoints() {
  return {
    planUrl: trimToNull(process.env.NEXT_PUBLIC_BILLING_PLAN_URL),
    usageUrl: trimToNull(process.env.NEXT_PUBLIC_BILLING_USAGE_URL),
    quotasUrl: trimToNull(process.env.NEXT_PUBLIC_BILLING_QUOTAS_URL),
    invoicesUrl: trimToNull(process.env.NEXT_PUBLIC_BILLING_INVOICES_URL),
    billingContactUrl: trimToNull(
      process.env.NEXT_PUBLIC_BILLING_CONTACT_URL,
    ),
    updateBillingContactUrl: trimToNull(
      process.env.NEXT_PUBLIC_BILLING_CONTACT_UPDATE_URL,
    ),
  };
}

export function getBillingCapabilities(): BillingCapabilities {
  const e = getBillingEndpoints();
  const allowUnavailable =
    getFrontendRuntimeConfig().features.unavailableBackendEndpoints;

  if (!allowUnavailable) {
    const core = Boolean(e.planUrl && e.usageUrl && e.quotasUrl);
    return {
      planEnabled: core,
      usageEnabled: core,
      quotasEnabled: core,
      invoicesEnabled: core && Boolean(e.invoicesUrl),
      billingContactEnabled: core && Boolean(e.billingContactUrl),
      updateBillingContactEnabled: core && Boolean(e.updateBillingContactUrl),
    };
  }

  return {
    planEnabled: Boolean(e.planUrl),
    usageEnabled: Boolean(e.usageUrl),
    quotasEnabled: Boolean(e.quotasUrl),
    invoicesEnabled: Boolean(e.invoicesUrl),
    billingContactEnabled: Boolean(e.billingContactUrl),
    updateBillingContactEnabled: Boolean(e.updateBillingContactUrl),
  };
}

export class BillingEndpointUnavailableError extends Error {
  readonly endpointKey: keyof BillingCapabilities;

  constructor(endpointKey: keyof BillingCapabilities) {
    super("Billing endpoint is not configured");
    this.name = "BillingEndpointUnavailableError";
    this.endpointKey = endpointKey;
  }
}

export function isBillingEndpointUnavailableError(
  error: unknown,
): error is BillingEndpointUnavailableError {
  return error instanceof BillingEndpointUnavailableError;
}

// ── Types ─────────────────────────────────────────────────────────────────────

export type BillingPlanStatus =
  | "active"
  | "trialing"
  | "past_due"
  | "cancelled"
  | "unknown";

export type BillingCycle = "monthly" | "annual" | null;

export type BillingPlanInfo = {
  plan_name: string;
  status: BillingPlanStatus;
  billing_cycle: BillingCycle;
  renewal_date: string | null;
  trial_end_date: string | null;
  seats_used: number | null;
  seats_included: number | null;
  storage_used_gb: number | null;
  storage_included_gb: number | null;
  monthly_questions_used: number | null;
  monthly_questions_included: number | null;
  token_allowance_used: number | null;
  token_allowance_included: number | null;
  evaluation_allowance_used: number | null;
  evaluation_allowance_included: number | null;
  agent_allowance_used: number | null;
  agent_allowance_included: number | null;
  connector_allowance_used: number | null;
  connector_allowance_included: number | null;
  can_manage_subscription: boolean;
  can_cancel_plan: boolean;
};

export type BillingDateRange = "7d" | "30d" | "90d" | "billing_period";

export type BillingUsageSummary = {
  range: { from: string; to: string };
  documents_uploaded: number | null;
  indexed_documents: number | null;
  storage_used_gb: number | null;
  total_chunks: number | null;
  questions_asked: number | null;
  avg_confidence: number | null;
  avg_latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_llm_cost_usd: number | null;
  evaluation_runs: number | null;
  agent_runs: number | null;
  connector_sync_jobs: number | null;
  failed_indexing_jobs: number | null;
};

export type BillingQuota = {
  resource: string;
  label: string;
  used: number;
  limit: number | null;
  unit: string;
};

export type InvoiceStatus = "paid" | "open" | "void" | "uncollectible";

export type Invoice = {
  id: string;
  date: string;
  amount_usd: number;
  status: InvoiceStatus;
  download_url: string | null;
};

export type BillingContact = {
  email: string | null;
  name: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  country: string | null;
  tax_id: string | null;
  payment_method_summary: string | null;
};

// ── Normalization ─────────────────────────────────────────────────────────────

type RawRecord = Record<string, unknown>;

function toRaw(payload: unknown): RawRecord {
  return typeof payload === "object" && payload !== null && !Array.isArray(payload)
    ? (payload as RawRecord)
    : {};
}

function asString(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function asStringOrNull(v: unknown): string | null {
  if (typeof v === "string" && v.trim().length > 0) return v.trim();
  return null;
}

function asNumberOrNull(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  return null;
}

function asBoolean(v: unknown, fallback: boolean): boolean {
  return typeof v === "boolean" ? v : fallback;
}

function asPlanStatus(v: unknown): BillingPlanStatus {
  const valid: BillingPlanStatus[] = [
    "active",
    "trialing",
    "past_due",
    "cancelled",
    "unknown",
  ];
  return (valid as string[]).includes(v as string)
    ? (v as BillingPlanStatus)
    : "unknown";
}

function asBillingCycle(v: unknown): BillingCycle {
  if (v === "monthly" || v === "annual") return v;
  return null;
}

function asInvoiceStatus(v: unknown): InvoiceStatus {
  const valid: InvoiceStatus[] = ["paid", "open", "void", "uncollectible"];
  return (valid as string[]).includes(v as string)
    ? (v as InvoiceStatus)
    : "open";
}

function normalizePlanInfo(payload: unknown): BillingPlanInfo {
  const r = toRaw(payload);
  return {
    plan_name: asString(r.plan_name, "Unknown"),
    status: asPlanStatus(r.status),
    billing_cycle: asBillingCycle(r.billing_cycle),
    renewal_date: asStringOrNull(r.renewal_date),
    trial_end_date: asStringOrNull(r.trial_end_date),
    seats_used: asNumberOrNull(r.seats_used),
    seats_included: asNumberOrNull(r.seats_included),
    storage_used_gb: asNumberOrNull(r.storage_used_gb),
    storage_included_gb: asNumberOrNull(r.storage_included_gb),
    monthly_questions_used: asNumberOrNull(r.monthly_questions_used),
    monthly_questions_included: asNumberOrNull(r.monthly_questions_included),
    token_allowance_used: asNumberOrNull(r.token_allowance_used),
    token_allowance_included: asNumberOrNull(r.token_allowance_included),
    evaluation_allowance_used: asNumberOrNull(r.evaluation_allowance_used),
    evaluation_allowance_included: asNumberOrNull(
      r.evaluation_allowance_included,
    ),
    agent_allowance_used: asNumberOrNull(r.agent_allowance_used),
    agent_allowance_included: asNumberOrNull(r.agent_allowance_included),
    connector_allowance_used: asNumberOrNull(r.connector_allowance_used),
    connector_allowance_included: asNumberOrNull(r.connector_allowance_included),
    can_manage_subscription: asBoolean(r.can_manage_subscription, false),
    can_cancel_plan: asBoolean(r.can_cancel_plan, false),
  };
}

function normalizeUsageSummary(payload: unknown): BillingUsageSummary {
  const r = toRaw(payload);
  const range = toRaw(r.range);
  return {
    range: {
      from: asString(range.from),
      to: asString(range.to),
    },
    documents_uploaded: asNumberOrNull(r.documents_uploaded),
    indexed_documents: asNumberOrNull(r.indexed_documents),
    storage_used_gb: asNumberOrNull(r.storage_used_gb),
    total_chunks: asNumberOrNull(r.total_chunks),
    questions_asked: asNumberOrNull(r.questions_asked),
    avg_confidence: asNumberOrNull(r.avg_confidence),
    avg_latency_ms: asNumberOrNull(r.avg_latency_ms),
    input_tokens: asNumberOrNull(r.input_tokens),
    output_tokens: asNumberOrNull(r.output_tokens),
    estimated_llm_cost_usd: asNumberOrNull(r.estimated_llm_cost_usd),
    evaluation_runs: asNumberOrNull(r.evaluation_runs),
    agent_runs: asNumberOrNull(r.agent_runs),
    connector_sync_jobs: asNumberOrNull(r.connector_sync_jobs),
    failed_indexing_jobs: asNumberOrNull(r.failed_indexing_jobs),
  };
}

function normalizeQuota(payload: unknown): BillingQuota {
  const r = toRaw(payload);
  return {
    resource: asString(r.resource),
    label: asString(r.label),
    used: asNumberOrNull(r.used) ?? 0,
    limit: asNumberOrNull(r.limit),
    unit: asString(r.unit, ""),
  };
}

function normalizeInvoice(payload: unknown): Invoice {
  const r = toRaw(payload);
  return {
    id: asString(r.id),
    date: asString(r.date),
    amount_usd: asNumberOrNull(r.amount_usd) ?? 0,
    status: asInvoiceStatus(r.status),
    download_url: asStringOrNull(r.download_url),
  };
}

function normalizeBillingContact(payload: unknown): BillingContact {
  const r = toRaw(payload);
  return {
    email: asStringOrNull(r.email),
    name: asStringOrNull(r.name),
    address_line1: asStringOrNull(r.address_line1),
    address_line2: asStringOrNull(r.address_line2),
    city: asStringOrNull(r.city),
    state: asStringOrNull(r.state),
    postal_code: asStringOrNull(r.postal_code),
    country: asStringOrNull(r.country),
    tax_id: asStringOrNull(r.tax_id),
    payment_method_summary: asStringOrNull(r.payment_method_summary),
  };
}

// ── API functions ─────────────────────────────────────────────────────────────

export async function getBillingPlanInfo(): Promise<BillingPlanInfo> {
  const { planUrl } = getBillingEndpoints();
  if (!planUrl) throw new BillingEndpointUnavailableError("planEnabled");
  const payload = await apiRequest<unknown>(planUrl, {
    method: "GET",
    retry: false,
  });
  return normalizePlanInfo(payload);
}

export async function getBillingUsageSummary(
  range: BillingDateRange = "30d",
): Promise<BillingUsageSummary> {
  const { usageUrl } = getBillingEndpoints();
  if (!usageUrl) throw new BillingEndpointUnavailableError("usageEnabled");
  const payload = await apiRequest<unknown>(usageUrl, {
    method: "GET",
    query: { range },
    retry: false,
  });
  return normalizeUsageSummary(payload);
}

export async function getBillingQuotas(): Promise<BillingQuota[]> {
  const { quotasUrl } = getBillingEndpoints();
  if (!quotasUrl) throw new BillingEndpointUnavailableError("quotasEnabled");
  const payload = await apiRequest<unknown>(quotasUrl, {
    method: "GET",
    retry: false,
  });
  if (Array.isArray(payload)) {
    return payload.map(normalizeQuota);
  }
  const r = toRaw(payload);
  if (Array.isArray(r.items)) {
    return (r.items as unknown[]).map(normalizeQuota);
  }
  return [];
}

export async function getInvoices(): Promise<Invoice[]> {
  const { invoicesUrl } = getBillingEndpoints();
  if (!invoicesUrl) throw new BillingEndpointUnavailableError("invoicesEnabled");
  const payload = await apiRequest<unknown>(invoicesUrl, {
    method: "GET",
    retry: false,
  });
  if (Array.isArray(payload)) {
    return payload.map(normalizeInvoice);
  }
  const r = toRaw(payload);
  if (Array.isArray(r.items)) {
    return (r.items as unknown[]).map(normalizeInvoice);
  }
  return [];
}

export async function getBillingContact(): Promise<BillingContact> {
  const { billingContactUrl } = getBillingEndpoints();
  if (!billingContactUrl)
    throw new BillingEndpointUnavailableError("billingContactEnabled");
  const payload = await apiRequest<unknown>(billingContactUrl, {
    method: "GET",
    retry: false,
  });
  return normalizeBillingContact(payload);
}

export async function updateBillingContact(
  data: Partial<BillingContact>,
): Promise<BillingContact> {
  const { updateBillingContactUrl } = getBillingEndpoints();
  if (!updateBillingContactUrl)
    throw new BillingEndpointUnavailableError("updateBillingContactEnabled");
  const payload = await apiRequest<unknown>(updateBillingContactUrl, {
    method: "PATCH",
    json: data,
    retry: false,
  });
  return normalizeBillingContact(payload);
}
