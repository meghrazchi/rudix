"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import {
  hasCapability,
  listProviders,
  type ConnectorCapabilityKey,
  type ProviderSummary,
} from "@/lib/api/connector-providers";
import { queryKeys } from "@/lib/api/query";

// ---------------------------------------------------------------------------
// Capability display metadata
// ---------------------------------------------------------------------------

type CapabilityMeta = {
  label?: string;
  description?: string;
  color: string;
};

const CAPABILITY_META: Record<ConnectorCapabilityKey, CapabilityMeta> = {
  delta_sync: {
    label: "Incremental sync",
    description: "Only changed items are fetched after the first full sync",
    color: "bg-blue-100 text-blue-800",
  },
  webhooks: {
    label: "Real-time updates",
    description: "Provider can push change notifications via webhooks",
    color: "bg-purple-100 text-purple-800",
  },
  acls: {
    label: "Permission-aware",
    description: "Access control lists are synced alongside content",
    color: "bg-indigo-100 text-indigo-800",
  },
  attachments: {
    label: "Attachments",
    description: "File attachments on items are included in sync",
    color: "bg-green-100 text-green-800",
  },
  comments: {
    label: "Comments",
    description: "Comments on items are included in sync",
    color: "bg-teal-100 text-teal-800",
  },
  folders: {
    label: "Folder hierarchy",
    description: "Folder and space structure is preserved during sync",
    color: "bg-amber-100 text-amber-800",
  },
  export_formats: {
    label: "Export formats",
    description:
      "Multiple content export formats are available for this provider",
    color: "bg-orange-100 text-orange-800",
  },
  files: {
    label: "Files",
    description:
      "File objects are indexed through the shared document pipeline",
    color: "bg-green-100 text-green-800",
  },
  deletions: {
    label: "Deletions",
    description: "Deleted source items are propagated as tombstones",
    color: "bg-rose-100 text-rose-800",
  },
  deep_links: {
    label: "Deep links",
    description: "Citations can open the original source item directly",
    color: "bg-sky-100 text-sky-800",
  },
  rate_limits: {
    label: "Rate-limit aware",
    description:
      "Sync respects the provider's API rate limits and retries automatically",
    color: "bg-gray-100 text-gray-700",
  },
};

// ---------------------------------------------------------------------------
// CapabilityBadge — renders a single capability chip
// ---------------------------------------------------------------------------

type CapabilityBadgeProps = {
  capability: ConnectorCapabilityKey;
  showTooltip?: boolean;
};

export function CapabilityBadge({
  capability,
  showTooltip = true,
}: CapabilityBadgeProps) {
  const t = useTranslations("connectors.setup.capabilities");
  const meta = CAPABILITY_META[capability];
  if (!meta) return null;

  return (
    <span
      title={showTooltip ? t(`${capability}.description`) : undefined}
      className={`inline-flex cursor-default items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${meta.color}`}
    >
      {t(`${capability}.label`)}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ProviderCapabilityBadges — renders all capability badges for a provider
// ---------------------------------------------------------------------------

type ProviderCapabilityBadgesProps = {
  provider: ProviderSummary;
  onlyCapabilities?: ConnectorCapabilityKey[];
  className?: string;
};

export function ProviderCapabilityBadges({
  provider,
  onlyCapabilities,
  className = "",
}: ProviderCapabilityBadgesProps) {
  const caps = provider.capabilities.capabilities;
  const toShow = onlyCapabilities
    ? caps.filter((c) => onlyCapabilities.includes(c))
    : caps;

  if (toShow.length === 0) return null;

  return (
    <div className={`flex flex-wrap gap-1.5 ${className}`}>
      {toShow.map((cap) => (
        <CapabilityBadge key={cap} capability={cap} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ProviderSetupHints — shows setup-time hints driven by provider capabilities
// ---------------------------------------------------------------------------

type ProviderSetupHintsProps = {
  provider: ProviderSummary;
};

export function ProviderSetupHints({ provider }: ProviderSetupHintsProps) {
  const hints: string[] = [];

  if (hasCapability(provider, "delta_sync")) {
    hints.push(
      "Incremental syncs will run after the initial full sync to reduce API usage.",
    );
  }
  if (hasCapability(provider, "webhooks")) {
    hints.push(
      "Configure a webhook in your provider settings for near-real-time updates.",
    );
  }
  if (hasCapability(provider, "acls")) {
    hints.push(
      "Permission data will be synced. Documents will respect the access control rules from the source.",
    );
  }
  if (provider.capabilities.export_formats.length > 1) {
    hints.push(
      `This provider supports ${provider.capabilities.export_formats.length} export formats. Choose the one that best suits your content.`,
    );
  }

  if (hints.length === 0) return null;

  return (
    <ul className="mt-2 space-y-1 text-xs text-gray-600">
      {hints.map((hint, i) => (
        <li key={i} className="flex gap-1.5">
          <span className="mt-0.5 shrink-0 text-gray-400">•</span>
          {hint}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// ProviderCard — full summary card for the provider picker
// ---------------------------------------------------------------------------

type ProviderCardProps = {
  provider: ProviderSummary;
  selected?: boolean;
  onClick?: () => void;
};

export function ProviderCard({
  provider,
  selected = false,
  onClick,
}: ProviderCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-lg border p-4 text-left transition-colors ${
        selected
          ? "border-indigo-500 bg-indigo-50 ring-1 ring-indigo-500"
          : "border-gray-200 bg-white hover:border-gray-300 hover:bg-gray-50"
      }`}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-semibold text-gray-900">
            {provider.display_name}
          </p>
          <p className="mt-0.5 text-xs text-gray-500 capitalize">
            {provider.capabilities.auth_type}
          </p>
        </div>
        {provider.has_oauth && (
          <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-700">
            OAuth
          </span>
        )}
      </div>
      <ProviderCapabilityBadges provider={provider} className="mt-3" />
    </button>
  );
}

// ---------------------------------------------------------------------------
// ProviderPicker — fetches all providers and renders a selection grid
// ---------------------------------------------------------------------------

type ProviderPickerProps = {
  selectedKey: string | null;
  onSelect: (providerKey: string) => void;
};

export function ProviderPicker({ selectedKey, onSelect }: ProviderPickerProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.connectorProviders,
    queryFn: listProviders,
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) {
    return <p className="text-sm text-gray-500">Loading providers…</p>;
  }
  if (isError || !data) {
    return <p className="text-sm text-red-600">Failed to load providers.</p>;
  }

  const enabled = data.items.filter((p) => p.enabled_by_default);

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {enabled.map((provider) => (
        <ProviderCard
          key={provider.key}
          provider={provider}
          selected={provider.key === selectedKey}
          onClick={() => onSelect(provider.key)}
        />
      ))}
    </div>
  );
}
