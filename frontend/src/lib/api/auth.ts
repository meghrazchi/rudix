import { apiRequest } from "@/lib/api/request";

export type EffectivePermissionsResponse = {
  permissions: string[];
  role: string;
  custom_role_id: string | null;
};

function normalizeEffectivePermissions(value: unknown): EffectivePermissionsResponse {
  const raw =
    value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  return {
    permissions: Array.isArray(raw.permissions)
      ? (raw.permissions as unknown[]).filter(
          (p): p is string => typeof p === "string",
        )
      : [],
    role: typeof raw.role === "string" ? raw.role : "",
    custom_role_id:
      typeof raw.custom_role_id === "string" ? raw.custom_role_id : null,
  };
}

export async function fetchEffectivePermissions(): Promise<EffectivePermissionsResponse> {
  const payload = await apiRequest<unknown>("/auth/effective-permissions", {
    method: "GET",
    retry: false,
  });
  return normalizeEffectivePermissions(payload);
}
