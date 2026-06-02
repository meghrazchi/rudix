from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.domains.documents.services.duplicate_detection import (
    DuplicateDetectionResult,
    check_for_duplicate,
)

ORG_ID = uuid4()
CHECKSUM = "a" * 64
EXISTING_DOC_ID = uuid4()


@pytest.fixture
def mock_session() -> MagicMock:
    return MagicMock()


async def _run(coro):  # type: ignore[no-untyped-def]
    return await coro


@pytest.mark.asyncio
async def test_check_for_duplicate_disabled_returns_no_duplicate(
    mock_session: MagicMock,
) -> None:
    result = await check_for_duplicate(
        mock_session,
        checksum=CHECKSUM,
        organization_id=ORG_ID,
        enabled=False,
        action="reject",
    )
    assert result.is_duplicate is False
    assert result.action == "allow"
    assert result.existing_document_id is None


@pytest.mark.asyncio
async def test_check_for_duplicate_empty_checksum_returns_no_duplicate(
    mock_session: MagicMock,
) -> None:
    result = await check_for_duplicate(
        mock_session,
        checksum="",
        organization_id=ORG_ID,
        enabled=True,
        action="reject",
    )
    assert result.is_duplicate is False


@pytest.mark.asyncio
async def test_check_for_duplicate_no_match_returns_no_duplicate(
    mock_session: MagicMock,
) -> None:
    with patch(
        "app.domains.documents.services.duplicate_detection._repository"
        ".find_active_document_id_by_checksum",
        new_callable=AsyncMock,
        return_value=None,
    ):
        result = await check_for_duplicate(
            mock_session,
            checksum=CHECKSUM,
            organization_id=ORG_ID,
            enabled=True,
            action="warn",
        )
    assert result.is_duplicate is False
    assert result.existing_document_id is None


@pytest.mark.asyncio
async def test_check_for_duplicate_match_returns_duplicate_with_action_warn(
    mock_session: MagicMock,
) -> None:
    with patch(
        "app.domains.documents.services.duplicate_detection._repository"
        ".find_active_document_id_by_checksum",
        new_callable=AsyncMock,
        return_value=EXISTING_DOC_ID,
    ):
        result = await check_for_duplicate(
            mock_session,
            checksum=CHECKSUM,
            organization_id=ORG_ID,
            enabled=True,
            action="warn",
        )
    assert result.is_duplicate is True
    assert result.action == "warn"
    assert result.existing_document_id == EXISTING_DOC_ID


@pytest.mark.asyncio
async def test_check_for_duplicate_match_returns_duplicate_with_action_reject(
    mock_session: MagicMock,
) -> None:
    with patch(
        "app.domains.documents.services.duplicate_detection._repository"
        ".find_active_document_id_by_checksum",
        new_callable=AsyncMock,
        return_value=EXISTING_DOC_ID,
    ):
        result = await check_for_duplicate(
            mock_session,
            checksum=CHECKSUM,
            organization_id=ORG_ID,
            enabled=True,
            action="reject",
        )
    assert result.is_duplicate is True
    assert result.action == "reject"
    assert result.existing_document_id == EXISTING_DOC_ID


@pytest.mark.asyncio
async def test_check_for_duplicate_match_returns_duplicate_with_action_allow(
    mock_session: MagicMock,
) -> None:
    with patch(
        "app.domains.documents.services.duplicate_detection._repository"
        ".find_active_document_id_by_checksum",
        new_callable=AsyncMock,
        return_value=EXISTING_DOC_ID,
    ):
        result = await check_for_duplicate(
            mock_session,
            checksum=CHECKSUM,
            organization_id=ORG_ID,
            enabled=True,
            action="allow",
        )
    assert result.is_duplicate is True
    assert result.action == "allow"
