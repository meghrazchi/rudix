import pytest
from qdrant_client.http.models import MatchAny, MatchValue

from app.domains.documents.services.qdrant_filters import build_organization_filter


def test_build_organization_filter_requires_organization_id() -> None:
    with pytest.raises(ValueError):
        build_organization_filter(organization_id="  ")


def test_build_organization_filter_includes_organization_must_clause() -> None:
    payload_filter = build_organization_filter(organization_id="org-1")

    assert payload_filter.must is not None
    assert len(payload_filter.must) == 1

    organization_condition = payload_filter.must[0]
    assert organization_condition.key == "organization_id"
    assert isinstance(organization_condition.match, MatchValue)
    assert organization_condition.match.value == "org-1"


def test_build_organization_filter_uses_match_value_for_single_document() -> None:
    payload_filter = build_organization_filter(
        organization_id="org-1",
        document_ids=["doc-1"],
    )

    assert payload_filter.must is not None
    assert len(payload_filter.must) == 2

    document_condition = payload_filter.must[1]
    assert document_condition.key == "document_id"
    assert isinstance(document_condition.match, MatchValue)
    assert document_condition.match.value == "doc-1"


def test_build_organization_filter_uses_match_any_for_multiple_documents() -> None:
    payload_filter = build_organization_filter(
        organization_id="org-1",
        document_ids=[" doc-1 ", "doc-2", "doc-1", ""],
    )

    assert payload_filter.must is not None
    assert len(payload_filter.must) == 2

    document_condition = payload_filter.must[1]
    assert document_condition.key == "document_id"
    assert isinstance(document_condition.match, MatchAny)
    assert document_condition.match.any == ["doc-1", "doc-2"]


def test_build_organization_filter_includes_index_version_when_provided() -> None:
    payload_filter = build_organization_filter(
        organization_id="org-1",
        document_ids=["doc-1"],
        index_version="v2",
    )

    assert payload_filter.must is not None
    assert len(payload_filter.must) == 3

    index_condition = payload_filter.must[2]
    assert index_condition.key == "index_version"
    assert isinstance(index_condition.match, MatchValue)
    assert index_condition.match.value == "v2"


def test_build_organization_filter_rejects_blank_index_version() -> None:
    with pytest.raises(ValueError):
        build_organization_filter(
            organization_id="org-1",
            index_version=" ",
        )


def test_build_organization_filter_includes_chunk_level_when_provided() -> None:
    payload_filter = build_organization_filter(
        organization_id="org-1",
        document_ids=["doc-1"],
        chunk_level=1,
    )

    assert payload_filter.must is not None
    assert len(payload_filter.must) == 3

    chunk_level_condition = payload_filter.must[2]
    assert chunk_level_condition.key == "chunk_level"
    assert isinstance(chunk_level_condition.match, MatchValue)
    assert chunk_level_condition.match.value == 1


def test_build_organization_filter_omits_chunk_level_when_none() -> None:
    payload_filter = build_organization_filter(
        organization_id="org-1",
        chunk_level=None,
    )

    assert payload_filter.must is not None
    keys = [condition.key for condition in payload_filter.must]
    assert "chunk_level" not in keys
