export type ObservabilityLevel = "info" | "warning" | "error";

export type FrontendBreadcrumb = {
  category: string;
  message: string;
  level?: ObservabilityLevel;
  data?: Record<string, unknown>;
  timestamp?: number;
};

export type FrontendObservabilityContext = {
  feature?: string;
  route?: string;
  requestId?: string | null;
  traceId?: string | null;
  tags?: Record<string, string | number | boolean | null | undefined>;
  extra?: Record<string, unknown>;
  level?: ObservabilityLevel;
};
