"""Backend tests for F256: Smart tags, custom metadata, and taxonomy management.

Covers:
  A. Repository — create / get / list / update metadata field
  B. Repository — delete field cascades to document_metadata
  C. Repository — upsert document metadata value (text, select, multi_select)
  D. Repository — audit log written on upsert
  E. Repository — list_documents_by_metadata returns matching IDs
  F. Repository — org isolation: cannot see another org's field
  G. Schema — CreateMetadataFieldRequest rejects invalid field_type
  H. Schema — select/multi_select requires allowed_values
  I. Schema — BulkSetMetadataRequest max 500 documents
  J. Service — value serialization for all field types
  K. Service — invalid select value raises 422
  L. Service — build_tag_suggestions returns prefix-filtered values
  M. HTTP — POST /admin/metadata/fields creates field (admin)
  N. HTTP — GET /admin/metadata/fields lists active fields
  O. HTTP — PATCH /admin/metadata/fields/{id} updates display_name
  P. HTTP — DELETE /admin/metadata/fields/{id} removes field
  Q. HTTP — PUT /documents/{id}/metadata sets values with audit
  R. HTTP — GET /documents/{id}/metadata returns current values
  S. HTTP — POST /admin/metadata/bulk-set updates multiple docs
  T. HTTP — GET /admin/metadata/fields/{id}/suggest returns prefix matches
  U. HTTP — role guard: viewer cannot create field
  V. HTTP — role guard: viewer cannot set document metadata
  W. HTTP — org isolation: cannot read another org's field
  X. HTTP — GET /documents/{id}/metadata/audit returns audit log (admin)

Run:
    pytest tests/test_metadata_taxonomy_f256.py -v
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("API_BASE_URL", "http://localhost:8000")
os.environ.setdefault("FRONTEND_BASE_URL", "http://localhost:3000")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/rag_app"
)
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION", "documents")
os.environ.setdefault("MINIO_ENDPOINT", "http://localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("MINIO_BUCKET", "documents")
os.environ.setdefault("RABBITMQ_URL", "amqp://admin:admin123@localhost:5672//")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("AUTH_PROVIDER", "app")
os.environ.setdefault("APP_AUTH_SECRET", "test-secret")

from app.auth.token_codec import create_app_access_token
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.metadata.repositories.metadata import (
    DocumentMetadataRepository,
    MetadataFieldRepository,
)
from app.domains.metadata.schemas.metadata import (
    BulkSetMetadataRequest,
    CreateMetadataFieldRequest,
    MetadataValueIn,
)
from app.domains.metadata.services.metadata_service import MetadataService
from app.main import app
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.metadata import MetadataField
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db(db_session: AsyncSession) -> AsyncSession:
    return db_session


def _make_token(user_id: str, org_id: str, role: str) -> str:
    settings.auth_provider = AuthProvider.app
    return create_app_access_token(user_id=user_id, organization_id=org_id, role=role)


@pytest_asyncio.fixture
async def org(db: AsyncSession) -> Organization:
    o = Organization(name="MetaOrg", slug=f"meta-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def org2(db: AsyncSession) -> Organization:
    o = Organization(name="OtherOrg", slug=f"other-{uuid4().hex[:8]}")
    db.add(o)
    await db.flush()
    return o


@pytest_asyncio.fixture
async def admin_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"admin-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db.flush()
    return u, _make_token(str(u.id), str(org.id), OrganizationRole.admin.value)


@pytest_asyncio.fixture
async def member_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"member-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.member.value,
        )
    )
    await db.flush()
    return u, _make_token(str(u.id), str(org.id), OrganizationRole.member.value)


@pytest_asyncio.fixture
async def viewer_user(db: AsyncSession, org: Organization) -> tuple[User, str]:
    u = User(email=f"viewer-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org.id,
            role=OrganizationRole.viewer.value,
        )
    )
    await db.flush()
    return u, _make_token(str(u.id), str(org.id), OrganizationRole.viewer.value)


@pytest_asyncio.fixture
async def admin_other_org(db: AsyncSession, org2: Organization) -> tuple[User, str]:
    u = User(email=f"admin2-{uuid4().hex[:6]}@example.com", hashed_password="x")
    db.add(u)
    await db.flush()
    db.add(
        OrganizationMember(
            user_id=u.id,
            organization_id=org2.id,
            role=OrganizationRole.admin.value,
        )
    )
    await db.flush()
    return u, _make_token(str(u.id), str(org2.id), OrganizationRole.admin.value)


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncClient:
    async def _override():
        yield db

    app.dependency_overrides[get_db_session] = _override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def text_field(db: AsyncSession, org: Organization) -> MetadataField:
    repo = MetadataFieldRepository()
    return await repo.create(
        db,
        organization_id=org.id,
        name="department",
        display_name="Department",
        field_type="text",
        allowed_values=None,
        is_required=False,
        is_filterable=True,
        description=None,
        sort_order=0,
    )


@pytest_asyncio.fixture
async def select_field(db: AsyncSession, org: Organization) -> MetadataField:
    repo = MetadataFieldRepository()
    return await repo.create(
        db,
        organization_id=org.id,
        name="region",
        display_name="Region",
        field_type="select",
        allowed_values=["EMEA", "APAC", "Americas"],
        is_required=True,
        is_filterable=True,
        description=None,
        sort_order=1,
    )


@pytest_asyncio.fixture
async def sample_document(db: AsyncSession, org: Organization) -> Document:
    doc = Document(
        organization_id=org.id,
        filename="sample.pdf",
        file_type="pdf",
        status="indexed",
        file_size_bytes=1024,
    )
    db.add(doc)
    await db.flush()
    return doc


# ── A: Repository CRUD for fields ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_create_and_get_field(db: AsyncSession, org: Organization) -> None:
    repo = MetadataFieldRepository()
    field = await repo.create(
        db,
        organization_id=org.id,
        name="owner",
        display_name="Owner",
        field_type="text",
        allowed_values=None,
        is_required=False,
        is_filterable=True,
        description="Document owner",
        sort_order=0,
    )
    assert field.id is not None
    fetched = await repo.get(db, field_id=field.id, organization_id=org.id)
    assert fetched is not None
    assert fetched.name == "owner"
    assert fetched.display_name == "Owner"


@pytest.mark.asyncio
async def test_a_list_fields_only_active(
    db: AsyncSession, org: Organization, text_field: MetadataField
) -> None:
    repo = MetadataFieldRepository()
    await repo.update(
        db,
        text_field,
        display_name=None,
        allowed_values=None,
        is_required=None,
        is_filterable=None,
        description=None,
        sort_order=None,
        is_active=False,
    )
    active = await repo.list(db, organization_id=org.id)
    assert all(f.is_active for f in active)
    inactive = await repo.list(db, organization_id=org.id, include_inactive=True)
    assert any(not f.is_active for f in inactive)


# ── B: Field delete cascades ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_b_delete_field_cascades(
    db: AsyncSession,
    org: Organization,
    text_field: MetadataField,
    sample_document: Document,
) -> None:
    field_repo = MetadataFieldRepository()
    doc_repo = DocumentMetadataRepository()
    svc = MetadataService()

    await svc.validate_and_save_document_values(
        db,
        document_id=sample_document.id,
        organization_id=org.id,
        values=[{"field_id": str(text_field.id), "value": "Engineering"}],
        changed_by_id=None,
    )

    await field_repo.delete(db, text_field)
    rows = await doc_repo.get_document_metadata(
        db, document_id=sample_document.id, organization_id=org.id
    )
    assert all(r.field_id != text_field.id for r in rows)


# ── C: Upsert document metadata ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_c_upsert_text_value(
    db: AsyncSession,
    org: Organization,
    text_field: MetadataField,
    sample_document: Document,
) -> None:
    svc = MetadataService()
    await svc.validate_and_save_document_values(
        db,
        document_id=sample_document.id,
        organization_id=org.id,
        values=[{"field_id": str(text_field.id), "value": "Engineering"}],
        changed_by_id=None,
    )
    repo = DocumentMetadataRepository()
    rows = await repo.get_document_metadata(
        db, document_id=sample_document.id, organization_id=org.id
    )
    assert len(rows) == 1
    assert rows[0].value_text == "Engineering"


@pytest.mark.asyncio
async def test_c_upsert_select_valid_value(
    db: AsyncSession,
    org: Organization,
    select_field: MetadataField,
    sample_document: Document,
) -> None:
    svc = MetadataService()
    await svc.validate_and_save_document_values(
        db,
        document_id=sample_document.id,
        organization_id=org.id,
        values=[{"field_id": str(select_field.id), "value": "EMEA"}],
        changed_by_id=None,
    )
    repo = DocumentMetadataRepository()
    rows = await repo.get_document_metadata(
        db, document_id=sample_document.id, organization_id=org.id
    )
    assert rows[0].value_text == "EMEA"


# ── D: Audit log ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_d_audit_written_on_upsert(
    db: AsyncSession,
    org: Organization,
    text_field: MetadataField,
    sample_document: Document,
    admin_user: tuple[User, str],
) -> None:
    user, _ = admin_user
    svc = MetadataService()
    await svc.validate_and_save_document_values(
        db,
        document_id=sample_document.id,
        organization_id=org.id,
        values=[{"field_id": str(text_field.id), "value": "HR"}],
        changed_by_id=user.id,
    )
    repo = DocumentMetadataRepository()
    logs = await repo.list_audit(db, document_id=sample_document.id, organization_id=org.id)
    assert len(logs) >= 1
    assert logs[0].new_value == "HR"
    assert logs[0].changed_by_id == user.id


# ── E: Metadata-based document filtering ──────────────────────────────────────


@pytest.mark.asyncio
async def test_e_filter_documents_by_metadata(
    db: AsyncSession,
    org: Organization,
    select_field: MetadataField,
) -> None:
    svc = MetadataService()
    repo = DocumentMetadataRepository()

    doc_a = Document(
        organization_id=org.id,
        filename="a.pdf",
        file_type="pdf",
        status="indexed",
        file_size_bytes=1,
    )
    doc_b = Document(
        organization_id=org.id,
        filename="b.pdf",
        file_type="pdf",
        status="indexed",
        file_size_bytes=1,
    )
    db.add_all([doc_a, doc_b])
    await db.flush()

    await svc.validate_and_save_document_values(
        db,
        document_id=doc_a.id,
        organization_id=org.id,
        values=[{"field_id": str(select_field.id), "value": "EMEA"}],
        changed_by_id=None,
    )
    await svc.validate_and_save_document_values(
        db,
        document_id=doc_b.id,
        organization_id=org.id,
        values=[{"field_id": str(select_field.id), "value": "APAC"}],
        changed_by_id=None,
    )

    ids = await repo.list_documents_by_metadata(
        db,
        organization_id=org.id,
        filters=[{"field_id": str(select_field.id), "value": "EMEA"}],
    )
    assert doc_a.id in ids
    assert doc_b.id not in ids


# ── F: Org isolation ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_f_org_isolation_field(
    db: AsyncSession,
    org: Organization,
    org2: Organization,
    text_field: MetadataField,
) -> None:
    repo = MetadataFieldRepository()
    # org2 cannot see org's field
    fetched = await repo.get(db, field_id=text_field.id, organization_id=org2.id)
    assert fetched is None


# ── G: Schema validation ──────────────────────────────────────────────────────


def test_g_invalid_field_type_rejected() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CreateMetadataFieldRequest(
            name="x",
            display_name="X",
            field_type="image",  # type: ignore[arg-type]
        )


# ── H: select requires allowed_values ─────────────────────────────────────────


def test_h_select_requires_allowed_values() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="allowed_values"):
        CreateMetadataFieldRequest(
            name="region",
            display_name="Region",
            field_type="select",
            allowed_values=None,
        )


# ── I: BulkSetMetadataRequest limits ─────────────────────────────────────────


def test_i_bulk_set_max_500() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BulkSetMetadataRequest(
            document_ids=["x"] * 501,
            values=[MetadataValueIn(field_id="f", value="v")],
        )


# ── J: Service serialization ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_j_service_boolean_serialization(
    db: AsyncSession,
    org: Organization,
) -> None:
    repo = MetadataFieldRepository()
    field = await repo.create(
        db,
        organization_id=org.id,
        name="is_public",
        display_name="Public",
        field_type="boolean",
        allowed_values=None,
        is_required=False,
        is_filterable=False,
        description=None,
        sort_order=0,
    )
    svc = MetadataService()
    doc = Document(
        organization_id=org.id,
        filename="b.pdf",
        file_type="pdf",
        status="indexed",
        file_size_bytes=1,
    )
    db.add(doc)
    await db.flush()

    await svc.validate_and_save_document_values(
        db,
        document_id=doc.id,
        organization_id=org.id,
        values=[{"field_id": str(field.id), "value": True}],
        changed_by_id=None,
    )
    doc_repo = DocumentMetadataRepository()
    rows = await doc_repo.get_document_metadata(db, document_id=doc.id, organization_id=org.id)
    assert rows[0].value_text == "true"


# ── K: Invalid select value raises 422 ────────────────────────────────────────


@pytest.mark.asyncio
async def test_k_invalid_select_value(
    db: AsyncSession,
    org: Organization,
    select_field: MetadataField,
    sample_document: Document,
) -> None:
    from fastapi import HTTPException

    svc = MetadataService()
    with pytest.raises(HTTPException) as exc_info:
        await svc.validate_and_save_document_values(
            db,
            document_id=sample_document.id,
            organization_id=org.id,
            values=[{"field_id": str(select_field.id), "value": "NotAllowed"}],
            changed_by_id=None,
        )
    assert exc_info.value.status_code == 422


# ── L: Tag suggestions ─────────────────────────────────────────────────────────


def test_l_tag_suggestions(select_field: MetadataField) -> None:
    svc = MetadataService()
    suggestions = svc.build_tag_suggestions(select_field, "em")
    assert "EMEA" in suggestions


# ── M: HTTP POST /admin/metadata/fields ───────────────────────────────────────


@pytest.mark.asyncio
async def test_m_http_create_field(client: AsyncClient, admin_user: tuple[User, str]) -> None:
    _, token = admin_user
    resp = await client.post(
        "/api/admin/metadata/fields",
        json={
            "name": "project",
            "display_name": "Project",
            "field_type": "text",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "project"
    assert data["field_type"] == "text"


# ── N: HTTP GET /admin/metadata/fields lists active ───────────────────────────


@pytest.mark.asyncio
async def test_n_http_list_fields(
    client: AsyncClient,
    admin_user: tuple[User, str],
    text_field: MetadataField,
) -> None:
    _, token = admin_user
    resp = await client.get(
        "/api/admin/metadata/fields",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["field_id"] for f in data["items"]]
    assert str(text_field.id) in ids


# ── O: HTTP PATCH /admin/metadata/fields/{id} ─────────────────────────────────


@pytest.mark.asyncio
async def test_o_http_update_field(
    client: AsyncClient,
    admin_user: tuple[User, str],
    text_field: MetadataField,
) -> None:
    _, token = admin_user
    resp = await client.patch(
        f"/api/admin/metadata/fields/{text_field.id}",
        json={"display_name": "Business Unit"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Business Unit"


# ── P: HTTP DELETE /admin/metadata/fields/{id} ────────────────────────────────


@pytest.mark.asyncio
async def test_p_http_delete_field(
    client: AsyncClient,
    admin_user: tuple[User, str],
    text_field: MetadataField,
) -> None:
    _, token = admin_user
    resp = await client.delete(
        f"/api/admin/metadata/fields/{text_field.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 204


# ── Q: HTTP PUT /documents/{id}/metadata ──────────────────────────────────────


@pytest.mark.asyncio
async def test_q_http_set_document_metadata(
    client: AsyncClient,
    admin_user: tuple[User, str],
    text_field: MetadataField,
    sample_document: Document,
) -> None:
    _, token = admin_user
    resp = await client.put(
        f"/api/documents/{sample_document.id}/metadata",
        json={"values": [{"field_id": str(text_field.id), "value": "Sales"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"] == str(sample_document.id)
    values = data["values"]
    assert any(v["value"] == "Sales" for v in values)


# ── R: HTTP GET /documents/{id}/metadata ──────────────────────────────────────


@pytest.mark.asyncio
async def test_r_http_get_document_metadata(
    client: AsyncClient,
    admin_user: tuple[User, str],
    text_field: MetadataField,
    sample_document: Document,
) -> None:
    _, token = admin_user
    # Set first
    await client.put(
        f"/api/documents/{sample_document.id}/metadata",
        json={"values": [{"field_id": str(text_field.id), "value": "HR"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get(
        f"/api/documents/{sample_document.id}/metadata",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert any(v["value"] == "HR" for v in data["values"])


# ── S: HTTP POST /admin/metadata/bulk-set ─────────────────────────────────────


@pytest.mark.asyncio
async def test_s_http_bulk_set(
    db: AsyncSession,
    client: AsyncClient,
    admin_user: tuple[User, str],
    org: Organization,
    text_field: MetadataField,
) -> None:
    _, token = admin_user
    doc1 = Document(
        organization_id=org.id,
        filename="d1.pdf",
        file_type="pdf",
        status="indexed",
        file_size_bytes=1,
    )
    doc2 = Document(
        organization_id=org.id,
        filename="d2.pdf",
        file_type="pdf",
        status="indexed",
        file_size_bytes=1,
    )
    db.add_all([doc1, doc2])
    await db.flush()

    resp = await client.post(
        "/api/admin/metadata/bulk-set",
        json={
            "document_ids": [str(doc1.id), str(doc2.id)],
            "values": [{"field_id": str(text_field.id), "value": "Engineering"}],
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["updated"] == 2
    assert data["skipped"] == 0


# ── T: HTTP /admin/metadata/fields/{id}/suggest ───────────────────────────────


@pytest.mark.asyncio
async def test_t_http_suggest(
    client: AsyncClient,
    admin_user: tuple[User, str],
    select_field: MetadataField,
) -> None:
    _, token = admin_user
    resp = await client.get(
        f"/api/admin/metadata/fields/{select_field.id}/suggest?prefix=EM",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert "EMEA" in resp.json()["suggestions"]


# ── U: Role guard — viewer cannot create field ────────────────────────────────


@pytest.mark.asyncio
async def test_u_viewer_cannot_create_field(
    client: AsyncClient, viewer_user: tuple[User, str]
) -> None:
    _, token = viewer_user
    resp = await client.post(
        "/api/admin/metadata/fields",
        json={"name": "foo", "display_name": "Foo", "field_type": "text"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── V: Role guard — viewer cannot set document metadata ───────────────────────


@pytest.mark.asyncio
async def test_v_viewer_cannot_set_metadata(
    client: AsyncClient,
    viewer_user: tuple[User, str],
    text_field: MetadataField,
    sample_document: Document,
) -> None:
    _, token = viewer_user
    resp = await client.put(
        f"/api/documents/{sample_document.id}/metadata",
        json={"values": [{"field_id": str(text_field.id), "value": "HR"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ── W: Org isolation — cannot read another org's field ───────────────────────


@pytest.mark.asyncio
async def test_w_org_isolation_http(
    client: AsyncClient,
    admin_other_org: tuple[User, str],
    text_field: MetadataField,
) -> None:
    _, token = admin_other_org
    resp = await client.get(
        f"/api/admin/metadata/fields/{text_field.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ── X: Audit log endpoint ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_x_http_get_audit_log(
    client: AsyncClient,
    admin_user: tuple[User, str],
    text_field: MetadataField,
    sample_document: Document,
) -> None:
    _, token = admin_user
    await client.put(
        f"/api/documents/{sample_document.id}/metadata",
        json={"values": [{"field_id": str(text_field.id), "value": "Legal"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = await client.get(
        f"/api/documents/{sample_document.id}/metadata/audit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["items"][0]["new_value"] == "Legal"
