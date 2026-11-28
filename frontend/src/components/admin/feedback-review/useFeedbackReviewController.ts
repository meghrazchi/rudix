import { useCallback, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  buildFeedbackReviewExportUrl,
  listFeedbackReviewItems,
  redactFeedbackDiagnostics,
  updateFeedbackReviewItem,
  type FeedbackReviewItemResponse,
  type FeedbackReviewListParams,
  type FeedbackReviewStatus,
  type FeedbackSeverity,
  type UpdateReviewItemPayload,
} from "@/lib/api/feedback-review";
import type { FeedbackCategory } from "@/lib/api/feedback";
import { queryKeys } from "@/lib/api/query";
import { canViewFeedbackReview } from "@/lib/dashboard";
import { isForbiddenError } from "@/lib/forbidden";
import { useAuthSession } from "@/lib/use-auth-session";
import { useOverlayFocus } from "@/lib/use-overlay-focus";
import {
  PAGE_LIMIT,
  type AppliedFilters,
  DEFAULT_FILTERS,
  trimToNull,
  parseNullableNumber,
} from "@/components/admin/feedback-review/feedbackReviewShared";

export function useFeedbackReviewController() {
  const t = useTranslations("adminFeedbackReview");
  const { state } = useAuthSession();
  const role = state.session?.role;
  const isAdminUser = canViewFeedbackReview(role);
  const queryClient = useQueryClient();

  const [statusInput, setStatusInput] = useState<FeedbackReviewStatus | "">("");
  const [categoryInput, setCategoryInput] = useState("");
  const [workspaceInput, setWorkspaceInput] = useState("");
  const [documentInput, setDocumentInput] = useState("");
  const [modelInput, setModelInput] = useState("");
  const [confidenceMinInput, setConfidenceMinInput] = useState("");
  const [confidenceMaxInput, setConfidenceMaxInput] = useState("");
  const [severityInput, setSeverityInput] = useState<FeedbackSeverity | "">("");
  const [ratingInput, setRatingInput] = useState<"up" | "down" | "">("");
  const [reasonInput, setReasonInput] = useState("");
  const [appliedFilters, setAppliedFilters] =
    useState<AppliedFilters>(DEFAULT_FILTERS);
  const [offset, setOffset] = useState(0);
  const [selectedItem, setSelectedItem] =
    useState<FeedbackReviewItemResponse | null>(null);
  const [convertReviewId, setConvertReviewId] = useState<string | null>(null);
  const [saveKnowledgeCardReviewId, setSaveKnowledgeCardReviewId] = useState<
    string | null
  >(null);

  const panelRef = useRef<HTMLElement | null>(null);
  const tableHostRef = useRef<HTMLDivElement | null>(null);

  const closePanel = useCallback(() => setSelectedItem(null), []);
  useOverlayFocus({
    isOpen: selectedItem != null,
    containerRef: panelRef,
    onClose: closePanel,
    lockBodyScroll: false,
  });

  const queryParams = useMemo(
    (): FeedbackReviewListParams => ({
      status: appliedFilters.status ?? undefined,
      category: appliedFilters.category ?? undefined,
      workspace_id: appliedFilters.workspaceId ?? undefined,
      document_id: appliedFilters.documentId ?? undefined,
      model_name: appliedFilters.modelName ?? undefined,
      confidence_min:
        parseNullableNumber(appliedFilters.confidenceMin) ?? undefined,
      confidence_max:
        parseNullableNumber(appliedFilters.confidenceMax) ?? undefined,
      severity: appliedFilters.severity ?? undefined,
      rating: appliedFilters.rating ?? undefined,
      reason: appliedFilters.reason ?? undefined,
      limit: PAGE_LIMIT,
      offset,
    }),
    [appliedFilters, offset],
  );

  const listQuery = useQuery({
    queryKey: queryKeys.feedbackReview.list(
      queryParams as Record<string, unknown>,
    ),
    queryFn: () => listFeedbackReviewItems(queryParams),
    enabled: isAdminUser,
  });

  const updateMutation = useMutation({
    mutationFn: ({
      reviewId,
      payload,
    }: {
      reviewId: string;
      payload: UpdateReviewItemPayload;
    }) => updateFeedbackReviewItem(reviewId, payload),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedbackReview.all,
      });
      setSelectedItem(updated);
    },
  });

  const redactMutation = useMutation({
    mutationFn: (feedbackId: string) => redactFeedbackDiagnostics(feedbackId),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.feedbackReview.all,
      });
      if (selectedItem && updated.feedback_id === selectedItem.feedback_id) {
        setSelectedItem(updated);
      }
    },
  });

  const forbiddenError =
    listQuery.isError && isForbiddenError(listQuery.error)
      ? listQuery.error
      : null;

  const data = listQuery.data;
  const rows = data?.items ?? [];
  const pageTotal = data?.total ?? 0;
  const pageStart = pageTotal === 0 ? 0 : offset + 1;
  const pageEnd =
    pageTotal === 0 ? 0 : Math.min(offset + PAGE_LIMIT, pageTotal);
  const hasPreviousPage = offset > 0;
  const hasNextPage = offset + PAGE_LIMIT < pageTotal;

  const openCount = rows.filter(
    (r) =>
      r.status === "new" || r.status === "triaged" || r.status === "accepted",
  ).length;
  const highSeverityCount = rows.filter((r) => r.severity === "high").length;
  const resolvedCount = rows.filter(
    (r) =>
      r.status === "resolved" ||
      r.status === "fixed" ||
      r.status === "converted_to_evaluation" ||
      r.status === "eval_created" ||
      r.status === "rejected" ||
      r.status === "duplicate",
  ).length;

  function applyFilters(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const category = trimToNull(categoryInput) as FeedbackCategory | null;
    setOffset(0);
    setAppliedFilters({
      status: (statusInput as FeedbackReviewStatus) || null,
      category,
      workspaceId: trimToNull(workspaceInput),
      documentId: trimToNull(documentInput),
      modelName: trimToNull(modelInput),
      confidenceMin: trimToNull(confidenceMinInput),
      confidenceMax: trimToNull(confidenceMaxInput),
      severity: (severityInput as FeedbackSeverity) || null,
      rating: (ratingInput as "up" | "down") || null,
      reason: trimToNull(reasonInput),
    });
  }

  function clearFilters() {
    setStatusInput("");
    setCategoryInput("");
    setWorkspaceInput("");
    setDocumentInput("");
    setModelInput("");
    setConfidenceMinInput("");
    setConfidenceMaxInput("");
    setSeverityInput("");
    setRatingInput("");
    setReasonInput("");
    setOffset(0);
    setAppliedFilters(DEFAULT_FILTERS);
  }

  const exportUrl = buildFeedbackReviewExportUrl({
    status: appliedFilters.status,
    category: appliedFilters.category ?? undefined,
    workspace_id: appliedFilters.workspaceId ?? undefined,
    document_id: appliedFilters.documentId ?? undefined,
    model_name: appliedFilters.modelName ?? undefined,
    confidence_min:
      parseNullableNumber(appliedFilters.confidenceMin) ?? undefined,
    confidence_max:
      parseNullableNumber(appliedFilters.confidenceMax) ?? undefined,
    severity: appliedFilters.severity,
    rating: appliedFilters.rating,
    reason: appliedFilters.reason,
  });
  return {
    t,
    state,
    role,
    isAdminUser,
    queryClient,
    statusInput,
    setStatusInput,
    categoryInput,
    setCategoryInput,
    workspaceInput,
    setWorkspaceInput,
    documentInput,
    setDocumentInput,
    modelInput,
    setModelInput,
    confidenceMinInput,
    setConfidenceMinInput,
    confidenceMaxInput,
    setConfidenceMaxInput,
    severityInput,
    setSeverityInput,
    ratingInput,
    setRatingInput,
    reasonInput,
    setReasonInput,
    appliedFilters,
    setAppliedFilters,
    offset,
    setOffset,
    selectedItem,
    setSelectedItem,
    convertReviewId,
    setConvertReviewId,
    saveKnowledgeCardReviewId,
    setSaveKnowledgeCardReviewId,
    panelRef,
    tableHostRef,
    closePanel,
    queryParams,
    listQuery,
    updateMutation,
    redactMutation,
    forbiddenError,
    data,
    rows,
    pageTotal,
    pageStart,
    pageEnd,
    hasPreviousPage,
    hasNextPage,
    openCount,
    highSeverityCount,
    resolvedCount,
    applyFilters,
    clearFilters,
    exportUrl,
  };
}
