import { apiRequest } from "@/lib/api/request";

export type ChatToolAvailabilityEntry = {
  name: string;
  purpose: string;
  required_permission: string;
  allowed_resource_types: string[];
  approval_required: boolean;
  feature_flag: string | null;
  required_roles: string[];
  feature_available: boolean;
  org_policy_enabled: boolean;
  available: boolean;
};

export type ChatToolsAvailabilityResponse = {
  organization_id: string;
  feature_enabled: boolean;
  tools: ChatToolAvailabilityEntry[];
};

export async function getChatToolsAvailability(): Promise<ChatToolsAvailabilityResponse> {
  return apiRequest<ChatToolsAvailabilityResponse>("/admin/chat-tools/availability");
}
