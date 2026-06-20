"""Dev/test seed utilities for the Enterprise Graph (F280).

Creates a small but representative sample graph in the configured Neo4j database.
Only intended for local development and integration test environments — never
call this against a production database.

Usage:
    python -m app.domains.graph.seed  (requires ENTERPRISE_GRAPH_ENABLED=true)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.core.logging import get_logger

logger = get_logger("graph.seed")

_ORG_ID = "seed-org-1"
_WORKSPACE_ID = "seed-ws-1"

_SEED_CYPHER = """
// Clear existing seed data (idempotent)
MATCH (n) WHERE n.organization_id = $org_id DETACH DELETE n;

// Documents
MERGE (d1:Document {organization_id: $org_id, document_id: 'doc-001'})
  SET d1.workspace_id = $workspace_id,
      d1.title        = 'Privacy Policy v2',
      d1.created_at   = $now;

MERGE (d2:Document {organization_id: $org_id, document_id: 'doc-002'})
  SET d2.workspace_id = $workspace_id,
      d2.title        = 'Vendor Agreement — Acme Corp',
      d2.created_at   = $now;

// Chunks
MERGE (c1:Chunk {organization_id: $org_id, chunk_id: 'chunk-001'})
  SET c1.source_document_id = 'doc-001',
      c1.position            = 0,
      c1.created_at          = $now;

MERGE (c2:Chunk {organization_id: $org_id, chunk_id: 'chunk-002'})
  SET c2.source_document_id = 'doc-002',
      c2.position            = 0,
      c2.created_at          = $now;

// Entities
MERGE (e1:Entity:Organization {organization_id: $org_id, entity_id: 'ent-org-001'})
  SET e1.entity_type    = 'Organization',
      e1.canonical_name = 'Acme Corp',
      e1.workspace_id   = $workspace_id;

MERGE (e2:Entity:Policy {organization_id: $org_id, entity_id: 'ent-pol-001'})
  SET e2.entity_type    = 'Policy',
      e2.canonical_name = 'Privacy Policy',
      e2.workspace_id   = $workspace_id;

MERGE (e3:Entity:Obligation {organization_id: $org_id, entity_id: 'ent-obl-001'})
  SET e3.entity_type    = 'Obligation',
      e3.canonical_name = 'Data retention: 90 days',
      e3.workspace_id   = $workspace_id;

// Relationships
MERGE (d1)-[:MENTIONS]->(e2);
MERGE (d2)-[:MENTIONS]->(e1);
MERGE (c1)-[:EVIDENCE_FOR]->(e2);
MERGE (c2)-[:EVIDENCE_FOR]->(e1);
MERGE (e2)-[:CONTAINS_OBLIGATION]->(e3);
MERGE (e1)-[:RELATES_TO]->(e2);
"""


async def seed_graph() -> None:
    """Populate the Neo4j database with sample graph data for development."""
    from app.clients.neo4j_client import get_driver, init_neo4j
    from app.core.config import settings

    if not settings.enterprise_graph_enabled:
        logger.warning("graph.seed.skipped", reason="enterprise_graph_disabled")
        return

    await init_neo4j()
    driver = get_driver()
    if driver is None:
        logger.error("graph.seed.failed", reason="driver_not_initialized")
        return

    params = {
        "org_id": _ORG_ID,
        "workspace_id": _WORKSPACE_ID,
        "now": datetime.now(UTC).isoformat(),
    }

    async with driver.session(database=settings.neo4j_database) as session:
        for stmt in _SEED_CYPHER.strip().split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            result = await session.run(stmt, **params)
            await result.consume()

    logger.info("graph.seed.complete", org_id=_ORG_ID, workspace_id=_WORKSPACE_ID)


if __name__ == "__main__":
    asyncio.run(seed_graph())
