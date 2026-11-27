import type { ConnectorConnectionSummary } from "@/lib/api/connectors";

export function formatConnectorSourceRoots(
  providerKey: string,
  authConfig: Record<string, unknown>,
): string[] {
  const rawValues =
    providerKey === "confluence"
      ? authConfig.space_keys
      : providerKey === "google_drive"
        ? [
            ...(Array.isArray(authConfig.folder_ids)
              ? authConfig.folder_ids
              : []),
            ...(Array.isArray(authConfig.drive_ids)
              ? authConfig.drive_ids
              : []),
          ]
        : [];

  if (!Array.isArray(rawValues)) {
    return [];
  }
  return rawValues
    .map((value) => String(value).trim())
    .filter((value) => value.length > 0);
}

export function getConnectorProviderLabel(providerKey: string): string {
  if (providerKey === "confluence") return "Confluence";
  if (providerKey === "google_drive") return "Google Drive";
  return providerKey
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function buildConnectorRootChips(
  connection: ConnectorConnectionSummary,
): { id: string; label: string }[] {
  const roots = formatConnectorSourceRoots(
    connection.provider_key,
    connection.auth_config ?? {},
  );
  return roots.map((root) => ({
    id: `${connection.id}:${root}`,
    label: root,
  }));
}
