import { setupServer, type SetupServer } from "msw/node";

import { createMockApiHandlers } from "@/test/msw/handlers";

type CreateMockApiServerOptions = Parameters<typeof createMockApiHandlers>[0];

export function createMockApiServer(options: CreateMockApiServerOptions = {}): SetupServer {
  return setupServer(...createMockApiHandlers(options));
}
