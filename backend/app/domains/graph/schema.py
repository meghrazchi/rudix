"""Enterprise Graph schema: node labels, relationship types, and migration definitions (F280).

Migrations are repeatable — every DDL statement uses IF NOT EXISTS so the runner
can apply the same migration list on every startup without side-effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

NODE_LABELS: tuple[str, ...] = (
    "Document",
    "Chunk",
    "Entity",
    "Person",
    "Organization",
    "Customer",
    "Vendor",
    "Product",
    "Project",
    "Policy",
    "Contract",
    "Control",
    "Requirement",
    "Risk",
    "Ticket",
    "System",
    "Process",
    "Obligation",
)

RELATIONSHIP_TYPES: tuple[str, ...] = (
    "MENTIONS",
    "EVIDENCE_FOR",
    "RELATES_TO",
    "OWNS",
    "COVERS_CONTROL",
    "CONTAINS_OBLIGATION",
    "PROVIDES_SERVICE_TO",
    "SUPERSEDES",
    "AFFECTS",
    "DEPENDS_ON",
)

# ---------------------------------------------------------------------------
# Migration definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphMigration:
    version: str  # four-digit zero-padded, e.g. "0001"
    description: str
    statements: list[str] = field(default_factory=list)


MIGRATIONS: list[GraphMigration] = [
    GraphMigration(
        version="0001",
        description="Initial node-key constraints and indexes for Document, Chunk, and Entity",
        statements=[
            # --- Uniqueness / node-key constraints ---
            # Each pair of (organization_id, stable_id) must be unique.
            """CREATE CONSTRAINT document_org_document_key IF NOT EXISTS
FOR (d:Document) REQUIRE (d.organization_id, d.document_id) IS NODE KEY""",
            """CREATE CONSTRAINT chunk_org_chunk_key IF NOT EXISTS
FOR (c:Chunk) REQUIRE (c.organization_id, c.chunk_id) IS NODE KEY""",
            """CREATE CONSTRAINT entity_org_entity_key IF NOT EXISTS
FOR (e:Entity) REQUIRE (e.organization_id, e.entity_id) IS NODE KEY""",
            # --- Document indexes ---
            """CREATE INDEX document_workspace_id_idx IF NOT EXISTS
FOR (d:Document) ON (d.workspace_id)""",
            """CREATE INDEX document_source_chunk_id_idx IF NOT EXISTS
FOR (d:Document) ON (d.source_chunk_id)""",
            # --- Chunk indexes ---
            """CREATE INDEX chunk_organization_id_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.organization_id)""",
            """CREATE INDEX chunk_source_document_id_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.source_document_id)""",
            # --- Entity indexes ---
            """CREATE INDEX entity_organization_id_idx IF NOT EXISTS
FOR (e:Entity) ON (e.organization_id)""",
            """CREATE INDEX entity_type_idx IF NOT EXISTS
FOR (e:Entity) ON (e.entity_type)""",
            """CREATE INDEX entity_canonical_name_idx IF NOT EXISTS
FOR (e:Entity) ON (e.canonical_name)""",
            """CREATE INDEX entity_workspace_id_idx IF NOT EXISTS
FOR (e:Entity) ON (e.workspace_id)""",
            """CREATE INDEX entity_external_source_id_idx IF NOT EXISTS
FOR (e:Entity) ON (e.external_source_id)""",
        ],
    ),
    GraphMigration(
        version="0002",
        description="Provenance indexes for Chunk node: workspace_id, page_number, source_connector (F282)",
        statements=[
            """CREATE INDEX chunk_workspace_id_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.workspace_id)""",
            """CREATE INDEX chunk_page_number_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.page_number)""",
            """CREATE INDEX chunk_source_connector_idx IF NOT EXISTS
FOR (c:Chunk) ON (c.source_connector)""",
            """CREATE INDEX extraction_run_id_node_idx IF NOT EXISTS
FOR (r:ExtractionRun) ON (r.run_id)""",
        ],
    ),
    GraphMigration(
        version="0003",
        description=(
            "Relationship property indexes for relation status, relation_id, and confidence (F284). "
            "One index per relationship type is required by Neo4j for relationship property indexes."
        ),
        statements=[
            # relation_id index per typed relationship (needed for GET/PATCH/DELETE by id)
            *[
                f"""CREATE INDEX {rel_type.lower()}_relation_id_idx IF NOT EXISTS
FOR ()-[r:{rel_type}]-() ON (r.relation_id)"""
                for rel_type in (
                    "MENTIONS",
                    "OWNS",
                    "RELATES_TO",
                    "COVERS_CONTROL",
                    "CONTAINS_OBLIGATION",
                    "PROVIDES_SERVICE_TO",
                    "SUPERSEDES",
                    "AFFECTS",
                    "DEPENDS_ON",
                )
            ],
            # status index per typed relationship (needed for list-by-status filter)
            *[
                f"""CREATE INDEX {rel_type.lower()}_status_idx IF NOT EXISTS
FOR ()-[r:{rel_type}]-() ON (r.status)"""
                for rel_type in (
                    "MENTIONS",
                    "OWNS",
                    "RELATES_TO",
                    "COVERS_CONTROL",
                    "CONTAINS_OBLIGATION",
                    "PROVIDES_SERVICE_TO",
                    "SUPERSEDES",
                    "AFFECTS",
                    "DEPENDS_ON",
                )
            ],
        ],
    ),
]
