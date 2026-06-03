import { http, HttpResponse, type HttpHandler } from "msw";

import {
  MSW_FIXTURES_API_BASE_URL,
  mockAuditLogs,
  mockBillingContact,
  mockBillingPlanInfo,
  mockBillingPortalSession,
  mockBillingQuotas,
  mockBillingUsageSummary,
  mockChatMessages,
  mockChatQueryResponse,
  mockChatSession,
  mockChatSessions,
  mockChunkingProfilePreview,
  mockChunkingProfiles,
  mockChunkingStrategyCatalog,
  mockDocumentChunks,
  mockDocumentDetail,
  mockDocumentsList,
  mockDocumentStatus,
  mockEvaluationQuestions,
  mockEvaluationRunDetail,
  mockEvaluationRunQueued,
  mockEvaluationSets,
  mockHealth,
  mockIngestionDefaults,
  mockInvoices,
  mockLoginPolicy,
  mockOrganizationProfile,
  mockOrganizationSettings,
  mockPipelineNodeDetail,
  mockPipelineRunGraph,
  mockPipelineRunResolve,
  mockPipelineSteps,
  mockReadinessDegraded,
  mockSecurityAuditEvents,
  mockSecurityPosture,
  mockSecuritySessions,
  mockTopBarNotifications,
  mockUsageSummary,
  mockUserPreferences,
  mockUserProfile,
} from "@/test/msw/fixtures";
import type { DocumentStatus } from "@/lib/api/documents";

type MockApiHandlersOptions = {
  apiBaseUrl?: string;
  healthMode?: "healthy" | "degraded";
};

function parsePaginationParams(requestUrl: string): {
  limit: number;
  offset: number;
} {
  const url = new URL(requestUrl);
  const limit = Math.max(
    1,
    Number.parseInt(url.searchParams.get("limit") ?? "20", 10) || 20,
  );
  const offset = Math.max(
    0,
    Number.parseInt(url.searchParams.get("offset") ?? "0", 10) || 0,
  );
  return { limit, offset };
}

function filterDocumentsByStatus(status: string | null) {
  const requested = status as DocumentStatus | null;
  if (!requested) {
    return mockDocumentsList.items;
  }
  return mockDocumentsList.items.filter((item) => item.status === requested);
}

function pageItems<T>(items: T[], limit: number, offset: number): T[] {
  return items.slice(offset, offset + limit);
}

export function createMockApiHandlers(
  options: MockApiHandlersOptions = {},
): HttpHandler[] {
  const apiBaseUrl = options.apiBaseUrl ?? MSW_FIXTURES_API_BASE_URL;
  const healthResponse =
    options.healthMode === "degraded" ? mockReadinessDegraded : mockHealth;

  return [
    http.get(`${apiBaseUrl}/documents`, ({ request }) => {
      const url = new URL(request.url);
      const { limit, offset } = parsePaginationParams(request.url);
      const statusFilter = url.searchParams.get("status");
      const filtered = filterDocumentsByStatus(statusFilter);
      return HttpResponse.json({
        ...mockDocumentsList,
        items: pageItems(filtered, limit, offset),
        total: filtered.length,
        limit,
        offset,
        status: statusFilter as DocumentStatus | null,
      });
    }),
    http.get(`${apiBaseUrl}/documents/:documentId`, () =>
      HttpResponse.json(mockDocumentDetail),
    ),
    http.get(`${apiBaseUrl}/documents/:documentId/status`, () =>
      HttpResponse.json(mockDocumentStatus),
    ),
    http.get(`${apiBaseUrl}/documents/:documentId/chunks`, ({ request }) => {
      const { limit, offset } = parsePaginationParams(request.url);
      return HttpResponse.json({
        ...mockDocumentChunks,
        items: pageItems(mockDocumentChunks.items, limit, offset),
        total: mockDocumentChunks.items.length,
        limit,
        offset,
      });
    }),
    http.get(`${apiBaseUrl}/admin/chunking-profiles/strategies`, () =>
      HttpResponse.json(mockChunkingStrategyCatalog),
    ),
    http.get(`${apiBaseUrl}/admin/chunking-profiles`, () =>
      HttpResponse.json(mockChunkingProfiles),
    ),
    http.post(`${apiBaseUrl}/admin/chunking-profiles/preview`, () =>
      HttpResponse.json(mockChunkingProfilePreview),
    ),
    http.post(`${apiBaseUrl}/documents/upload`, () =>
      HttpResponse.json(
        {
          document_id: "doc-uploaded-1",
          filename: "Uploaded.pdf",
          status: "uploaded",
          queue_status: "queued",
          checksum: "sha256:uploaded",
          message: "Document uploaded and queued for processing.",
        },
        { status: 201 },
      ),
    ),
    http.get(`${apiBaseUrl}/chat/sessions`, ({ request }) => {
      const { limit, offset } = parsePaginationParams(request.url);
      return HttpResponse.json({
        ...mockChatSessions,
        items: pageItems(mockChatSessions.items, limit, offset),
        total: mockChatSessions.items.length,
        limit,
        offset,
      });
    }),
    http.post(`${apiBaseUrl}/chat/sessions`, () =>
      HttpResponse.json(mockChatSession, { status: 201 }),
    ),
    http.get(
      `${apiBaseUrl}/chat/sessions/:sessionId/messages`,
      ({ request }) => {
        const { limit, offset } = parsePaginationParams(request.url);
        return HttpResponse.json({
          ...mockChatMessages,
          items: pageItems(mockChatMessages.items, limit, offset),
          total: mockChatMessages.items.length,
          limit,
          offset,
        });
      },
    ),
    http.post(`${apiBaseUrl}/chat`, () =>
      HttpResponse.json(mockChatQueryResponse),
    ),
    http.get(`${apiBaseUrl}/evaluation-sets`, ({ request }) => {
      const { limit, offset } = parsePaginationParams(request.url);
      return HttpResponse.json({
        ...mockEvaluationSets,
        items: pageItems(mockEvaluationSets.items, limit, offset),
        total: mockEvaluationSets.items.length,
        limit,
        offset,
      });
    }),
    http.post(`${apiBaseUrl}/evaluation-sets`, () =>
      HttpResponse.json(mockEvaluationSets.items[0], { status: 201 }),
    ),
    http.get(
      `${apiBaseUrl}/evaluation-sets/:evaluationSetId/questions`,
      ({ request }) => {
        const { limit, offset } = parsePaginationParams(request.url);
        return HttpResponse.json({
          ...mockEvaluationQuestions,
          items: pageItems(mockEvaluationQuestions.items, limit, offset),
          total: mockEvaluationQuestions.items.length,
          limit,
          offset,
        });
      },
    ),
    http.post(`${apiBaseUrl}/evaluation-sets/:evaluationSetId/questions`, () =>
      HttpResponse.json(mockEvaluationQuestions.items[0], { status: 201 }),
    ),
    http.post(`${apiBaseUrl}/evaluations/run`, () =>
      HttpResponse.json(mockEvaluationRunQueued, { status: 202 }),
    ),
    http.get(`${apiBaseUrl}/evaluations/runs/:evaluationRunId`, () =>
      HttpResponse.json(mockEvaluationRunDetail),
    ),
    http.get(`${apiBaseUrl}/pipeline/steps`, () =>
      HttpResponse.json(mockPipelineSteps),
    ),
    http.get(`${apiBaseUrl}/pipeline/runs/resolve`, () =>
      HttpResponse.json(mockPipelineRunResolve),
    ),
    http.get(`${apiBaseUrl}/pipeline/runs/:runId`, () =>
      HttpResponse.json(mockPipelineRunGraph),
    ),
    http.get(`${apiBaseUrl}/pipeline/runs/:runId/nodes/:nodeId`, () =>
      HttpResponse.json(mockPipelineNodeDetail),
    ),
    http.get(`${apiBaseUrl}/health`, () => HttpResponse.json(healthResponse)),
    http.get(`${apiBaseUrl}/ready`, () => HttpResponse.json(healthResponse)),
    http.get(`${apiBaseUrl}/admin/usage`, () =>
      HttpResponse.json(mockUsageSummary),
    ),
    http.get(`${apiBaseUrl}/admin/audit-logs`, ({ request }) => {
      const { limit, offset } = parsePaginationParams(request.url);
      return HttpResponse.json({
        ...mockAuditLogs,
        items: pageItems(mockAuditLogs.items, limit, offset),
        total: mockAuditLogs.items.length,
        limit,
        offset,
      });
    }),
    http.get(`${apiBaseUrl}/notifications`, () =>
      HttpResponse.json(mockTopBarNotifications),
    ),

    // ── Settings: Profile ────────────────────────────────────────────────────
    http.get(`${apiBaseUrl}/me`, () => HttpResponse.json(mockUserProfile)),
    http.patch(`${apiBaseUrl}/me`, () => HttpResponse.json(mockUserProfile)),
    http.get(`${apiBaseUrl}/me/preferences`, () =>
      HttpResponse.json(mockUserPreferences),
    ),
    http.patch(`${apiBaseUrl}/me/preferences`, () =>
      HttpResponse.json(mockUserPreferences),
    ),
    http.post(`${apiBaseUrl}/me/sign-out-all`, () =>
      new HttpResponse(null, { status: 204 }),
    ),
    http.delete(`${apiBaseUrl}/me`, () =>
      new HttpResponse(null, { status: 204 }),
    ),

    // ── Settings: Security ───────────────────────────────────────────────────
    http.get(`${apiBaseUrl}/security/sessions`, () =>
      HttpResponse.json({ items: mockSecuritySessions }),
    ),
    http.delete(`${apiBaseUrl}/security/sessions/:sessionId`, () =>
      new HttpResponse(null, { status: 204 }),
    ),
    http.post(`${apiBaseUrl}/security/sessions/revoke-all`, () =>
      HttpResponse.json({ revoked_count: 1 }),
    ),
    http.get(`${apiBaseUrl}/security/login-policy`, () =>
      HttpResponse.json(mockLoginPolicy),
    ),
    http.patch(`${apiBaseUrl}/security/login-policy`, () =>
      HttpResponse.json(mockLoginPolicy),
    ),
    http.get(`${apiBaseUrl}/security/posture`, () =>
      HttpResponse.json(mockSecurityPosture),
    ),
    http.get(`${apiBaseUrl}/security/audit-events`, () =>
      HttpResponse.json({ items: mockSecurityAuditEvents }),
    ),

    // ── Settings: Organization ───────────────────────────────────────────────
    http.get(`${apiBaseUrl}/organization`, () =>
      HttpResponse.json(mockOrganizationProfile),
    ),
    http.patch(`${apiBaseUrl}/organization`, () =>
      HttpResponse.json(mockOrganizationProfile),
    ),
    http.get(`${apiBaseUrl}/organization/settings`, () =>
      HttpResponse.json(mockOrganizationSettings),
    ),
    http.patch(`${apiBaseUrl}/organization/settings`, () =>
      HttpResponse.json(mockOrganizationSettings),
    ),
    http.get(`${apiBaseUrl}/organization/ingestion`, () =>
      HttpResponse.json(mockIngestionDefaults),
    ),
    http.patch(`${apiBaseUrl}/organization/ingestion`, () =>
      HttpResponse.json(mockIngestionDefaults),
    ),

    // ── Settings: Billing ────────────────────────────────────────────────────
    http.get(`${apiBaseUrl}/billing/plan`, () =>
      HttpResponse.json(mockBillingPlanInfo),
    ),
    http.get(`${apiBaseUrl}/billing/usage`, () =>
      HttpResponse.json(mockBillingUsageSummary),
    ),
    http.get(`${apiBaseUrl}/billing/quotas`, () =>
      HttpResponse.json(mockBillingQuotas),
    ),
    http.get(`${apiBaseUrl}/billing/invoices`, () =>
      HttpResponse.json(mockInvoices),
    ),
    http.get(`${apiBaseUrl}/billing/contact`, () =>
      HttpResponse.json(mockBillingContact),
    ),
    http.patch(`${apiBaseUrl}/billing/contact`, () =>
      HttpResponse.json(mockBillingContact),
    ),
    http.post(`${apiBaseUrl}/billing/portal-session`, () =>
      HttpResponse.json(mockBillingPortalSession, { status: 201 }),
    ),
  ];
}
