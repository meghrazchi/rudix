import { apiRequest } from "@/lib/api/request";
import {
  permissionsAccessChartsSchema,
  permissionsAccessRowListSchema,
  permissionsAccessSummarySchema,
  type PermissionsAccessCharts,
  type PermissionsAccessQuery,
  type PermissionsAccessRowList,
  type PermissionsAccessSummary,
} from "@/lib/schemas/permissions-access";

const PERMISSIONS_ACCESS_BASE_PATH = "/admin/permissions-access";

function toQueryRecord(query: PermissionsAccessQuery) {
  return {
    from: query.from,
    to: query.to,
    role: query.role,
    access_source: query.access_source,
    resource_type: query.resource_type,
    conflict_status: query.conflict_status,
    search: query.search,
    page: query.page,
    page_size: query.page_size,
  };
}

export async function getPermissionsAccessSummary(
  query: PermissionsAccessQuery = {},
): Promise<PermissionsAccessSummary> {
  const payload = await apiRequest<unknown>(
    `${PERMISSIONS_ACCESS_BASE_PATH}/summary`,
    {
      method: "GET",
      query: toQueryRecord(query),
      retry: false,
    },
  );
  return permissionsAccessSummarySchema.parse(payload);
}

export async function getPermissionsAccessCharts(
  query: PermissionsAccessQuery = {},
): Promise<PermissionsAccessCharts> {
  const payload = await apiRequest<unknown>(
    `${PERMISSIONS_ACCESS_BASE_PATH}/charts`,
    {
      method: "GET",
      query: toQueryRecord(query),
      retry: false,
    },
  );
  return permissionsAccessChartsSchema.parse(payload);
}

export async function listPermissionsAccessRows(
  query: PermissionsAccessQuery = {},
): Promise<PermissionsAccessRowList> {
  const payload = await apiRequest<unknown>(
    `${PERMISSIONS_ACCESS_BASE_PATH}/rows`,
    {
      method: "GET",
      query: toQueryRecord(query),
      retry: false,
    },
  );
  return permissionsAccessRowListSchema.parse(payload);
}

export async function exportPermissionsAccessReport(
  query: PermissionsAccessQuery = {},
): Promise<Blob> {
  return apiRequest<Blob>(`${PERMISSIONS_ACCESS_BASE_PATH}/export`, {
    method: "GET",
    query: toQueryRecord(query),
    responseType: "blob",
    retry: false,
  });
}
