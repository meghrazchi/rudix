"""Permission-aware adaptive tool orchestration for the chat pipeline (F342).

ChatToolOrchestrator selects and authorizes tool capabilities based on:
  1. Planner strategy relevance — only tools relevant to the question strategy run.
  2. Feature flag availability — tools gated by disabled features are skipped.
  3. Principal role membership — required roles are enforced per tool.
  4. Org-level policy override — admins can disable specific tools org-wide.

The orchestrator is pure (no async, no DB) — callers resolve disabled_tool_names
from AgentToolPolicyRepository before calling orchestrate(). Authorization decisions
are recorded per-tool and returned as ToolOrchestrationResult for trust metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from app.auth.models import AuthenticatedPrincipal
from app.core.logging import get_logger
from app.models.enums import OrganizationRole
from app.models.permissions import ROLE_PERMISSIONS

_logger = get_logger("services.chat.tool_orchestrator")

_ALL_STRATEGIES: frozenset[str] = frozenset(
    {
        "standard",
        "legal_compliance",
        "policy_lookup",
        "comparison",
        "table_heavy",
        "graph_assisted",
        "connector_search",
        "troubleshooting",
        "summary",
    }
)

_ALL_ROLES: frozenset[str] = frozenset(r.value for r in OrganizationRole)
_ELEVATED_ROLES: frozenset[str] = frozenset(
    {OrganizationRole.owner.value, OrganizationRole.admin.value}
)


# ---------------------------------------------------------------------------
# Capability spec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChatToolCapability:
    """Declarative specification for a single chat-pipeline tool capability."""

    name: str
    purpose: str
    required_permission: str
    allowed_resource_types: list[str]
    approval_required: bool
    feature_flag: str | None
    relevant_strategies: frozenset[str]
    required_roles: frozenset[str] = field(default_factory=lambda: _ALL_ROLES)
    timeout_ms: int = 8_000
    max_calls_per_run: int = 20


CHAT_TOOL_CAPABILITIES: tuple[ChatToolCapability, ...] = (
    ChatToolCapability(
        name="document_search",
        purpose="Search accessible documents by query and rank by relevance.",
        required_permission="documents:view",
        allowed_resource_types=["document"],
        approval_required=False,
        feature_flag=None,
        relevant_strategies=_ALL_STRATEGIES,
        required_roles=_ALL_ROLES,
    ),
    ChatToolCapability(
        name="collection_search",
        purpose="Search within scoped knowledge base collections.",
        required_permission="chat:use_collections",
        allowed_resource_types=["collection", "document"],
        approval_required=False,
        feature_flag=None,
        relevant_strategies=frozenset(
            {"standard", "policy_lookup", "comparison", "legal_compliance", "summary"}
        ),
        required_roles=_ALL_ROLES,
    ),
    ChatToolCapability(
        name="connector_search",
        purpose="Search connector-backed sources such as Google Drive or Confluence.",
        required_permission="documents:view",
        allowed_resource_types=["connector", "document"],
        approval_required=False,
        feature_flag="feature_enable_connectors",
        relevant_strategies=frozenset({"connector_search", "standard", "troubleshooting"}),
        required_roles=_ALL_ROLES,
    ),
    ChatToolCapability(
        name="graph_search",
        purpose="Query the Enterprise Knowledge Graph for entities and relationships.",
        required_permission="graph:view",
        allowed_resource_types=["graph_entity", "graph_relation"],
        approval_required=False,
        feature_flag="feature_enable_graph_rag",
        relevant_strategies=frozenset({"graph_assisted", "standard"}),
        required_roles=_ALL_ROLES,
    ),
    ChatToolCapability(
        name="citation_preview",
        purpose="Preview source citations and evidence snippets for a retrieved chunk.",
        required_permission="chat:use",
        allowed_resource_types=["document", "chunk"],
        approval_required=False,
        feature_flag=None,
        relevant_strategies=_ALL_STRATEGIES,
        required_roles=_ALL_ROLES,
    ),
    ChatToolCapability(
        name="evaluation_lookup",
        purpose="Retrieve evaluation run results and quality metrics for admin review.",
        required_permission="evaluations:view",
        allowed_resource_types=["evaluation_run", "evaluation_set"],
        approval_required=False,
        feature_flag=None,
        relevant_strategies=frozenset({"standard", "troubleshooting"}),
        required_roles=_ELEVATED_ROLES,
    ),
    ChatToolCapability(
        name="feedback_creation",
        purpose="Record answer quality feedback for the active chat session.",
        required_permission="chat:use",
        allowed_resource_types=["feedback"],
        approval_required=False,
        feature_flag=None,
        relevant_strategies=_ALL_STRATEGIES,
        required_roles=_ALL_ROLES,
    ),
    ChatToolCapability(
        name="document_lifecycle_lookup",
        purpose="Look up document ingestion lifecycle status for troubleshooting.",
        required_permission="documents:manage",
        allowed_resource_types=["document"],
        approval_required=False,
        feature_flag=None,
        relevant_strategies=frozenset({"troubleshooting", "standard"}),
        required_roles=_ELEVATED_ROLES,
    ),
)

_CAPABILITY_BY_NAME: dict[str, ChatToolCapability] = {
    cap.name: cap for cap in CHAT_TOOL_CAPABILITIES
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ChatToolCallRecord:
    """Authorization and execution outcome for one tool capability."""

    tool_name: str
    tool_purpose: str
    authorized: bool
    executed: bool
    succeeded: bool
    fallback_used: bool
    latency_ms: int
    denial_reason: str | None = None
    error_code: str | None = None


@dataclass
class ToolOrchestrationResult:
    """Aggregated result of the tool orchestration step for a single chat query."""

    enabled: bool
    tool_calls: list[ChatToolCallRecord]
    orchestration_latency_ms: int = 0

    @property
    def authorized_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.authorized)

    @property
    def executed_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.executed)

    @property
    def succeeded_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.succeeded)

    @property
    def fallback_count(self) -> int:
        return sum(1 for t in self.tool_calls if t.fallback_used)

    @property
    def denied_count(self) -> int:
        return sum(1 for t in self.tool_calls if not t.authorized)

    @property
    def tool_count(self) -> int:
        return len(self.tool_calls)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ChatToolOrchestrator:
    """Selects and authorizes tool capabilities for the RAG chat pipeline.

    Authorization is pure — no DB access, no async. Callers must provide:
      - feature_availability: dict mapping settings attr names → resolved bool
      - disabled_tool_names: org-level disabled tools from AgentToolPolicyRepository
    """

    def __init__(
        self,
        *,
        capabilities: tuple[ChatToolCapability, ...] | None = None,
    ) -> None:
        self._capabilities = capabilities or CHAT_TOOL_CAPABILITIES

    def orchestrate(
        self,
        *,
        planner_strategy: str,
        principal: AuthenticatedPrincipal,
        feature_availability: dict[str, bool],
        disabled_tool_names: frozenset[str],
        source_scope_mode: str | None = None,
    ) -> ToolOrchestrationResult:
        """Return per-tool authorization decisions for the given query context.

        Tools not relevant to the planner_strategy are silently skipped.
        All other tools produce a ChatToolCallRecord (authorized or denied).
        """
        started = perf_counter()
        effective_permissions = _resolve_effective_permissions(principal)
        principal_roles = frozenset(r.strip().lower() for r in (principal.roles or []))

        records: list[ChatToolCallRecord] = []
        for cap in self._capabilities:
            if planner_strategy not in cap.relevant_strategies:
                continue

            cap_started = perf_counter()
            denial_reason = _check_authorization(
                cap=cap,
                principal_roles=principal_roles,
                effective_permissions=effective_permissions,
                feature_availability=feature_availability,
                disabled_tool_names=disabled_tool_names,
                source_scope_mode=source_scope_mode,
            )
            authorized = denial_reason is None
            latency_ms = int((perf_counter() - cap_started) * 1000)

            records.append(
                ChatToolCallRecord(
                    tool_name=cap.name,
                    tool_purpose=cap.purpose,
                    authorized=authorized,
                    executed=authorized,
                    succeeded=authorized,
                    fallback_used=not authorized,
                    latency_ms=latency_ms,
                    denial_reason=denial_reason,
                    error_code=None if authorized else "authorization_failed",
                )
            )
            _logger.debug(
                "chat.tool.authorization",
                tool_name=cap.name,
                authorized=authorized,
                denial_reason=denial_reason,
                planner_strategy=planner_strategy,
                user_id=principal.user_id,
                org_id=principal.organization_id,
            )

        orchestration_latency_ms = int((perf_counter() - started) * 1000)
        return ToolOrchestrationResult(
            enabled=True,
            tool_calls=records,
            orchestration_latency_ms=orchestration_latency_ms,
        )

    def list_capabilities(self) -> tuple[ChatToolCapability, ...]:
        return self._capabilities

    def get_capability(self, tool_name: str) -> ChatToolCapability | None:
        return _CAPABILITY_BY_NAME.get(tool_name)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_effective_permissions(principal: AuthenticatedPrincipal) -> frozenset[str]:
    """Derive effective permissions from principal roles or API key scopes."""
    if principal.api_key_permissions is not None:
        return principal.api_key_permissions
    effective: set[str] = set()
    for role in principal.roles:
        effective.update(ROLE_PERMISSIONS.get(role, frozenset()))
    return frozenset(effective)


def _check_authorization(
    *,
    cap: ChatToolCapability,
    principal_roles: frozenset[str],
    effective_permissions: frozenset[str],
    feature_availability: dict[str, bool],
    disabled_tool_names: frozenset[str],
    source_scope_mode: str | None,
) -> str | None:
    """Return a denial_reason string if authorization fails, else None."""
    if cap.name in disabled_tool_names:
        return "org_policy_disabled"

    if cap.feature_flag is not None and not feature_availability.get(cap.feature_flag, False):
        return "feature_unavailable"

    if not principal_roles.intersection(cap.required_roles):
        return "insufficient_role"

    if cap.required_permission and cap.required_permission not in effective_permissions:
        return "insufficient_permission"

    if cap.name == "collection_search" and source_scope_mode not in ("collection", "all", None):
        return "source_scope_mismatch"

    return None
