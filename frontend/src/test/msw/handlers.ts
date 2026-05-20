import { http, HttpResponse, type HttpHandler } from "msw";

import {
  MSW_FIXTURES_API_BASE_URL,
  mockAuditLogs,
  mockChatMessages,
  mockChatQueryResponse,
  mockChatSession,
  mockChatSessions,
  mockDocumentChunks,
  mockDocumentDetail,
  mockDocumentsList,
  mockDocumentStatus,
  mockEvaluationQuestions,
  mockEvaluationRunDetail,
  mockEvaluationRunQueued,
  mockEvaluationSets,
  mockHealth,
  mockPipelineNodeDetail,
  mockPipelineRunGraph,
  mockPipelineRunResolve,
  mockPipelineSteps,
  mockReadinessDegraded,
  mockTopBarNotifications,
  mockUsageSummary,
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
  ];
}
