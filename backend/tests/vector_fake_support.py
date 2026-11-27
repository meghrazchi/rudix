"""Point ledger for ``QdrantService`` test fakes (R06-06).

The ingestion index stage deletes points of other runs and checks the document's point
count after the embed stage. A fake that subclasses ``PointLedgerMixin`` records the
points its ``upsert_chunks`` receives (keyed like real point ids: document, index version,
chunk index) and answers those calls from that record. It never reuses vectors.
"""

from __future__ import annotations

from typing import Any


class PointLedgerMixin:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        original = cls.__dict__.get("upsert_chunks")
        if original is None:
            return

        async def upsert_chunks(self: Any, *args: Any, **call: Any) -> Any:
            result = await original(self, *args, **call)
            ledger = self.__dict__.setdefault("_ledger_points", {})
            for chunk in call.get("chunks") or []:
                key = (str(chunk.document_id), str(chunk.index_version), int(chunk.chunk_index))
                ledger[key] = call.get("ingest_run_id")
            return result

        cls.upsert_chunks = upsert_chunks  # type: ignore[attr-defined]

    def _points(self) -> dict[tuple[str, str, int], str | None]:
        return self.__dict__.setdefault("_ledger_points", {})

    async def find_reusable_vectors(self, **_: Any) -> dict[str, list[float]]:
        return {}

    async def delete_stale_document_points(
        self, *, document_id: Any, index_version: str, ingest_run_id: str, **_: Any
    ) -> None:
        points = self._points()
        for key in [k for k in points if k[:2] == (str(document_id), index_version)]:
            if points[key] != ingest_run_id:
                del points[key]
        self.__dict__.setdefault("stale_deletes", []).append(index_version)

    async def count_document_points(self, *, document_id: Any, index_version: str, **_: Any) -> int:
        return sum(1 for k in self._points() if k[:2] == (str(document_id), index_version))
