import { apiRequest } from "@/lib/api/request";

export type SSOType = "saml" | "oidc";

export type SSOConfig = {
  id: string;
  organization_id: string;
  sso_type: SSOType;
  domain: string;
  enabled: boolean;
  idp_metadata_url: string | null;
  sp_entity_id: string;
  sp_acs_url: string;
  idp_entity_id: string | null;
  idp_sso_url: string | null;
  attribute_mapping: Record<string, string>;
  last_test_at: string | null;
  last_test_result: "success" | "failure" | null;
  created_at: string;
  updated_at: string;
};

export type UpsertSSOConfigRequest = {
  domain: string;
  sso_type?: SSOType;
  enabled?: boolean;
  idp_metadata_url?: string | null;
  idp_metadata_xml?: string | null;
  idp_sso_url?: string | null;
  idp_entity_id?: string | null;
  idp_certificate?: string | null;
  attribute_mapping?: Record<string, string>;
  change_note?: string | null;
};

export type TestConnectionRequest = {
  idp_metadata_url?: string | null;
  idp_metadata_xml?: string | null;
  idp_sso_url?: string | null;
};

export type TestConnectionResponse = {
  success: boolean;
  result: "success" | "failure";
  detail: string;
  checked_at: string;
};

export type SSODiscoverRequest = {
  email: string;
};

export type SSODiscoverResponse = {
  sso_enabled: boolean;
  sso_type: SSOType | null;
  redirect_url: string | null;
  domain: string | null;
};

export async function getSSOConfig(): Promise<SSOConfig | null> {
  return apiRequest<SSOConfig | null>("/admin/sso");
}

export async function upsertSSOConfig(
  payload: UpsertSSOConfigRequest,
): Promise<SSOConfig> {
  return apiRequest<SSOConfig>("/admin/sso", {
    method: "PUT",
    json: payload,
  });
}

export async function deleteSSOConfig(): Promise<void> {
  return apiRequest<void>("/admin/sso", { method: "DELETE" });
}

export async function testSSOConnection(
  payload: TestConnectionRequest,
): Promise<TestConnectionResponse> {
  return apiRequest<TestConnectionResponse>("/admin/sso/test-connection", {
    method: "POST",
    json: payload,
  });
}

export async function discoverSSO(email: string): Promise<SSODiscoverResponse> {
  return apiRequest<SSODiscoverResponse>("/auth/sso/discover", {
    method: "POST",
    json: { email },
    attachAuth: false,
    attachOrganizationId: false,
    retry: false,
  });
}
