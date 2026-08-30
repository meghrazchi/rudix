import { z } from "zod";

export const permissionsAccessSummarySchema = z.object({
  total_users: z.number().int(),
  admin_users: z.number().int(),
  external_users: z.number().int(),
  external_users_is_heuristic: z.boolean(),
  broad_access_users: z.number().int(),
  permission_conflicts_open: z.number().int(),
  orphaned_grants: z.number().int(),
  expired_active_grants: z.number().int(),
  connector_acl_mismatches: z.number().int(),
  resources_without_owner: z.number().int(),
  unauthorized_access_attempts: z.number().int(),
  generated_at: z.string(),
});

export const roleCountRowSchema = z.object({
  role: z.string(),
  count: z.number().int(),
});

export const accessSourceCountRowSchema = z.object({
  access_source: z.string(),
  count: z.number().int(),
});

export const resourceTypeCountRowSchema = z.object({
  resource_type: z.string(),
  count: z.number().int(),
});

export const broadAccessUserRowSchema = z.object({
  user_id: z.string(),
  name: z.string(),
  email: z.string(),
  role: z.string(),
  reason: z.string(),
});

export const failedAccessAttemptPointSchema = z.object({
  date: z.string(),
  count: z.number().int(),
});

export const permissionsAccessChartsSchema = z.object({
  users_by_role: z.array(roleCountRowSchema),
  access_distribution: z.array(accessSourceCountRowSchema),
  conflicts_by_resource_type: z.array(resourceTypeCountRowSchema),
  broad_access_users: z.array(broadAccessUserRowSchema),
  failed_access_attempts: z.array(failedAccessAttemptPointSchema),
  generated_at: z.string(),
});

export const permissionsAccessRowSchema = z.object({
  id: z.string(),
  user_id: z.string().nullable(),
  user_name: z.string().nullable(),
  user_email: z.string().nullable(),
  role: z.string().nullable(),
  team: z.string().nullable(),
  resource_id: z.string().nullable(),
  resource_type: z.string(),
  resource_label: z.string().nullable(),
  access_level: z.string(),
  access_source: z.string(),
  conflict_status: z.string().nullable(),
  last_access: z.string().nullable(),
  grant_id: z.string().nullable(),
  conflict_id: z.string().nullable(),
});

export const permissionsAccessRowListSchema = z.object({
  items: z.array(permissionsAccessRowSchema),
  total: z.number().int(),
  page: z.number().int(),
  page_size: z.number().int(),
});

export type PermissionsAccessSummary = z.infer<
  typeof permissionsAccessSummarySchema
>;
export type PermissionsAccessCharts = z.infer<
  typeof permissionsAccessChartsSchema
>;
export type BroadAccessUserRow = z.infer<typeof broadAccessUserRowSchema>;
export type PermissionsAccessRow = z.infer<typeof permissionsAccessRowSchema>;
export type PermissionsAccessRowList = z.infer<
  typeof permissionsAccessRowListSchema
>;

export type PermissionsAccessQuery = {
  from?: string;
  to?: string;
  role?: string;
  access_source?: string;
  resource_type?: string;
  conflict_status?: string;
  search?: string;
  page?: number;
  page_size?: number;
};
