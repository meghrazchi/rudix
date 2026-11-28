import type { Served } from "@/lib/api/schema-helpers";
import type { components } from "@/lib/api/generated/schema";

import { apiRequest } from "@/lib/api/request";

type Schemas = components["schemas"];

export type ChatToolAvailabilityEntry = Served<
  Schemas["ChatToolAvailabilityEntry"]
>;

export type ChatToolsAvailabilityResponse = Served<
  Schemas["ChatToolsAvailabilityResponse"]
>;

export async function getChatToolsAvailability(): Promise<ChatToolsAvailabilityResponse> {
  return apiRequest<ChatToolsAvailabilityResponse>(
    "/admin/chat-tools/availability",
  );
}
