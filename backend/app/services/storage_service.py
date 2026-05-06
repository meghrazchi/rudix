class StorageService:
    """MinIO/S3 object storage abstraction."""

    async def create_upload_url(self, *, object_key: str, content_type: str) -> str:
        raise NotImplementedError
