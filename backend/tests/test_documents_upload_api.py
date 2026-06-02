import os
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Ensure strict settings can be loaded when importing modules in tests.
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

from app.auth.factory import get_auth_provider
from app.auth.token_codec import create_app_access_token
from app.clients import minio_client as minio_module
from app.core.config import AuthProvider, settings
from app.db.session import get_db_session
from app.domains.documents.services.malware_scan import MalwareScanResult
from app.interfaces.http import documents as documents_api
from app.main import app
from app.models.document import Document
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.usage import AuditLog
from app.models.user import User


class FakeMinio:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self.fail_put = False

    def put_object(self, **kwargs: Any) -> None:
        if self.fail_put:
            raise RuntimeError("minio put failure")
        self.put_calls.append(kwargs)

    def delete_object(self, **kwargs: Any) -> None:
        self.delete_calls.append(kwargs)


class FakeTaskResult:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class FakeProcessDocumentTask:
    def __init__(self) -> None:
        self.delay_calls: list[dict[str, Any]] = []
        self.fail_delay = False

    def delay(self, document_id: str, **kwargs: Any) -> FakeTaskResult:
        if self.fail_delay:
            raise RuntimeError("enqueue failure")
        self.delay_calls.append({"document_id": document_id, **kwargs})
        return FakeTaskResult(task_id=f"task-{len(self.delay_calls)}")


class FakeMalwareScanService:
    def __init__(self) -> None:
        self.next_result = MalwareScanResult(status="clean", duration_ms=2)
        self.calls: list[int] = []

    async def scan_bytes(self, *, content: bytes) -> MalwareScanResult:
        self.calls.append(len(content))
        return self.next_result


@pytest_asyncio.fixture
async def upload_client(
    monkeypatch: pytest.MonkeyPatch,
    db_session: AsyncSession,
) -> AsyncClient:
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.app)
    monkeypatch.setattr(settings, "app_auth_secret", SecretStr("test-secret"))
    monkeypatch.setattr(settings, "app_auth_issuer", "rudix-test")
    monkeypatch.setattr(settings, "app_auth_audience", "rudix-test-audience")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "max_upload_size_mb", 25)
    get_auth_provider.cache_clear()

    async def _override_get_db_session() -> AsyncSession:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def fake_minio(monkeypatch: pytest.MonkeyPatch) -> FakeMinio:
    fake = FakeMinio()
    monkeypatch.setattr(minio_module, "minio_client", fake)
    return fake


@pytest.fixture
def fake_process_document_task(monkeypatch: pytest.MonkeyPatch) -> FakeProcessDocumentTask:
    fake = FakeProcessDocumentTask()
    monkeypatch.setattr(documents_api, "process_document", fake)
    return fake


@pytest.fixture(autouse=True)
def fake_malware_scan_service(monkeypatch: pytest.MonkeyPatch) -> FakeMalwareScanService:
    fake = FakeMalwareScanService()
    monkeypatch.setattr(documents_api, "malware_scan_service", fake)
    return fake


async def _seed_principal(db_session: AsyncSession) -> tuple[User, Organization]:
    organization = Organization(name="Upload Org", slug=f"upload-org-{uuid4().hex[:8]}")
    db_session.add(organization)
    await db_session.flush()

    user = User(
        organization_id=organization.id,
        external_auth_id=f"user-{uuid4().hex[:8]}",
        email=f"user-{uuid4().hex[:8]}@example.com",
        display_name="Upload User",
    )
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=OrganizationRole.member.value,
        )
    )
    await db_session.commit()
    return user, organization


def _auth_headers(*, token: str, organization_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": organization_id,
    }


async def _document_count(db_session: AsyncSession) -> int:
    result = await db_session.execute(select(func.count(Document.id)))
    return int(result.scalar_one())


async def _get_document(db_session: AsyncSession, *, document_id: UUID) -> Document | None:
    result = await db_session.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content_type", "content"),
    [
        ("sample.pdf", "application/pdf", b"%PDF-1.7\nsample"),
        ("sample.txt", "text/plain", b"plain text"),
        (
            "sample.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"docx-bytes",
        ),
    ],
)
async def test_upload_accepts_supported_document_types(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
    fake_malware_scan_service: FakeMalwareScanService,
    filename: str,
    content_type: str,
    content: bytes,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["filename"] == filename
    assert payload["status"] == "uploaded"
    assert payload["queue_status"] == "queued"
    assert payload["checksum"]
    assert fake_malware_scan_service.calls == [len(content)]
    assert len(fake_minio.put_calls) == 1
    put_call = fake_minio.put_calls[0]
    assert put_call["Bucket"] == settings.minio_bucket
    assert put_call["ContentLength"] == len(content)
    assert put_call["ContentType"] == content_type

    document_id = UUID(payload["document_id"])
    expected_extension = filename.rsplit(".", maxsplit=1)[-1].lower()
    expected_key = f"uploads/{org.id}/{user.id}/{document_id}.{expected_extension}"
    assert put_call["Key"] == expected_key
    assert filename not in put_call["Key"]

    document = await _get_document(db_session, document_id=document_id)
    assert document is not None
    assert document.organization_id == org.id
    assert document.uploaded_by_user_id == user.id
    assert document.status == "uploaded"
    assert document.file_type == expected_extension
    assert document.storage_bucket == settings.minio_bucket
    assert document.storage_object_key == expected_key
    assert document.checksum == payload["checksum"]
    assert len(fake_process_document_task.delay_calls) == 1
    delay_call = fake_process_document_task.delay_calls[0]
    assert delay_call["document_id"] == payload["document_id"]
    assert delay_call["organization_id"] == str(org.id)
    assert delay_call["user_id"] == str(user.id)
    assert await _document_count(db_session) == 1
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "document.upload.accepted"
    assert audit_logs[0].resource_type == "document"
    assert audit_logs[0].resource_id == document.id
    assert audit_logs[0].metadata_json["file_type"] == expected_extension
    assert audit_logs[0].metadata_json["file_size_bytes"] == len(content)
    assert audit_logs[0].metadata_json["request_id"]


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_extension(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.exe", b"binary", "application/x-msdownload")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported file extension"
    assert len(fake_minio.put_calls) == 0
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_mime_type(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.pdf", b"%PDF-1.7", "text/plain")},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "unsupported mime type"
    assert len(fake_minio.put_calls) == 0
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_rejects_oversized_file(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"a" * (1024 * 1024 + 1), "text/plain")},
    )

    assert response.status_code == 413
    assert len(fake_minio.put_calls) == 0
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_rejects_empty_file(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "empty file"
    assert len(fake_minio.put_calls) == 0
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_allows_duplicate_files_as_distinct_documents(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )
    file_payload = ("duplicate.txt", b"same content", "text/plain")

    first_response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": file_payload},
    )
    second_response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": file_payload},
    )

    assert first_response.status_code == 201
    assert second_response.status_code == 201

    first_payload = first_response.json()
    second_payload = second_response.json()
    assert first_payload["document_id"] != second_payload["document_id"]
    assert first_payload["checksum"] == second_payload["checksum"]
    assert len(fake_minio.put_calls) == 2
    assert fake_minio.put_calls[0]["Key"] != fake_minio.put_calls[1]["Key"]
    assert len(fake_process_document_task.delay_calls) == 2
    assert (
        fake_process_document_task.delay_calls[0]["document_id"]
        != fake_process_document_task.delay_calls[1]["document_id"]
    )
    assert await _document_count(db_session) == 2


@pytest.mark.asyncio
async def test_upload_returns_503_when_storage_upload_fails(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    fake_minio.fail_put = True
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"safe payload", "text/plain")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Upload storage operation failed"
    assert len(fake_minio.put_calls) == 0
    assert len(fake_minio.delete_calls) == 0
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_deletes_uploaded_object_when_metadata_persist_fails(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise_create_document(*_: Any, **__: Any) -> None:
        raise RuntimeError("metadata failure")

    monkeypatch.setattr(
        documents_api.document_repository, "create_document", _raise_create_document
    )

    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"safe payload", "text/plain")},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to persist document metadata"
    assert len(fake_minio.put_calls) == 1
    assert len(fake_minio.delete_calls) == 1
    assert fake_minio.delete_calls[0]["Bucket"] == settings.minio_bucket
    assert fake_minio.delete_calls[0]["Key"] == fake_minio.put_calls[0]["Key"]
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_returns_503_when_enqueue_fails_and_document_stays_uploaded(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    fake_process_document_task.fail_delay = True
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"safe payload", "text/plain")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Document uploaded but could not be queued for processing"
    assert len(fake_minio.put_calls) == 1
    assert len(fake_minio.delete_calls) == 0
    assert await _document_count(db_session) == 1

    result = await db_session.execute(select(Document))
    document = result.scalar_one()
    assert document.status == "uploaded"
    assert await _document_count(db_session) == 1
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 2
    actions = {row.action for row in audit_logs}
    assert actions == {"document.upload.accepted", "document.upload.enqueue_failed"}


@pytest.mark.asyncio
async def test_upload_rejects_malware_and_does_not_persist_or_enqueue(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
    fake_malware_scan_service: FakeMalwareScanService,
) -> None:
    fake_malware_scan_service.next_result = MalwareScanResult(
        status="infected",
        signature="Eicar-Test-Signature",
        duration_ms=5,
    )
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"safe payload", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "File failed security scan"
    assert len(fake_minio.put_calls) == 0
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "document.upload.rejected_malware"
    assert audit_logs[0].metadata_json["scanner"] == "clamav"
    assert audit_logs[0].metadata_json["scanner_result"] == "infected"
    assert audit_logs[0].metadata_json["signature"] == "Eicar-Test-Signature"


@pytest.mark.asyncio
async def test_upload_fails_closed_when_scan_required_and_scanner_unavailable(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
    fake_malware_scan_service: FakeMalwareScanService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "malware_scan_required", True)
    monkeypatch.setattr(settings, "malware_scan_bypass_on_unavailable", False)
    fake_malware_scan_service.next_result = MalwareScanResult(
        status="error",
        error_type="unavailable",
        duration_ms=7,
    )
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"safe payload", "text/plain")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "File security scan unavailable"
    assert len(fake_minio.put_calls) == 0
    assert len(fake_process_document_task.delay_calls) == 0
    assert await _document_count(db_session) == 0
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    assert len(audit_logs) == 1
    assert audit_logs[0].action == "document.upload.scan_unavailable_rejected"
    assert audit_logs[0].metadata_json["scanner_result"] == "error"
    assert audit_logs[0].metadata_json["error_type"] == "unavailable"


@pytest.mark.asyncio
async def test_upload_bypasses_unavailable_scanner_when_explicitly_enabled_in_non_production(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
    fake_malware_scan_service: FakeMalwareScanService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "malware_scan_required", True)
    monkeypatch.setattr(settings, "malware_scan_bypass_on_unavailable", True)
    fake_malware_scan_service.next_result = MalwareScanResult(
        status="error",
        error_type="unavailable",
        duration_ms=4,
    )
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("sample.txt", b"safe payload", "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["queue_status"] == "queued"
    assert len(fake_minio.put_calls) == 1
    assert len(fake_process_document_task.delay_calls) == 1
    assert await _document_count(db_session) == 1
    audit_logs = list((await db_session.execute(select(AuditLog))).scalars().all())
    actions = {row.action for row in audit_logs}
    assert actions == {"document.upload.scan_unavailable_bypassed", "document.upload.accepted"}


@pytest.mark.asyncio
async def test_upload_stores_metadata_fields(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("report.pdf", b"%PDF-1.7\nsample", "application/pdf")},
        data={
            "source": "https://internal.example.com/report",
            "language": "en",
            "retention_class": "confidential",
            "notes": "Quarterly compliance report",
            "tags": "compliance,quarterly,legal",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["collection_assigned"] is False

    document_id = UUID(payload["document_id"])
    document = await _get_document(db_session, document_id=document_id)
    assert document is not None
    assert document.source == "https://internal.example.com/report"
    assert document.language == "en"
    assert document.retention_class == "confidential"
    assert document.notes == "Quarterly compliance report"
    assert document.tags == "compliance,quarterly,legal"


@pytest.mark.asyncio
async def test_upload_rejects_invalid_language_code(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("report.pdf", b"%PDF-1.7\nsample", "application/pdf")},
        data={"language": "klingon"},
    )

    assert response.status_code == 422
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_rejects_invalid_retention_class(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("report.pdf", b"%PDF-1.7\nsample", "application/pdf")},
        data={"retention_class": "super_secret"},
    )

    assert response.status_code == 422
    assert await _document_count(db_session) == 0


@pytest.mark.asyncio
async def test_upload_with_collection_auto_assigns_document(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    from app.models.collection import Collection, CollectionDocument

    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    collection = Collection(
        organization_id=org.id,
        owner_id=user.id,
        name="Legal Docs",
        access_policy="org_wide",
    )
    db_session.add(collection)
    await db_session.commit()

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("contract.pdf", b"%PDF-1.7\ncontent", "application/pdf")},
        data={"collection_id": str(collection.id)},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["collection_assigned"] is True

    document_id = UUID(payload["document_id"])
    result = await db_session.execute(
        select(CollectionDocument).where(
            CollectionDocument.document_id == document_id,
            CollectionDocument.collection_id == collection.id,
        )
    )
    assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_upload_with_unknown_collection_id_skips_assignment(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("note.txt", b"plain text", "text/plain")},
        data={"collection_id": str(uuid4())},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["collection_assigned"] is False
    assert await _document_count(db_session) == 1


@pytest.mark.asyncio
async def test_upload_without_metadata_succeeds_with_defaults(
    upload_client: AsyncClient,
    db_session: AsyncSession,
    fake_minio: FakeMinio,
    fake_process_document_task: FakeProcessDocumentTask,
) -> None:
    user, org = await _seed_principal(db_session)
    token = create_app_access_token(
        subject=user.external_auth_id, organization_id=str(org.id), expires_in_seconds=600
    )

    response = await upload_client.post(
        "/api/v1/documents/upload",
        headers=_auth_headers(token=token, organization_id=str(org.id)),
        files={"file": ("readme.txt", b"hello world", "text/plain")},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["collection_assigned"] is False

    document_id = UUID(payload["document_id"])
    document = await _get_document(db_session, document_id=document_id)
    assert document is not None
    assert document.source is None
    assert document.language is None
    assert document.retention_class is None
    assert document.notes is None
    assert document.tags is None
