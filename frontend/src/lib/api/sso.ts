import type { Overlay, Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type SSOType = "saml" | "oidc";

export type SSOConfig = Overlay<
  Served<Schemas["SSOConfigResponse"]>,
  { sso_type: SSOType }
>;

export type UpsertSSOConfigRequest = Schemas["UpsertSSOConfigRequest"];

export type TestConnectionRequest = Schemas["TestConnectionRequest"];

export type TestConnectionResponse = Served<Schemas["TestConnectionResponse"]>;

export type SSODiscoverRequest = Schemas["SSODiscoverRequest"];

export type SSODiscoverResponse = Served<Schemas["SSODiscoverResponse"]>;

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
